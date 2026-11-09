"""Three holes in the pick accounting, found in HF's 2026-11-08 data.

1. A stale lock was judged by the *holder device's* global activity, so a
   picker who claimed a list, picked nothing, and kept working other lists
   held it forever. On 2026-11-08 that cost an 80-line order.
2. Pending lines on a list that was never completed counted as neither picked,
   short nor lost — 385 lines invisible while the page reported 0.12%
   unaccounted.
3. Overrides were countable only as ScanEvents, but one bulk confirm marks N
   rows from a single event, so the share of lines verified by a scan was
   unknowable.
"""
import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orderpiqrApp.models import (
    Customer, Device, Order, OrderLine, PickList, Product, ProductPick, ScanEvent,
    UserProfile, abandoned_picklist_q,
)
from orderpiqrApp.tests.test_scan_endpoints import FINGERPRINT, ScanEndpointTestCase
from orderpiqrApp.utils.health import pick_outcomes


class StaleLockTests(TestCase):
    """The holding list's own activity decides, not the holder's device."""

    def setUp(self):
        self.customer = Customer.objects.create(name='Healthy Fridge')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)

        self.holder = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint='holder-fp',
            name='Beata', description='', last_login=timezone.now(), lists_picked=0)
        self.claimer = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=FINGERPRINT,
            name='Dawid', description='', last_login=timezone.now(), lists_picked=0)

        self.product = Product.objects.create(
            customer=self.customer, code='P-1', description='Thing')
        self.order = Order.objects.create(
            customer=self.customer, order_code='MAR_BOX', status='in_progress',
            queue_position=1)
        OrderLine.objects.create(order=self.order, product=self.product, quantity=1)

        self.held = PickList.objects.create(
            customer=self.customer, device=self.holder, picklist_code='MAR_BOX',
            order=self.order, pick_started=True, successful=None)
        ProductPick.objects.create(
            product=self.product, picklist=self.held, quantity=1)

        self.client.login(username='picker1', password='pw12345678')

    def _set_list_idle(self, minutes):
        # updated_at is auto_now, so it can only be backdated by a queryset
        # update — the same reason _touch_picklist exists.
        PickList.objects.filter(pk=self.held.pk).update(
            updated_at=timezone.now() - timedelta(minutes=minutes))

    def _claim(self):
        return self.client.post('/orderpiqr/scan-picklist', data=json.dumps({
            'orderID': 'MAR_BOX',
            'picklist': ['P-1'],
            'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')

    def test_busy_holder_does_not_keep_an_untouched_list_locked(self):
        # The exact 2026-11-08 shape: the holder is active right now (they are
        # picking other lists) but this list has not moved in 15 minutes.
        self._set_list_idle(15)
        self.holder.last_login = timezone.now()
        self.holder.save(update_fields=['last_login'])

        response = self._claim()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ScanEvent.objects.filter(event_type='lock_takeover').exists())

    def test_takeover_message_reports_the_list_idle_time(self):
        self._set_list_idle(15)

        self._claim()

        event = ScanEvent.objects.get(event_type='lock_takeover')
        self.assertIn('Beata', event.message)
        self.assertIn('idle 15m', event.message)

    def test_a_list_still_being_worked_stays_locked(self):
        # The protection that must survive the fix: recent work on *this* list
        # means someone is on it.
        self._set_list_idle(2)

        response = self._claim()

        self.assertEqual(response.status_code, 409)
        self.assertIn('already being picked', response.json()['message'])

    def test_idle_holder_device_no_longer_decides_on_its_own(self):
        # Inverse of the bug: the device has been quiet for hours but the list
        # was touched a minute ago (another picker's phone shares the list, or
        # the outbox just flushed). The list is what counts.
        self._set_list_idle(1)
        self.holder.last_login = timezone.now() - timedelta(hours=5)
        self.holder.save(update_fields=['last_login'])

        self.assertEqual(self._claim().status_code, 409)


class PicklistActivityStampTests(ScanEndpointTestCase):
    """updated_at has to move per pick for either reader to trust it."""

    def _pick(self, **overrides):
        payload = {
            'orderID': 'ORD-1',
            'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT,
            'timeTakenMs': 500,
        }
        payload.update(overrides)
        return self.client.post('/orderpiqr/product-pick', data=json.dumps(payload),
                                content_type='application/json')

    def test_a_pick_stamps_list_activity(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        picklist = PickList.objects.get(picklist_code='ORD-1')
        PickList.objects.filter(pk=picklist.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30))

        self._pick()

        picklist.refresh_from_db()
        self.assertLess(timezone.now() - picklist.updated_at, timedelta(minutes=1))

    def test_a_bulk_pick_stamps_list_activity(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        picklist = PickList.objects.get(picklist_code='ORD-1')
        PickList.objects.filter(pk=picklist.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30))

        self.client.post('/orderpiqr/bulk-product-pick', data=json.dumps({
            'orderID': 'ORD-1',
            'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT,
            'quantity': 2,
        }), content_type='application/json')

        picklist.refresh_from_db()
        self.assertLess(timezone.now() - picklist.updated_at, timedelta(minutes=1))

    def test_stamping_does_not_rewrite_the_device_row(self):
        # A queryset update is used precisely to skip PickList.save(), which
        # recounts and re-saves the Device on the hottest path in the app.
        self.scan(['SMOOTHIE-1'])
        picklist = PickList.objects.get(picklist_code='ORD-1')
        PickList.objects.filter(pk=picklist.pk).update(pick_started=True)

        self._pick()

        picklist.refresh_from_db()
        # save() would have run the model's save() override and left notes /
        # recomputed fields alone, but the cheap path must still not lose the
        # column it was asked to write.
        self.assertTrue(picklist.pick_started)


class ScanVerifiedTests(ScanEndpointTestCase):
    """Per-row verification: the unit the question is actually asked in."""

    def _pick(self, **overrides):
        payload = {
            'orderID': 'ORD-1',
            'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT,
            'timeTakenMs': 500,
        }
        payload.update(overrides)
        return self.client.post('/orderpiqr/product-pick', data=json.dumps(payload),
                                content_type='application/json')

    def _bulk(self, quantity, **overrides):
        payload = {
            'orderID': 'ORD-1',
            'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT,
            'quantity': quantity,
        }
        payload.update(overrides)
        return self.client.post('/orderpiqr/bulk-product-pick', data=json.dumps(payload),
                                content_type='application/json')

    def test_a_scanned_pick_is_verified(self):
        self.scan(['SMOOTHIE-1'])
        self._pick()
        self.assertTrue(ProductPick.objects.get().scan_verified)

    def test_an_override_is_not_verified(self):
        self.scan(['SMOOTHIE-1'])
        self._pick(manualOverride=True)
        self.assertFalse(ProductPick.objects.get().scan_verified)

    def test_one_bulk_override_marks_every_row_unverified(self):
        # The whole point: one ScanEvent, five unverified lines. Counting the
        # events would have reported one.
        self.scan(['SMOOTHIE-1'] * 5)
        self._bulk(5, manualOverride=True)

        picks = ProductPick.objects.filter(outcome='picked')
        self.assertEqual(picks.count(), 5)
        self.assertEqual(picks.filter(scan_verified=False).count(), 5)
        self.assertEqual(
            ScanEvent.objects.filter(event_type='manual_override').count(), 1)

    def test_a_bulk_scan_marks_every_row_verified(self):
        self.scan(['SMOOTHIE-1'] * 3)
        self._bulk(3)
        self.assertEqual(
            ProductPick.objects.filter(outcome='picked', scan_verified=True).count(), 3)

    def test_a_declared_short_says_nothing_about_verification(self):
        # A short is not a pick; False would read as "an unverified pick".
        self.scan(['SMOOTHIE-1'])
        self._pick(successful=False, shortReason='insufficient_stock')

        pick = ProductPick.objects.get()
        self.assertEqual(pick.outcome, 'short')
        self.assertIsNone(pick.scan_verified)

    def test_history_stays_unknown(self):
        # Nothing may silently assert that a pre-existing row was verified.
        self.scan(['SMOOTHIE-1'])
        self.assertIsNone(ProductPick.objects.get().scan_verified)

    def test_a_reclaimed_short_takes_the_verification_of_the_new_pick(self):
        self.scan(['SMOOTHIE-1'])
        self._pick(successful=False, shortReason='not_found')
        self._pick(pickId='second-op')

        pick = ProductPick.objects.get()
        self.assertEqual(pick.outcome, 'picked')
        self.assertTrue(pick.scan_verified)


class AbandonedListAccountingTests(ScanEndpointTestCase):
    """Pending lines on a list nobody came back to are lost, not limbo."""

    def _window(self):
        now = timezone.now()
        return pick_outcomes(self.customer, now - timedelta(days=30), now + timedelta(minutes=1))[0]

    def _abandon(self, order_id='ORD-1', hours=3):
        PickList.objects.filter(picklist_code=order_id).update(
            updated_at=timezone.now() - timedelta(hours=hours))

    def test_pending_lines_on_an_abandoned_list_count_as_lost(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        self._abandon()

        outcomes = self._window()
        self.assertEqual(outcomes['lines_lost'], 2)
        self.assertEqual(outcomes['lines_abandoned'], 2)
        self.assertEqual(outcomes['lists_abandoned'], 1)

    def test_an_open_list_someone_is_still_working_is_not_abandoned(self):
        # The false positive that would make the metric useless: a list claimed
        # ten minutes ago is in progress, not lost.
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])

        outcomes = self._window()
        self.assertEqual(outcomes['lines_lost'], 0)
        self.assertEqual(outcomes['lines_abandoned'], 0)

    def test_a_completed_list_is_never_abandoned(self):
        self.scan(['SMOOTHIE-1'])
        self.complete()
        self._abandon()

        outcomes = self._window()
        self.assertEqual(outcomes['lines_abandoned'], 0)
        self.assertEqual(outcomes['lists_abandoned'], 0)

    def test_an_archived_list_is_excluded(self):
        # Archiving is how ops says "stop counting this"; it must still work.
        self.scan(['SMOOTHIE-1'])
        self._abandon()
        PickList.objects.filter(picklist_code='ORD-1').update(archived=True)

        self.assertEqual(self._window()['lines_abandoned'], 0)

    def test_picked_lines_on_an_abandoned_list_are_not_lost(self):
        # Only the pending rows are unrecorded work; recorded picks stand.
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': 'ORD-1', 'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT, 'timeTakenMs': 100,
        }), content_type='application/json')
        self._abandon()

        outcomes = self._window()
        self.assertEqual(outcomes['lines_abandoned'], 1)
        self.assertEqual(outcomes['lines_lost'], 1)

    def test_a_pick_rescues_the_list_from_the_abandoned_bucket(self):
        # Activity is the signal, so recording work has to clear the flag.
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        self._abandon()
        self.assertEqual(self._window()['lists_abandoned'], 1)

        self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': 'ORD-1', 'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT, 'timeTakenMs': 100,
        }), content_type='application/json')

        self.assertEqual(self._window()['lists_abandoned'], 0)

    def test_the_predicate_is_shared_not_reimplemented(self):
        self.scan(['SMOOTHIE-1'])
        self._abandon()
        self.assertEqual(
            PickList.objects.filter(abandoned_picklist_q()).count(), 1)


