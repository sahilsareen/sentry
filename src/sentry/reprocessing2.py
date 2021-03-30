"""
Reprocessing allows a user to re-enqueue all events of a group at the start of
preprocess-event, for example to reattempt symbolication of stacktraces or
reattempt grouping.

How reprocessing works
======================

1. In `start_group_reprocessing`, the group is put into REPROCESSING state. In
   this state it must not be modified or receive events. Much like with group
   merging, all its hashes are detached, they are moved to a new, empty group.

   The group gets a new activity entry that contains metadata about who
   triggered reprocessing with how many events. This is purely to serve UI.

   If a user at this point navigates to the group, they will not be able to
   interact with it at all, but only watch the progress of reprocessing.

2. All events from the group are iterated through and enqueued into
   preprocess_event. The event payload is taken from a backup that was made on
   first ingestion in preprocess_event.

3. wait_group_reprocessed in sentry.tasks.reprocessing2 polls a counter in
   Redis to see if reprocessing is done. When it reaches zero, all associated
   models like assignee and activity are moved into the new group.

   A group redirect is installed. The old group is deleted, while the new group
   is unresolved. This effectively unsets the REPROCESSING status.

   A user looking at the progressbar on the old group's URL is supposed to be
   redirected at this point. The new group can either:

   a. Have events by itself, but also show a success message based on the data in activity.
   b. Be totally empty but suggest a search for original_issue_id based on data in activity.

   However, there's no special flag for whether that new group has been a
   result of reprocessing.

Why not mutate the group in-place? (and how reprocessing actually works)
========================================================================

Snuba is only able to delete entire groups at once. How group deletion works
internally:

* A new row is inserted into the events table with the same event_id, but a
  `deleted=1` property. This row by itself would naturally appear as a new
  event with the same event ID, however Snuba adds `and not deleted` to every query.

* The group ID is added to a Redis set of "temporarily excluded group IDs".
  This set is now appended to every query: `and group_id not in (<long list of
  deleted group IDs>)`

* Every n hours, ClickHouse folds rows with duplicate primary keys into one
  row. Now only the `deleted=1` row of the deleted event remains. This process
  is basically rewriting the table, and as such itself takes a couple of hours.

  After that the Redis set can be cleared out.

As such, reusing the group ID will not work as the Redis set will prevent
any events in that group from being searchable. We can also not skip the Redis
part specifically for reprocessing: When the user chooses to process `x` out of
`n` events, the other `n - x` events would randomly appear within search
results until the next table rewrite is done.

One could in theory store individual event IDs in Redis that should be excluded
from all queries. However, this blows up the size of all queries within a
project until the next table rewrite is done, and slows down all searches. In
theory this slowdown can also happen if one chose to delete a lot of groups
within a project.

There is the additional complication that the `deleted=1` row "wins" over any
other row one may insert at a later point. So what reprocessing actually does
instead of group deletion is:

* Insert `deleted=1` for all events that are *not* supposed to be reprocessed.
* Mark the group as deleted in Redis.
* All reprocessed events are "just" inserted over the old ones.
"""

import hashlib
import logging
import sentry_sdk
from sentry.utils import json

from django.conf import settings

from sentry import nodestore, eventstore, models, options
from sentry.eventstore.models import Event
from sentry.attachments import CachedAttachment, attachment_cache
from sentry.utils import snuba
from sentry.utils.cache import cache_key_for_event
from sentry.utils.safe import set_path, get_path, safe_execute
from sentry.utils.redis import redis_clusters
from sentry.eventstore.processing import event_processing_store
from sentry.deletions.defaults.group import DIRECT_GROUP_RELATED_MODELS

logger = logging.getLogger("sentry.reprocessing")

_REDIS_SYNC_TTL = 3600 * 24


# Note: Event attachments and group reports are migrated in save_event.
GROUP_MODELS_TO_MIGRATE = DIRECT_GROUP_RELATED_MODELS + (models.Activity,)

# If we were to move groupinbox to the new, empty group, inbox would show the
# empty, unactionable group while it is reprocessing. Let post-process take
# care of assigning GroupInbox like normally.
GROUP_MODELS_TO_MIGRATE = tuple(x for x in GROUP_MODELS_TO_MIGRATE if x != models.GroupInbox)


class CannotReprocess(Exception):
    pass


def _generate_unprocessed_event_node_id(project_id, event_id):
    return hashlib.md5(f"{project_id}:{event_id}:unprocessed".encode("utf-8")).hexdigest()


def save_unprocessed_event(project, event_id):
    """
    Move event from event_processing_store into nodestore. Only call if event
    has outcome=accepted.
    """
    with sentry_sdk.start_span(
        op="sentry.reprocessing2.save_unprocessed_event.get_unprocessed_event"
    ):
        data = event_processing_store.get(
            cache_key_for_event({"project": project.id, "event_id": event_id}), unprocessed=True
        )
        if data is None:
            return

    with sentry_sdk.start_span(op="sentry.reprocessing2.save_unprocessed_event.set_nodestore"):
        node_id = _generate_unprocessed_event_node_id(project_id=project.id, event_id=event_id)
        nodestore.set(node_id, data)


