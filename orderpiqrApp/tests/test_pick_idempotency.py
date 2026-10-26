"""Replay safety for the four picking POSTs.

A picker works in a cooled warehouse with bad reception, so the client queues
its picks and retries them. Every retry is a byte-identical POST arriving a
second or an hour later, and the server must apply it exactly once.

The invariant under test throughout: on a replay the response still says "ok"
(a retry is not an error the picker should ever see) and the number of rows
marked successful does not move.
"""
import json

from orderpiqrApp.models import (
    CustomerSettingValue, InventoryLog, Order, OrderLine, PickList, ProductPick,
    SettingDefinition,
)
from orderpiqrApp.tests.test_scan_endpoints import FINGERPRINT, ScanEndpointTestCase


class PickIdempotencyTestCase(ScanEndpointTestCase):
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

    def bulk_pick(self, quantity, product_code='SMOOTHIE-1', order_id='ORD-1', **overrides):
        payload = {
            'orderID': order_id,
            'productCode': product_code,
            'deviceFingerprint': FINGERPRINT,
            'quantity': quantity,
            'timeTakenMs': 500,
        }
        payload.update(overrides)
        return self.client.post('/orderpiqr/bulk-product-pick', data=json.dumps(payload),
                                content_type='application/json')

    def picked_count(self, order_id='ORD-1'):
        picklist = PickList.objects.get(picklist_code=order_id, customer=self.customer)
        return ProductPick.objects.filter(picklist=picklist, outcome='picked').count()


class ProductPickReplayTests(PickIdempotencyTestCase):
    def test_replayed_pick_id_does_not_mark_a_second_row(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])

        first = self.pick(pickId='pick-abc')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.picked_count(), 1)

        second = self.pick(pickId='pick-abc')

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['status'], 'ok')
        self.assertTrue(second.json()['duplicate'])
        # The second unit is still waiting to be picked.
        self.assertEqual(self.picked_count(), 1)

    def test_replay_answers_with_the_row_it_originally_marked(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        first = self.pick(pickId='pick-abc').json()

        second = self.pick(pickId='pick-abc').json()

        self.assertEqual(second['picklist_code'], 'ORD-1')
        self.assertEqual(second['product_code'], 'SMOOTHIE-1')
        self.assertEqual(second['updated_productpick_id'], first['updated_productpick_id'])
        self.assertEqual(second['remaining_for_product'], 1)

    def test_a_first_pick_is_not_flagged_as_duplicate(self):
        self.scan(['SMOOTHIE-1'])
        self.assertNotIn('duplicate', self.pick(pickId='pick-abc').json())

    def test_pick_id_is_stored_on_the_marked_row(self):
        self.scan(['SMOOTHIE-1'])
        self.pick(pickId='pick-abc')

        pp = ProductPick.objects.get(outcome='picked')
        self.assertEqual(pp.client_pick_id, 'pick-abc')

    def test_distinct_pick_ids_mark_distinct_rows(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])

        self.pick(pickId='pick-1')
        self.pick(pickId='pick-2')

        self.assertEqual(self.picked_count(), 2)

    def test_without_a_pick_id_two_picks_still_mark_two_rows(self):
        # Replay protection is keyed on the client's id, never on the product:
        # a picker genuinely scanning the same product twice must get two rows.
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])

        self.pick()
        self.pick()

        self.assertEqual(self.picked_count(), 2)

    def test_empty_pick_id_is_not_treated_as_a_duplicate(self):
        # Rows carry '' by default, so a blank id must never match them.
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])

        self.pick(pickId='')
        self.pick(pickId='   ')

        self.assertEqual(self.picked_count(), 2)

    def test_overlong_pick_id_is_truncated_and_still_deduped(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        long_id = 'x' * 200

        self.pick(pickId=long_id)
        second = self.pick(pickId=long_id)

        self.assertTrue(second.json()['duplicate'])
        self.assertEqual(self.picked_count(), 1)
        self.assertEqual(ProductPick.objects.get(outcome='picked').client_pick_id, 'x' * 64)

    def test_pick_id_from_another_picklist_does_not_collide(self):
        self.scan(['SMOOTHIE-1'], order_id='ORD-1')
        self.scan(['SALAD-1'], order_id='ORD-2')

        self.pick(pickId='pick-abc', order_id='ORD-1')
        response = self.pick('SALAD-1', pickId='pick-abc', order_id='ORD-2')

        self.assertNotIn('duplicate', response.json())
        self.assertEqual(self.picked_count('ORD-2'), 1)

    def test_replay_on_a_lost_picklist_still_stops_the_line(self):
        # The duplicate check must not paper over a missing picklist: that 404
        # and its error_code are what stop the picker scanning into the void.
        response = self.pick(pickId='pick-abc', order_id='ORD-NEVER-SCANNED')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error_code'], 'picklist_not_found')


class ProductPickTimeTakenTests(PickIdempotencyTestCase):
    def test_null_time_taken_ms_is_accepted(self):
        # Regression: int(None) raised, so a queued pick replayed after a
        # reload — which has no stopwatch to report — was lost with a 500.
        self.scan(['SMOOTHIE-1'])

        response = self.pick(timeTakenMs=None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.picked_count(), 1)
        self.assertIsNone(ProductPick.objects.get(outcome='picked').time_taken)

    def test_missing_time_taken_ms_is_accepted(self):
        self.scan(['SMOOTHIE-1'])

        response = self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': 'ORD-1', 'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.picked_count(), 1)

    def test_unparseable_time_taken_ms_is_accepted(self):
        self.scan(['SMOOTHIE-1'])

        response = self.pick(timeTakenMs='not-a-number')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(ProductPick.objects.get(outcome='picked').time_taken)


