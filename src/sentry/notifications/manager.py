from django.db import transaction
from django.db.models import Q
from typing import Iterable, List, Optional

from sentry.db.models import BaseManager, QuerySet
from sentry.models.integration import ExternalProviders
from sentry.notifications.helpers import (
    get_scope,
    get_scope_type,
    get_target,
    should_user_be_notified,
    transform_to_notification_settings_by_user,
    validate,
)
from sentry.notifications.types import (
    NotificationScopeType,
    NotificationSettingOptionValues,
    NotificationSettingTypes,
)
from sentry.notifications.legacy_mappings import (
    KEYS_TO_LEGACY_KEYS,
    get_legacy_key,
    get_legacy_value,
)


class NotificationsManager(BaseManager):
    """
    TODO(mgaeta): Add a caching layer for notification settings
    """

    def get_settings(
        self,
        provider: ExternalProviders,
        type: NotificationSettingTypes,
        user: Optional = None,
        team: Optional = None,
        project: Optional = None,
        organization: Optional = None,
    ) -> NotificationSettingOptionValues:
        """
        In this temporary implementation, always read EMAIL settings from
        UserOptions. One and only one of (user, team, project, or organization)
        must not be null. This function automatically translates a missing DB
        row to NotificationSettingOptionValues.DEFAULT.
        """
        from sentry.models import UserOption

        setting_option = self.find_settings(
            provider, type, user, team, project, organization
        ).first()
        value = setting_option.value if setting_option else NotificationSettingOptionValues.DEFAULT

        legacy_value = UserOption.objects.get_value(
            user, get_legacy_key(type), project=project, organization=organization
        )
        assert get_legacy_value(type, value) == legacy_value

        return value

    def update_settings(
        self,
        provider: ExternalProviders,
        type: NotificationSettingTypes,
        value: NotificationSettingOptionValues,
        user: Optional = None,
        team: Optional = None,
        project: Optional = None,
        organization: Optional = None,
    ) -> None:
        """
        Save a target's notification preferences.
        Examples:
          * Updating a user's org-independent preferences
          * Updating a user's per-project preferences
          * Updating a user's per-organization preferences
        """
        from sentry.models import UserOption

        # A missing DB row is equivalent to DEFAULT.
        if value == NotificationSettingOptionValues.DEFAULT:
            return self.remove_settings(
                provider,
                type,
                user=user,
                team=team,
                project=project,
                organization=organization,
            )

        if not validate(type, value):
            raise Exception(f"value '{value}' is not valid for type '{type}'")

        user_id_option = getattr(user, "id", None)
        scope_type, scope_identifier = get_scope(
            user_id_option, project=project, organization=organization
        )
        target = get_target(user, team)

        key = get_legacy_key(type)
        legacy_value = get_legacy_value(type, value)

        # Annoying HACK to translate "subscribe_by_default"
        if type == NotificationSettingTypes.ISSUE_ALERTS:
            legacy_value = int(legacy_value)
            if project is None:
                key = "subscribe_by_default"

        with transaction.atomic():
            setting, created = self.get_or_create(
                provider=provider.value,
                type=type.value,
                scope_type=scope_type.value,
                scope_identifier=scope_identifier,
                target=target,
                defaults={"value": value.value},
            )
            if not created and setting.value != value.value:
                setting.update(value=value.value)

            if target.type == 1:
                UserOption.objects.set_value(
                    user, key=key, value=legacy_value, project=project, organization=organization
                )

    def remove_settings(
        self,
        provider: ExternalProviders,
        type: NotificationSettingTypes,
        user: Optional = None,
        team: Optional = None,
        project: Optional = None,
        organization: Optional = None,
    ) -> None:
        """
        We don't anticipate this function will be used by the API but is useful
        for tests. This can also be called by `update_settings` when attempting
        to set a notification preference to DEFAULT.
        """
        from sentry.models import UserOption

        with transaction.atomic():
            self.find_settings(provider, type, user, team, project, organization).delete()
            UserOption.objects.unset_value(user, project, get_legacy_key(type))

    def _filter(
        self,
        provider: Optional[ExternalProviders] = None,
        type: Optional[NotificationSettingTypes] = None,
        scope_type: Optional[NotificationScopeType] = None,
        scope_identifier: Optional[int] = None,
        targets: Optional[Iterable] = None,
    ) -> QuerySet:
        """ Wrapper for .filter that translates types to actual attributes to column types. """
        filters = {}
        if provider:
            filters["provider"] = provider.value

        if type:
            filters["type"] = type.value

        if scope_type:
            filters["scope_type"] = scope_type.value

        if scope_identifier:
            filters["scope_identifier"] = scope_identifier

        if targets:
            filters["target__in"] = targets

        return self.filter(**filters)

    @staticmethod
    def remove_legacy_option(type: Optional[NotificationSettingTypes] = None, **kwargs) -> None:
        from sentry.models import UserOption

        if type:
            kwargs["key"] = get_legacy_key(type)
        else:
            kwargs["key__in"] = KEYS_TO_LEGACY_KEYS.values()

        UserOption.objects.filter(**kwargs).delete()

    def remove_for_user(self, user, type: Optional[NotificationSettingTypes] = None) -> None:
        """ Bulk delete all Notification Settings for a USER, optionally by type. """
        # We don't need a transaction because this is only used in tests.
        self.remove_legacy_option(type, user=user)
        self._filter(targets=[user.actor], type=type).delete()

    def remove_for_team(self, team, type: Optional[NotificationSettingTypes] = None) -> None:
        """ Bulk delete all Notification Settings for a TEAM, optionally by type. """
        self._filter(targets=[team.actor], type=type).delete()

    def remove_for_project(self, project, type: Optional[NotificationSettingTypes] = None) -> None:
        """ Bulk delete all Notification Settings for a PROJECT, optionally by type. """
        self.remove_legacy_option(type, project=project)
        self._filter(
            scope_type=NotificationScopeType.PROJECT,
            scope_identifier=project.id,
            type=type,
        ).delete()

    def remove_for_organization(
        self, organization, type: Optional[NotificationSettingTypes] = None
    ) -> None:
        """ Bulk delete all Notification Settings for a ENTIRE ORGANIZATION, optionally by type. """
        self.remove_legacy_option(type, organization=organization)
        self._filter(
            scope_type=NotificationScopeType.ORGANIZATION,
            scope_identifier=organization.id,
            type=type,
        ).delete()

    def find_settings(
        self,
        provider: ExternalProviders,
        type: NotificationSettingTypes,
        user: Optional = None,
        team: Optional = None,
        project: Optional = None,
        organization: Optional = None,
    ) -> QuerySet:
        """ Wrapper for .filter that translates object parameters to scopes and targets. """
        user_id_option = getattr(user, "id", None)
        scope_type, scope_identifier = get_scope(
            user_id_option, project=project, organization=organization
        )
        target = get_target(user, team)
        return self._filter(provider, type, scope_type, scope_identifier, [target])

    def get_for_user_by_projects(
        self,
        provider: ExternalProviders,
        type: NotificationSettingTypes,
        user,
        parents: List,
    ) -> QuerySet:
        """
        Find all of a user's notification settings for a list of projects or organizations.
        This will include the user's  setting.
        """
        scope_type = get_scope_type(type)
        return self.filter(
            Q(
                scope_type=scope_type.value,
                scope_identifier__in=[parent.id for parent in parents],
            )
            | Q(
                scope_type=NotificationScopeType.USER.value,
                scope_identifier=user.id,
            ),
            provider=provider.value,
            type=type.value,
            target=user.actor,
        )

    def get_for_users_by_parent(
        self,
        provider: ExternalProviders,
        type: NotificationSettingTypes,
        parent,
        users: List,
    ) -> QuerySet:
        """
        Find all of a project/organization's notification settings for a list of users.
        This will include each user's project/organization-independent settings.
        """
        scope_type = get_scope_type(type)
        return self.filter(
            Q(
                scope_type=scope_type.value,
                scope_identifier=parent.id,
            )
            | Q(
                scope_type=NotificationScopeType.USER.value,
                scope_identifier__in=[user.id for user in users],
            ),
            provider=provider.value,
            type=type.value,
            target__in=[user.actor.id for user in users],
        )

    def filter_to_subscribed_users(
        self,
        provider: ExternalProviders,
        project,
        users: List,
    ) -> List:
        """
        Filters a list of users down to the users who are subscribed to email
        alerts. We check both the project level settings and global default settings.
        """
        notification_settings = self.get_for_users_by_parent(
            provider, NotificationSettingTypes.ISSUE_ALERTS, parent=project, users=users
        )
        notification_settings_by_user = transform_to_notification_settings_by_user(
            notification_settings, users
        )
        return [
            user for user in users if should_user_be_notified(notification_settings_by_user, user)
        ]

    def get_notification_recipients(self, provider: ExternalProviders, project) -> List:
        """
        Return a set of users that should receive Issue Alert emails for a given
        project. To start, we get the set of all users. Then we fetch all of
        their relevant notification settings and put them into reference
        dictionary. Finally, we traverse the set of users and return the ones
        that should get a notification.
        """
        from sentry.models import User

        user_ids = project.member_set.values_list("user", flat=True)
        users = User.objects.filter(id__in=user_ids)
        return self.filter_to_subscribed_users(provider, project, users)