def backup_unprocessed_event(project, data):
    """
    Backup unprocessed event payload into redis. Only call if event should be
    able to be reprocessed.
    """

    if options.get("store.reprocessing-force-disable"):
        return

    event_processing_store.store(dict(data), unprocessed=True)


def reprocess_event(project_id, event_id, start_time):

    from sentry.tasks.store import preprocess_event_from_reprocessing
    from sentry.ingest.ingest_consumer import CACHE_TIMEOUT
    from sentry.plugins.base import plugins

    with sentry_sdk.start_span(op="reprocess_events.nodestore.get"):
        node_id = Event.generate_node_id(project_id, event_id)
        data = nodestore.get(node_id, subkey="unprocessed")
        if data is None:
            node_id = _generate_unprocessed_event_node_id(project_id=project_id, event_id=event_id)
            data = nodestore.get(node_id)

    if data is None:
        raise CannotReprocess("reprocessing_nodestore.not_found")

    with sentry_sdk.start_span(op="reprocess_events.eventstore.get"):
        event = eventstore.get_event_by_id(project_id, event_id)

    if event is None:
        raise CannotReprocess("event.not_found")

    attachments = list(
        models.EventAttachment.objects.filter(project_id=project_id, event_id=event_id)
    )
    files = {f.id: f for f in models.File.objects.filter(id__in=[ea.file_id for ea in attachments])}

    missing_attachment_types = set()

    for plugin in plugins.all(version=2):
        for ty in (
            safe_execute(plugin.get_required_attachment_types, data, _with_transaction=False) or ()
        ):
            missing_attachment_types.add(ty)

    for ea in attachments:
        missing_attachment_types.discard(ea.type)

    if missing_attachment_types:
        raise CannotReprocess(
            f"attachment.not_found.{'_and_'.join(sorted(missing_attachment_types))}"
        )

    # Step 1: Fix up the event payload for reprocessing and put it in event
    # cache/event_processing_store
    set_path(data, "contexts", "reprocessing", "original_issue_id", value=event.group_id)
    set_path(
        data, "contexts", "reprocessing", "original_primary_hash", value=event.get_primary_hash()
    )
    cache_key = event_processing_store.store(data)

    # Step 2: Copy attachments into attachment cache
    attachment_objects = []

    for attachment_id, attachment in enumerate(attachments):
        with sentry_sdk.start_span(op="reprocess_event._copy_attachment_into_cache") as span:
            span.set_data("attachment_id", attachment.id)
            attachment_objects.append(
                _copy_attachment_into_cache(
                    attachment_id=attachment_id,
                    attachment=attachment,
                    file=files[attachment.file_id],
                    cache_key=cache_key,
                    cache_timeout=CACHE_TIMEOUT,
                )
            )

    if attachment_objects:
        with sentry_sdk.start_span(op="reprocess_event.set_attachment_meta"):
            attachment_cache.set(cache_key, attachments=attachment_objects, timeout=CACHE_TIMEOUT)

    preprocess_event_from_reprocessing.delay(
        cache_key=cache_key, start_time=start_time, event_id=event_id
    )


def delete_old_primary_hash(event):
    """In case the primary hash changed during reprocessing, we need to tell
    Snuba before reinserting the event. Snuba may then insert a tombstone row
    depending on whether the primary_hash is part of the PK/sortkey or not.

    Only when the primary_hash changed and is part of the sortkey, we need to
    explicitly tombstone the old row.

    If the primary_hash is not part of the PK/sortkey, or if the primary_hash
    did not change, nothing needs to be done as ClickHouse's table merge will
    merge the two rows together.
    """

    old_primary_hash = get_path(event.data, "contexts", "reprocessing", "original_primary_hash")

    if old_primary_hash is not None and old_primary_hash != event.get_primary_hash():
        from sentry import eventstream

        eventstream.tombstone_events_unsafe(
            event.project_id,
            [event.event_id],
            old_primary_hash=old_primary_hash,
        )


def _copy_attachment_into_cache(attachment_id, attachment, file, cache_key, cache_timeout):
    fp = file.getfile()
    chunk_index = 0
    size = 0
    while True:
        chunk = fp.read(settings.SENTRY_REPROCESSING_ATTACHMENT_CHUNK_SIZE)
        if not chunk:
            break

        size += len(chunk)

        attachment_cache.set_chunk(
            key=cache_key,
            id=attachment_id,
            chunk_index=chunk_index,
            chunk_data=chunk,
            timeout=cache_timeout,
        )
        chunk_index += 1

    assert size == file.size

    return CachedAttachment(
        key=cache_key,
        id=attachment_id,
        name=attachment.name,
        # XXX: Not part of eventattachment model, but not strictly
        # necessary for processing
        content_type=None,
        type=file.type,
        chunks=chunk_index,
        size=size,
    )


