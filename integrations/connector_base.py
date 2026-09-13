"""Base class every platform connector implements."""


class BaseConnector:
    #: Platform key, must match Connection.platform (e.g. 'shopify').
    platform = None

    #: Extra config defaults merged over Connection.DEFAULT_CONFIG.
    config_defaults = {}

    #: Seconds between reconciliation polls for this platform.
    poll_interval = 3600

    def __init__(self, connection):
        self.connection = connection
        self.config = connection.get_config()

    # ---- inbound -----------------------------------------------------------

    def parse_order_event(self, inbox_row):
        """Translate an inbox row into an ExternalOrder, or None if the event
        is not order-related / should be skipped."""
        raise NotImplementedError

    def handle_event(self, inbox_row):
        """Handle non-order events (product updates, uninstall, ...).
        Return True if the event was handled here."""
        return False

    def fetch_variants(self):
        """Yield ExternalVariant for the full catalog (product sync)."""
        raise NotImplementedError

    def count_variants(self):
        """Total variant count for sync progress reporting, or None if the
        platform can't provide one cheaply."""
        return None

    def poll(self):
        """Reconciliation: fetch recent orders from the platform and insert
        any missing events into the inbox. Also the only intake path for
        platforms without webhooks."""
        raise NotImplementedError

    def needs_immediate_poll(self):
        """True when the connection has never been polled (fresh install or
        just re-linked), so the worker polls now instead of waiting out
        poll_interval."""
        return False

    # ---- outbound ----------------------------------------------------------

    def execute(self, outbox_row):
        """Execute an outbound intent (fulfill_order / archive_order /
        push_inventory). Raise to trigger retry with backoff."""
        raise NotImplementedError

    # ---- auth --------------------------------------------------------------

    def refresh_auth(self):
        """Refresh expiring credentials if needed. Called periodically."""
        return None
