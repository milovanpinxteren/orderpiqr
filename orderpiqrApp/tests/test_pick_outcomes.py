"""The outcome vocabulary on ProductPick (pending/picked/short/lost).

`outcome` is the source of truth and `successful` is derived from it in
save(); a declared short is recorded work that must survive restarts and be
distinguishable from a lost pick (the server never heard anything) — the very
distinction the measurement work exists for.
"""
import json

from django.urls import reverse

from orderpiqrApp.models import (
    CustomerSettingValue, PickList, ProductPick, ScanEvent, SettingDefinition,
    resolve_pending_picks_to_lost,
)
from orderpiqrApp.tests.test_scan_endpoints import FINGERPRINT, ScanEndpointTestCase


class OutcomeTestCase(ScanEndpointTestCase):
    def pick(self, product_code='SMOOTHIE-1', order_id='ORD-1', **overrides):
        payload = {
            'orderID': order_id,
            'productCode': product_code,
            'deviceFingerprint': FINGERPRINT,
            'timeTakenMs': 500,
        }
        payload.update(overrides)
        return self.client.post('/orderpiqr/product-pick', data=json.dumps(payload),
                                content_type='application/json')

    def declare_short(self, quantity=1, reason='not_found', **overrides):
        return self.pick(successful=False, shortReason=reason,
                         quantity=quantity, **overrides)

    def picklist(self, order_id='ORD-1'):
        return PickList.objects.get(picklist_code=order_id, customer=self.customer)


class SaveDerivationTests(OutcomeTestCase):
    def make_pick(self, outcome):
        self.scan(['SMOOTHIE-1'])
        pp = ProductPick.objects.get()
        pp.outcome = outcome
        pp.save()
        pp.refresh_from_db()
        return pp

    def test_pending_derives_none(self):
        self.assertIsNone(self.make_pick('pending').successful)

    def test_picked_derives_true(self):
        self.assertTrue(self.make_pick('picked').successful)

    def test_short_derives_false(self):
        self.assertFalse(self.make_pick('short').successful)

    def test_lost_derives_none(self):
        # Lost is "never heard anything", not a declared failure: deriving
        # False would conflate it with shorts.
        self.assertIsNone(self.make_pick('lost').successful)

    def test_update_fields_with_outcome_also_writes_successful(self):
        self.scan(['SMOOTHIE-1'])
        pp = ProductPick.objects.get()
        pp.outcome = 'picked'
        pp.save(update_fields=['outcome'])
        pp.refresh_from_db()
        self.assertTrue(pp.successful)

    def test_direct_successful_write_is_overruled_by_outcome(self):
        # outcome is the source of truth: a writer that only sets successful
        # cannot desync the two columns.
        self.scan(['SMOOTHIE-1'])
        pp = ProductPick.objects.get()
        pp.successful = True
        pp.save()
        pp.refresh_from_db()
        self.assertIsNone(pp.successful)
        self.assertEqual(pp.outcome, 'pending')

    def test_outcome_from_successful(self):
        self.assertEqual(ProductPick.outcome_from_successful(True), 'picked')
        self.assertEqual(ProductPick.outcome_from_successful(False), 'short')
        self.assertEqual(ProductPick.outcome_from_successful(None), 'pending')


