"""Pick-flow health logging: the /orderpiqr/scan-event endpoint and the
server-side ScanEvent capture inside the scan endpoints.

The invariant mirrored throughout: health logging is fire-and-forget. It never
changes an endpoint's response, and the scan-event endpoint answers 200 'ok'
even when it deliberately stores nothing (dedupe, unresolvable device).
"""
import json

from orderpiqrApp.models import ProductPick, ScanEvent
from orderpiqrApp.tests.test_scan_endpoints import FINGERPRINT, ScanEndpointTestCase


class ScanEventEndpointTests(ScanEndpointTestCase):
    def post_event(self, **overrides):
        payload = {
            'eventType': 'unknown_product',
            'scannedCode': 'NO-SUCH-CODE',
            'picklistCode': 'ORD-1',
            'message': 'Barcode not recognized',
            'deviceFingerprint': FINGERPRINT,
        }
        payload.update(overrides)
        return self.client.post('/orderpiqr/scan-event', data=json.dumps(payload),
                                content_type='application/json')

    def test_valid_event_is_stored_with_fields(self):
        response = self.post_event()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        event = ScanEvent.objects.get()
        self.assertEqual(event.customer, self.customer)
        self.assertEqual(event.device, self.device)
        self.assertEqual(event.event_type, 'unknown_product')
        self.assertEqual(event.scanned_code, 'NO-SUCH-CODE')
        self.assertEqual(event.picklist_code, 'ORD-1')
        self.assertEqual(event.message, 'Barcode not recognized')

    def test_invalid_event_type_is_400(self):
        response = self.post_event(eventType='not-a-real-type')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ScanEvent.objects.count(), 0)

    def test_missing_event_type_is_400(self):
        response = self.client.post('/orderpiqr/scan-event', data=json.dumps({
            'scannedCode': 'X', 'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_malformed_json_is_400(self):
        response = self.client.post('/orderpiqr/scan-event', data='{not json',
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_identical_event_within_window_is_deduped(self):
        first = self.post_event()
        second = self.post_event()

        # Both answer ok — the client must not care — but only one row lands.
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(ScanEvent.objects.count(), 1)

    def test_different_scanned_code_is_not_deduped(self):
        self.post_event()
        self.post_event(scannedCode='OTHER-CODE')
        self.assertEqual(ScanEvent.objects.count(), 2)

    def test_unauthenticated_unknown_fingerprint_stores_nothing(self):
        self.client.logout()
        response = self.post_event(deviceFingerprint='ghost-fp-never-registered')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertEqual(ScanEvent.objects.count(), 0)

    def test_unauthenticated_known_fingerprint_resolves_device(self):
        self.client.logout()
        response = self.post_event()

        self.assertEqual(response.status_code, 200)
        event = ScanEvent.objects.get()
        self.assertEqual(event.device, self.device)
        self.assertEqual(event.customer, self.customer)

    def test_authenticated_without_device_logs_with_customer(self):
        response = self.post_event(deviceFingerprint='fingerprint-nobody-registered')

        self.assertEqual(response.status_code, 200)
        event = ScanEvent.objects.get()
        self.assertIsNone(event.device)
        self.assertEqual(event.customer, self.customer)

    def test_long_codes_and_message_are_truncated(self):
        self.post_event(scannedCode='X' * 600, picklistCode='Y' * 600, message='Z' * 5000)
        event = ScanEvent.objects.get()
        self.assertEqual(len(event.scanned_code), 255)
        self.assertEqual(len(event.picklist_code), 255)
        self.assertEqual(len(event.message), 2000)


class ScanPicklistCaptureTests(ScanEndpointTestCase):
    def test_unknown_product_rejection_creates_picklist_rejected_event(self):
        response = self.scan(['SMOOTHIE-1', 'NO-SUCH-CODE'])

        self.assertEqual(response.status_code, 404)
        event = ScanEvent.objects.get(event_type='picklist_rejected')
        self.assertEqual(event.customer, self.customer)
        self.assertEqual(event.device, self.device)
        self.assertEqual(event.scanned_code, 'NO-SUCH-CODE')
        self.assertEqual(event.picklist_code, 'ORD-1')
        self.assertIn('NO-SUCH-CODE', event.message)

    def test_accepted_scan_creates_no_event(self):
        self.scan(['SMOOTHIE-1'])
        self.assertEqual(ScanEvent.objects.count(), 0)


class ProductPickCaptureTests(ScanEndpointTestCase):
    def pick(self, product_code='SMOOTHIE-1', order_id='ORD-1', **overrides):
        payload = {
            'orderID': order_id,
            'productCode': product_code,
            'deviceFingerprint': FINGERPRINT,
            'timeTakenMs': 1200,
        }
        payload.update(overrides)
        return self.client.post('/orderpiqr/product-pick', data=json.dumps(payload),
                                content_type='application/json')

    def test_manual_override_logs_event_and_updates_pick(self):
        self.scan(['SMOOTHIE-1'])
        response = self.pick(manualOverride=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        pp = ProductPick.objects.get(product=self.smoothie)
        self.assertTrue(pp.successful)

        event = ScanEvent.objects.get(event_type='manual_override')
        self.assertEqual(event.scanned_code, 'SMOOTHIE-1')
        self.assertEqual(event.picklist_code, 'ORD-1')
        self.assertEqual(event.device, self.device)

    def test_normal_pick_logs_no_manual_override(self):
        self.scan(['SMOOTHIE-1'])
        response = self.pick()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ScanEvent.objects.filter(event_type='manual_override').exists())
        pp = ProductPick.objects.get(product=self.smoothie)
        self.assertTrue(pp.successful)

    def test_pick_without_picklist_logs_sync_error(self):
        response = self.pick(order_id='ORD-NEVER-SCANNED')

        self.assertEqual(response.status_code, 404)
        event = ScanEvent.objects.get(event_type='sync_error')
        self.assertEqual(event.scanned_code, 'SMOOTHIE-1')
        self.assertEqual(event.picklist_code, 'ORD-NEVER-SCANNED')

    def test_pick_of_unknown_product_logs_sync_error(self):
        self.scan(['SMOOTHIE-1'])
        response = self.pick(product_code='NO-SUCH-CODE')

        self.assertEqual(response.status_code, 404)
        event = ScanEvent.objects.get(event_type='sync_error')
        self.assertEqual(event.scanned_code, 'NO-SUCH-CODE')
        self.assertEqual(event.picklist_code, 'ORD-1')


class CompletePicklistCaptureTests(ScanEndpointTestCase):
    def test_completing_unknown_picklist_logs_sync_error(self):
        response = self.complete('ORD-NEVER-SCANNED')

        self.assertEqual(response.status_code, 404)
        event = ScanEvent.objects.get(event_type='sync_error')
        self.assertEqual(event.picklist_code, 'ORD-NEVER-SCANNED')
        self.assertEqual(event.device, self.device)

    def test_successful_completion_logs_nothing(self):
        self.scan(['SMOOTHIE-1'])
        self.pick_all()
        self.complete()
        self.assertFalse(ScanEvent.objects.filter(event_type='sync_error').exists())

    def pick_all(self):
        self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': 'ORD-1', 'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT, 'timeTakenMs': 500,
        }), content_type='application/json')