class BulkProductPickReplayTests(PickIdempotencyTestCase):
    def test_replayed_bulk_does_not_mark_more_rows(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SMOOTHIE-1'])

        first = self.bulk_pick(3, pickId='bulk-abc')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.picked_count(), 3)

        second = self.bulk_pick(3, pickId='bulk-abc')

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['status'], 'ok')
        self.assertTrue(second.json()['duplicate'])
        self.assertEqual(second.json()['updated_count'], 3)
        self.assertEqual(self.picked_count(), 3)

    def test_pick_id_is_stored_on_every_row_the_bulk_marked(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SMOOTHIE-1'])
        self.bulk_pick(2, pickId='bulk-abc')

        self.assertEqual(
            ProductPick.objects.filter(client_pick_id='bulk-abc').count(), 2)

    def test_replayed_partial_bulk_is_ok_not_a_shortfall_error(self):
        # The trap this guards: after the first bulk the rows it marked are no
        # longer unpicked, so the availability check would reject the retry with
        # a 400 "only N unpicked rows available" — an error for work that is
        # already recorded.
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SMOOTHIE-1'])
        self.bulk_pick(3, pickId='bulk-abc')

        second = self.bulk_pick(3, pickId='bulk-abc')

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['remaining_for_product'], 0)

    def test_distinct_bulk_ids_mark_distinct_rows(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SMOOTHIE-1', 'SMOOTHIE-1'])

        self.bulk_pick(2, pickId='bulk-1')
        self.bulk_pick(2, pickId='bulk-2')

        self.assertEqual(self.picked_count(), 4)

    def test_bulk_replay_of_a_single_pick_id_is_recognised(self):
        # The two endpoints share one id space: whichever one landed first, the
        # retry must not mark a second row.
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        self.pick(pickId='shared-id')

        response = self.bulk_pick(1, pickId='shared-id')

        self.assertTrue(response.json()['duplicate'])
        self.assertEqual(self.picked_count(), 1)

    def test_bulk_replay_on_a_lost_picklist_still_stops_the_line(self):
        response = self.bulk_pick(1, pickId='bulk-abc', order_id='ORD-NEVER-SCANNED')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error_code'], 'picklist_not_found')


class ClaimReplayTests(PickIdempotencyTestCase):
    """A claim is the head of the retry queue, so it is replayed most often."""

    def test_replayed_claim_by_the_same_device_is_ok(self):
        self.scan(['SMOOTHIE-1', 'SALAD-1'])

        response = self.scan(['SMOOTHIE-1', 'SALAD-1'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertEqual(response.json()['already_picked'], {})
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        self.assertEqual(ProductPick.objects.filter(picklist=picklist).count(), 2)

    def test_replayed_claim_reports_picks_already_recorded(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])
        self.pick(pickId='pick-abc')

        response = self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['already_picked'], {'SMOOTHIE-1': 1})
        self.assertEqual(self.picked_count(), 1)

    def test_replayed_claim_keeps_the_order_in_progress(self):
        order = Order.objects.create(
            customer=self.customer, order_code='ORD-1', status='queued', queue_position=1)
        OrderLine.objects.create(order=order, product=self.smoothie, quantity=1)

        self.scan(['SMOOTHIE-1'])
        response = self.scan(['SMOOTHIE-1'])

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'in_progress')

    def test_pick_survives_a_claim_replay_that_lands_after_it(self):
        # Strict FIFO should prevent it, but if a duplicate claim ever arrives
        # behind a pick, the recorded pick must still be there afterwards.
        self.scan(['SMOOTHIE-1', 'SALAD-1'])
        self.pick(pickId='pick-abc')

        self.scan(['SMOOTHIE-1', 'SALAD-1'])

        self.assertEqual(self.picked_count(), 1)
        self.assertTrue(
            ProductPick.objects.filter(client_pick_id='pick-abc', outcome='picked').exists())