class ResolvePendingToLostTests(OutcomeTestCase):
    def test_only_pending_rows_become_lost(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SMOOTHIE-1'])
        self.pick(pickId='p-1')
        self.declare_short(pickId='p-2')

        resolve_pending_picks_to_lost(self.picklist())

        picks = ProductPick.objects.filter(picklist=self.picklist())
        self.assertEqual(picks.filter(outcome='picked').count(), 1)
        self.assertEqual(picks.filter(outcome='short').count(), 1)
        self.assertEqual(picks.filter(outcome='lost').count(), 1)
        # Queryset update: lost rows keep successful NULL.
        self.assertIsNone(picks.get(outcome='lost').successful)


class ShortDeclarationTests(OutcomeTestCase):
    def test_short_marks_row_with_reason(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])

        response = self.declare_short(pickId='short-1')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['outcome'], 'short')
        self.assertEqual(body['updated_count'], 1)
        # The short row no longer counts as remaining work.
        self.assertEqual(body['remaining_for_product'], 1)
        pp = ProductPick.objects.get(outcome='short')
        self.assertEqual(pp.short_reason, 'not_found')
        self.assertFalse(pp.successful)

    def test_short_logs_a_short_pick_event_with_reason(self):
        self.scan(['SMOOTHIE-1'])
        self.declare_short(reason='damaged', pickId='short-1')

        event = ScanEvent.objects.get(event_type='short_pick')
        self.assertEqual(event.reason, 'damaged')
        self.assertEqual(event.scanned_code, 'SMOOTHIE-1')
        self.assertEqual(event.picklist_code, 'ORD-1')
        self.assertEqual(event.severity, 'info')

    def test_unknown_reason_normalizes_to_other(self):
        self.scan(['SMOOTHIE-1'])
        self.declare_short(reason='gremlins', pickId='short-1')
        self.assertEqual(ProductPick.objects.get(outcome='short').short_reason, 'other')

    def test_reason_text_lands_in_notes_before_the_stamp(self):
        self.scan(['SMOOTHIE-1'])
        self.declare_short(reason='other', reasonText='box crushed', pickId='short-1')

        notes = ProductPick.objects.get(outcome='short').notes
        self.assertIn('box crushed', notes)
        self.assertLess(notes.index('box crushed'), notes.index('device='))

    def test_replayed_short_pick_id_is_a_noop(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        self.declare_short(pickId='short-1')

        second = self.declare_short(pickId='short-1')

        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()['duplicate'])
        self.assertEqual(second.json()['outcome'], 'short')
        self.assertEqual(ProductPick.objects.filter(outcome='short').count(), 1)
        self.assertEqual(ScanEvent.objects.filter(event_type='short_pick').count(), 1)

    def test_quantity_short_marks_that_many_rows_with_one_pick_id(self):
        self.scan(['SMOOTHIE-1'] * 4)

        response = self.declare_short(quantity=3, pickId='short-1')

        self.assertEqual(response.json()['updated_count'], 3)
        self.assertEqual(response.json()['remaining_for_product'], 1)
        shorts = ProductPick.objects.filter(outcome='short')
        self.assertEqual(shorts.count(), 3)
        self.assertEqual({p.client_pick_id for p in shorts}, {'short-1'})

        replay = self.declare_short(quantity=3, pickId='short-1')
        self.assertTrue(replay.json()['duplicate'])
        self.assertEqual(ProductPick.objects.filter(outcome='short').count(), 3)

    def test_quantity_is_capped_at_available_rows(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])

        response = self.declare_short(quantity=5, pickId='short-1')

        self.assertEqual(response.json()['updated_count'], 2)
        self.assertEqual(ProductPick.objects.filter(outcome='short').count(), 2)

    def test_short_with_nothing_available_is_a_noop(self):
        self.scan(['SMOOTHIE-1'])
        self.pick(pickId='p-1')

        response = self.declare_short(pickId='short-1')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'noop')
        self.assertEqual(ProductPick.objects.filter(outcome='short').count(), 0)

    def test_scan_after_short_reclaims_the_row(self):
        # The picker found the item after all: the short flips back to picked
        # and the reason is cleared.
        self.scan(['SMOOTHIE-1'])
        self.declare_short(pickId='short-1')

        response = self.pick(pickId='p-2')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['outcome'], 'picked')
        pp = ProductPick.objects.get()
        self.assertEqual(pp.outcome, 'picked')
        self.assertEqual(pp.short_reason, '')
        self.assertTrue(pp.successful)


class CompletionOutcomeTests(OutcomeTestCase):
    def test_completion_resolves_pending_to_lost(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        self.pick(pickId='p-1')

        self.complete()

        picks = ProductPick.objects.filter(picklist=self.picklist())
        self.assertEqual(picks.filter(outcome='picked').count(), 1)
        self.assertEqual(picks.filter(outcome='lost').count(), 1)
        self.assertEqual(picks.filter(outcome='pending').count(), 0)

    def test_late_pick_after_completion_reclaims_a_lost_row(self):
        # A queued pick flushed after the completion is real work: it reclaims
        # the lost row instead of being dropped as a noop.
        self.scan(['SMOOTHIE-1'])
        self.complete()
        self.assertEqual(ProductPick.objects.filter(outcome='lost').count(), 1)

        response = self.pick(pickId='late-1')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['outcome'], 'picked')
        self.assertEqual(ProductPick.objects.filter(outcome='lost').count(), 0)
        self.assertEqual(ProductPick.objects.filter(outcome='picked').count(), 1)


class ProductPickMethodTests(OutcomeTestCase):
    def test_get_is_rejected(self):
        self.assertEqual(self.client.get('/orderpiqr/product-pick').status_code, 405)


class ShortPickSettingTests(ScanEndpointTestCase):
    """The scan page branches on short_pick_enabled, so the flag has to reach
    the client settings blob — off by default (pattern: picklist search)."""

    def setUp(self):
        super().setUp()
        session = self.client.session
        session['device_fingerprint'] = FINGERPRINT
        session.save()

    def scan_page(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_setting_defaults_to_false_in_the_settings_blob(self):
        self.assertIn('"short_pick_enabled": false', self.scan_page())

    def test_enabled_setting_reaches_the_settings_blob(self):
        CustomerSettingValue.objects.update_or_create(
            customer=self.customer,
            definition=SettingDefinition.objects.get(key='short_pick_enabled'),
            defaults={'value': 'true'})
        self.assertIn('"short_pick_enabled": true', self.scan_page())
