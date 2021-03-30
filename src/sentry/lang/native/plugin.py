from sentry.lang.native.processing import (
    process_applecrashreport,
    process_minidump,
    process_payload,
    MINIDUMP_ATTACHMENT_TYPE,
    APPLECRASHREPORT_ATTACHMENT_TYPE,
)
from sentry.lang.native.utils import is_native_event, is_minidump_event, is_applecrashreport_event
from sentry.plugins.base.v2 import Plugin2


class NativePlugin(Plugin2):
    can_disable = False

    def get_event_enhancers(self, data):
        if is_minidump_event(data):
            return [process_minidump]
        elif is_applecrashreport_event(data):
            return [process_applecrashreport]
        elif is_native_event(data):
            return [process_payload]

    def get_required_attachment_types(self, data):
        if is_minidump_event(data):
            return [MINIDUMP_ATTACHMENT_TYPE]
        elif is_applecrashreport_event(data):
            return [APPLECRASHREPORT_ATTACHMENT_TYPE]
        else:
            return []
