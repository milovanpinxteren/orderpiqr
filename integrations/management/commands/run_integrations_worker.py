"""Integrations worker: processes the webhook inbox, executes the sync
outbox with retry/backoff, and runs per-connection reconciliation polls.

Run on a Heroku worker dyno:  python manage.py run_integrations_worker
One-shot (cron / tests):      python manage.py run_integrations_worker --once
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from integrations.models import Connection, SyncOutbox, WebhookInbox
from integrations.services import intake

logger = logging.getLogger(__name__)

INBOX_BATCH = 20
OUTBOX_BATCH = 20
# needs_mapping rows are retried on this cadence (mapping may have been fixed)
NEEDS_MAPPING_RETRY = timedelta(minutes=10)
MAX_BACKOFF_MINUTES = 360


class Command(BaseCommand):
    help = 'Run the integrations background worker loop.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true',
                            help='Run a single pass and exit.')
        parser.add_argument('--sleep', type=float, default=5.0,
                            help='Idle sleep between passes in seconds.')

    def handle(self, *args, **options):
        self._last_poll = {}
        logger.info("Integrations worker started")
        while True:
            try:
                did_work = self.run_pass()
            except Exception:
                logger.exception("Worker pass crashed")
                did_work = False
            if options['once']:
                break
            if not did_work:
                time.sleep(options['sleep'])

    def run_pass(self):
        processed = self.process_inbox()
        executed = self.process_outbox()
        self.run_due_polls()
        return bool(processed or executed)

    # ---- inbox -------------------------------------------------------------

    def claim_inbox_rows(self):
        now = timezone.now()
        with transaction.atomic():
            rows = list(
                WebhookInbox.objects
                .select_for_update(skip_locked=True)
                .filter(status='pending')
                .order_by('received_at')[:INBOX_BATCH]
            )
            if len(rows) < INBOX_BATCH:
                rows += list(
                    WebhookInbox.objects
                    .select_for_update(skip_locked=True)
                    .filter(status='needs_mapping',
                            processed_at__lt=now - NEEDS_MAPPING_RETRY)
                    .order_by('processed_at')[:INBOX_BATCH - len(rows)]
                )
            for row in rows:
                row.status = 'processing'
                row.save(update_fields=['status'])
        return rows

    def process_inbox(self):
        rows = self.claim_inbox_rows()
        for row in rows:
            self.process_inbox_row(row)
        return len(rows)

    def process_inbox_row(self, row):
        row.attempts += 1
        try:
            connector = row.connection.get_connector()

            if connector.handle_event(row):
                row.status = 'processed'
            else:
                ext_order = connector.parse_order_event(row)
                if ext_order is None:
                    row.status = 'skipped'
                elif ext_order.status in ('cancelled', 'fulfilled_elsewhere'):
                    intake.cancel_external_order(
                        row.connection, ext_order.external_order_id,
                        reason=ext_order.status,
                    )
                    row.status = 'processed'
                else:
                    intake.import_external_order(row.connection, ext_order)
                    row.status = 'processed'
            row.error = ''
        except intake.UnresolvedLinesError as exc:
            row.status = 'needs_mapping'
            row.error = str(exc)
        except Exception as exc:
            logger.exception("Inbox row %s failed", row.pk)
            row.status = 'failed' if row.attempts >= 5 else 'pending'
            row.error = str(exc)[:2000]
        if row.connection.pk is None:
            # Handler deleted the connection (shop/redact); this row was
            # cascade-deleted with it, so there is nothing left to save.
            return
        row.processed_at = timezone.now()
        row.save(update_fields=['status', 'attempts', 'error', 'processed_at'])

    # ---- outbox ------------------------------------------------------------

    def claim_outbox_rows(self):
        now = timezone.now()
        with transaction.atomic():
            rows = list(
                SyncOutbox.objects
                .select_for_update(skip_locked=True)
                .filter(status='pending', next_attempt_at__lte=now)
                .order_by('next_attempt_at')[:OUTBOX_BATCH]
            )
            for row in rows:
                row.status = 'processing'
                row.save(update_fields=['status'])
        return rows

    def process_outbox(self):
        rows = self.claim_outbox_rows()
        for row in rows:
            row.attempts += 1
            try:
                connector = row.connection.get_connector()
                connector.execute(row)
                row.status = 'done'
                row.error = ''
            except Exception as exc:
                logger.exception("Outbox row %s (%s) failed", row.pk, row.action)
                row.error = str(exc)[:2000]
                if row.attempts >= row.max_attempts:
                    row.status = 'failed'
                else:
                    row.status = 'pending'
                    backoff = min(2 ** row.attempts, MAX_BACKOFF_MINUTES)
                    row.next_attempt_at = timezone.now() + timedelta(minutes=backoff)
            row.save(update_fields=['status', 'attempts', 'error', 'next_attempt_at', 'updated_at'])
        return len(rows)

    # ---- polls -------------------------------------------------------------

    def run_due_polls(self):
        now = time.monotonic()
        for connection in Connection.objects.filter(status='active'):
            try:
                connector = connection.get_connector()
            except LookupError:
                continue
            last = self._last_poll.get(connection.pk)
            if last is not None and now - last < connector.poll_interval:
                continue
            self._last_poll[connection.pk] = now
            try:
                connector.refresh_auth()
                connector.poll()
            except Exception:
                logger.exception("Poll failed for connection %s", connection.pk)