class CompletePicklistReplayTests(PickIdempotencyTestCase):
    def _enable_inventory(self):
        definition = SettingDefinition.objects.get(key='inventory_management_enabled')
        CustomerSettingValue.objects.update_or_create(
            customer=self.customer, definition=definition, defaults={'value': 'true'})

    def _ordered_list(self):
        order = Order.objects.create(
            customer=self.customer, order_code='ORD-1', status='queued', queue_position=1)
        OrderLine.objects.create(order=order, product=self.smoothie, quantity=1)
        self.scan(['SMOOTHIE-1'])
        self.pick(pickId='pick-abc')
        return order

    def test_recompleting_is_ok_not_an_error(self):
        self.scan(['SMOOTHIE-1'])
        self.complete()

        response = self.complete()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertTrue(response.json()['duplicate'])

    def test_recompleting_does_not_restretch_time_taken(self):
        # The old code recomputed "now minus pick_time" on every call, so a
        # completion replayed an hour later reported an hour-long pick.
        self.scan(['SMOOTHIE-1'])
        self.complete()
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        PickList.objects.filter(pk=picklist.pk).update(time_taken=None)

        self.complete()

        picklist.refresh_from_db()
        self.assertIsNone(picklist.time_taken)

    def test_recompleting_does_not_decrement_inventory_twice(self):
        self._enable_inventory()
        self.smoothie.inventory_quantity = 10
        self.smoothie.save(update_fields=['inventory_quantity'])
        self._ordered_list()

        self.complete()
        self.complete()

        self.smoothie.refresh_from_db()
        self.assertEqual(self.smoothie.inventory_quantity, 9)
        self.assertEqual(
            InventoryLog.objects.filter(reason=InventoryLog.Reason.ORDER_PICKED).count(), 1)

    def test_recompleting_leaves_the_order_completed_at_alone(self):
        order = self._ordered_list()
        self.complete()
        order.refresh_from_db()
        first_completed_at = order.completed_at

        self.complete()

        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')
        self.assertEqual(order.completed_at, first_completed_at)

    def test_completing_a_list_still_marks_it_successful(self):
        # The duplicate short-circuit must not swallow the real completion.
        self.scan(['SMOOTHIE-1'])

        response = self.complete()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('duplicate', response.json())
        picklist = PickList.objects.get(picklist_code='ORD-1', customer=self.customer)
        self.assertTrue(picklist.successful)


class ManualOverrideReplayTests(PickIdempotencyTestCase):
    """A replayed override op must not count the same unscannable line twice.

    The manual_override scan event feeds the health page's unscannable-products
    metric; before the dedupe-aware ordering, every reception-drop retry of an
    override pick logged a fresh event.
    """

    def override_events(self):
        from orderpiqrApp.models import ScanEvent
        return ScanEvent.objects.filter(event_type='manual_override').count()

    def test_replayed_override_pick_logs_one_event(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1'])

        self.pick(pickId='pick-abc', manualOverride=True)
        self.pick(pickId='pick-abc', manualOverride=True)

        self.assertEqual(self.override_events(), 1)
        self.assertEqual(self.picked_count(), 1)

    def test_replayed_override_bulk_logs_one_event(self):
        self.scan(['SMOOTHIE-1', 'SMOOTHIE-1', 'SMOOTHIE-1'])

        self.bulk_pick(2, pickId='bulk-abc', manualOverride=True)
        self.bulk_pick(2, pickId='bulk-abc', manualOverride=True)

        self.assertEqual(self.override_events(), 1)
        self.assertEqual(self.picked_count(), 2)

    def test_override_on_a_lost_picklist_still_logs(self):
        # The 404 path must keep the override signal (the two-lost-weeks bug):
        # moving the log behind the duplicate check must not lose this case.
        response = self.pick(order_id='NO-SUCH-LIST', pickId='pick-abc', manualOverride=True)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.override_events(), 1)

    def test_override_bulk_on_a_lost_picklist_still_logs(self):
        response = self.bulk_pick(2, order_id='NO-SUCH-LIST', pickId='bulk-abc', manualOverride=True)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.override_events(), 1)