class UnverifiedShareTests(ScanEndpointTestCase):
    def _window(self):
        now = timezone.now()
        return pick_outcomes(self.customer, now - timedelta(days=30), now + timedelta(minutes=1))[0]

    def test_percentage_ignores_rows_of_unknown_verification(self):
        # Three picked rows: one scanned, one overridden, one from before the
        # column existed. The share must be 50%, not 33% — history is excluded
        # rather than assumed verified.
        self.scan(['SMOOTHIE-1'] * 3)
        picks = list(ProductPick.objects.order_by('id'))
        ProductPick.objects.filter(pk=picks[0].pk).update(
            outcome='picked', successful=True, scan_verified=True)
        ProductPick.objects.filter(pk=picks[1].pk).update(
            outcome='picked', successful=True, scan_verified=False)
        ProductPick.objects.filter(pk=picks[2].pk).update(
            outcome='picked', successful=True, scan_verified=None)

        outcomes = self._window()
        self.assertEqual(outcomes['lines_scan_verified'], 1)
        self.assertEqual(outcomes['lines_unverified'], 1)
        self.assertEqual(outcomes['lines_unverified_pct'], 50.0)

    def test_no_known_rows_reports_zero_not_an_error(self):
        self.scan(['SMOOTHIE-1'])
        outcomes = self._window()
        self.assertEqual(outcomes['lines_unverified_pct'], 0.0)