def is_reprocessed_event(data):
    return bool(_get_original_issue_id(data))


def _get_original_issue_id(data):
    return get_path(data, "contexts", "reprocessing", "original_issue_id")


def _get_sync_redis_client():
    return redis_clusters.get(settings.SENTRY_REPROCESSING_SYNC_REDIS_CLUSTER)


def _get_sync_counter_key(group_id):
    return f"re2:count:{group_id}"


def _get_info_reprocessed_key(group_id):
    return f"re2:info:{group_id}"


def mark_event_reprocessed(data):
    """
    This function is supposed to be unconditionally called when an event has
    finished reprocessing, regardless of whether it has been saved or not.
    """
    group_id = _get_original_issue_id(data)
    if group_id is None:
        return

    key = _get_sync_counter_key(_get_original_issue_id(data))
    if _get_sync_redis_client().decr(key) == 0:
        from sentry.tasks.reprocessing2 import finish_reprocessing

        finish_reprocessing.delay(project_id=data["project"], group_id=group_id)


def start_group_reprocessing(
    project_id, group_id, remaining_events, max_events=None, acting_user_id=None
):
    from django.db import transaction

    with transaction.atomic():
        group = models.Group.objects.get(id=group_id)
        original_status = group.status
        if original_status == models.GroupStatus.REPROCESSING:
            # This is supposed to be a rather unlikely UI race when two people
            # click reprocessing in the UI at the same time.
            #
            # During reprocessing the button is greyed out.
            raise RuntimeError("Cannot reprocess group that is currently being reprocessed")

        original_short_id = group.short_id
        group.status = models.GroupStatus.REPROCESSING
        # satisfy unique constraint of (project_id, short_id)
        # we manually tested that multiple groups with (project_id=1,
        # short_id=null) can exist in postgres
        group.short_id = None
        group.save()

        # Create a duplicate row that has the same attributes by nulling out
        # the primary key and saving
        group.pk = group.id = None
        new_group = group  # rename variable just to avoid confusion
        del group
        new_group.status = original_status
        new_group.short_id = original_short_id

        if remaining_events == "keep":
            # this will be incremented by the events that are reprocessed
            if max_events is not None:
                new_group.times_seen -= max_events
        elif remaining_events == "delete":
            new_group.times_seen = 0
        else:
            raise ValueError(remaining_events)

        new_group.save()

        # This migrates all models that are associated with a group but not
        # directly with an event, i.e. everything but event attachments and user
        # reports. Those other updates are run per-event (in
        # post-process-forwarder) to not cause too much load on pg.
        for model in GROUP_MODELS_TO_MIGRATE:
            model.objects.filter(group_id=group_id).update(group_id=new_group.id)

    # Get event counts of issue (for all environments etc). This was copypasted
    # and simplified from groupserializer.
    event_count = snuba.aliased_query(
        aggregations=[["count()", "", "times_seen"]],  # select
        dataset=snuba.Dataset.Events,  # from
        conditions=[["group_id", "=", group_id], ["project_id", "=", project_id]],  # where
        referrer="reprocessing2.start_group_reprocessing",
    )["data"][0]["times_seen"]

    if max_events is not None:
        event_count = min(event_count, max_events)

    # Create activity on *old* group as that will serve the landing page for our
    # reprocessing status
    #
    # Later the activity is migrated to the new group where it is used to serve
    # the success message.
    new_activity = models.Activity.objects.create(
        type=models.Activity.REPROCESS,
        project=new_group.project,
        ident=str(group_id),
        group_id=group_id,
        user_id=acting_user_id,
        data={"eventCount": event_count, "oldGroupId": group_id, "newGroupId": new_group.id},
    )

    # New Activity Timestamp
    date_created = new_activity.datetime

    client = _get_sync_redis_client()
    client.setex(_get_sync_counter_key(group_id), _REDIS_SYNC_TTL, event_count)
    client.setex(
        _get_info_reprocessed_key(group_id),
        _REDIS_SYNC_TTL,
        json.dumps({"dateCreated": date_created, "totalEvents": event_count}),
    )

    return new_group.id


def is_group_finished(group_id):
    """
    Checks whether a group has finished reprocessing.
    """

    pending, _ = get_progress(group_id)
    return pending <= 0


def get_progress(group_id):
    pending = _get_sync_redis_client().get(_get_sync_counter_key(group_id))
    info = _get_sync_redis_client().get(_get_info_reprocessed_key(group_id))
    if pending is None:
        logger.error("reprocessing2.missing_counter")
        return 0, None
    if info is None:
        logger.error("reprocessing2.missing_info")
        return 0, None
    return int(pending), json.loads(info)
