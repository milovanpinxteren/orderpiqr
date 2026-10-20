"""Archive / restore / delete for picker devices.

Dead phones accumulate and most of them cannot be deleted: PickList.device
cascades and billing counts picklists, so a device with history may only be
archived. Archiving is also not a block — a device that picks again un-archives
itself, which is what keeps a mistake from hiding a working phone.
"""
import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import activate

from orderpiqrApp.models import Customer, Device, PickList, Product, UserProfile

FINGERPRINT = 'lifecycle-fp'


class DeviceLifecycleTestCase(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='House of Tests')
        self.other_customer = Customer.objects.create(name='Other company')

        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        self.admin = User.objects.create_user(username='boss', password='secret123')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)
        self.client.login(username='boss', password='secret123')

    def make_device(self, name='Phone', customer=None, **kwargs):
        defaults = {
            'customer': customer or self.customer,
            'name': name,
            'description': '',
            'last_login': timezone.now(),
            'lists_picked': 0,
        }
        defaults.update(kwargs)
        return Device.objects.create(**defaults)

    def make_picklist(self, device, code='PL-1'):
        return PickList.objects.create(
            picklist_code=code, customer=device.customer, device=device)


class DeviceArchiveRestoreTests(DeviceLifecycleTestCase):
    def test_archive_sets_the_flag(self):
        device = self.make_device(device_fingerprint='fp-1')

        response = self.client.post(
            reverse('manage_device_archive', args=[device.device_id]))

        self.assertRedirects(response, reverse('manage_devices'))
        device.refresh_from_db()
        self.assertTrue(device.archived)

    def test_restore_clears_the_flag(self):
        device = self.make_device(device_fingerprint='fp-1', archived=True)

        response = self.client.post(
            reverse('manage_device_restore', args=[device.device_id]))

        self.assertEqual(response.status_code, 302)
        device.refresh_from_db()
        self.assertFalse(device.archived)

    def test_redirect_preserves_the_show_filter(self):
        device = self.make_device(device_fingerprint='fp-1', archived=True)

        response = self.client.post(
            reverse('manage_device_restore', args=[device.device_id]),
            {'show': 'archived'})

        self.assertRedirects(response, reverse('manage_devices') + '?show=archived')

    def test_get_does_not_archive(self):
        device = self.make_device(device_fingerprint='fp-1')

        response = self.client.get(
            reverse('manage_device_archive', args=[device.device_id]))

        self.assertEqual(response.status_code, 302)
        device.refresh_from_db()
        self.assertFalse(device.archived)

    def test_cannot_archive_another_customers_device(self):
        foreign = self.make_device('Theirs', customer=self.other_customer,
                                   device_fingerprint='fp-theirs')

        response = self.client.post(
            reverse('manage_device_archive', args=[foreign.device_id]))

        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertFalse(foreign.archived)

    def test_cannot_restore_another_customers_device(self):
        foreign = self.make_device('Theirs', customer=self.other_customer,
                                   device_fingerprint='fp-theirs', archived=True)

        response = self.client.post(
            reverse('manage_device_restore', args=[foreign.device_id]))

        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertTrue(foreign.archived)


class DeviceDeleteTests(DeviceLifecycleTestCase):
    def test_delete_refused_for_a_device_with_picklists(self):
        device = self.make_device(device_fingerprint='fp-1')
        picklist = self.make_picklist(device)

        response = self.client.post(
            reverse('manage_device_delete', args=[device.device_id]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Device.objects.filter(pk=device.pk).exists())
        # PickList.device cascades: the history must still be there.
        self.assertTrue(PickList.objects.filter(pk=picklist.pk).exists())

    def test_delete_refusal_explains_itself(self):
        device = self.make_device(device_fingerprint='fp-1')
        self.make_picklist(device)

        response = self.client.post(
            reverse('manage_device_delete', args=[device.device_id]), follow=True)

        self.assertContains(response, 'can only be archived')

    def test_delete_allowed_without_picklists(self):
        device = self.make_device(device_fingerprint='fp-1')

        response = self.client.post(
            reverse('manage_device_delete', args=[device.device_id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Device.objects.filter(pk=device.pk).exists())

    def test_cannot_delete_another_customers_device(self):
        foreign = self.make_device('Theirs', customer=self.other_customer,
                                   device_fingerprint='fp-theirs')

        response = self.client.post(
            reverse('manage_device_delete', args=[foreign.device_id]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Device.objects.filter(pk=foreign.pk).exists())

    def test_get_does_not_delete(self):
        device = self.make_device(device_fingerprint='fp-1')

        self.client.get(reverse('manage_device_delete', args=[device.device_id]))

        self.assertTrue(Device.objects.filter(pk=device.pk).exists())


class DevicesListFilterTests(DeviceLifecycleTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('manage_devices')
        self.live = self.make_device('Live phone', device_fingerprint='fp-live')
        self.dead = self.make_device('Dead phone', device_fingerprint='fp-dead',
                                     archived=True)

    def listed(self, **params):
        return [d.name for d in self.client.get(self.url, params).context['devices']]

    def test_default_hides_archived_devices(self):
        self.assertEqual(self.listed(), ['Live phone'])

    def test_show_archived(self):
        self.assertEqual(self.listed(show='archived'), ['Dead phone'])

    def test_show_all(self):
        self.assertEqual(sorted(self.listed(show='all')), ['Dead phone', 'Live phone'])

    def test_unknown_show_value_falls_back_to_active(self):
        response = self.client.get(self.url, {'show': 'nonsense'})
        self.assertEqual(response.context['show'], 'active')
        self.assertEqual([d.name for d in response.context['devices']], ['Live phone'])

    def test_counts_are_exposed_for_the_filter_labels(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['active_count'], 1)
        self.assertEqual(response.context['archived_count'], 1)

    def test_picklist_count_is_annotated(self):
        self.make_picklist(self.live, code='PL-1')
        self.make_picklist(self.live, code='PL-2')

        listed = {d.name: d for d in self.client.get(self.url, {'show': 'all'}).context['devices']}

        self.assertEqual(listed['Live phone'].picklist_count, 2)
        self.assertEqual(listed['Dead phone'].picklist_count, 0)

    def test_delete_lives_in_the_bulk_bar_not_per_row(self):
        # Per-row delete was replaced by the bulk bar: the single-device delete
        # view stays (and keeps refusing devices with history), but the page
        # offers deletion through the bulk endpoint, which skips and reports
        # devices with picked lists instead of hiding the button.
        response = self.client.get(self.url)
        self.assertNotContains(
            response, reverse('manage_device_delete', args=[self.live.device_id]))
        self.assertContains(response, reverse('manage_devices_bulk_action'))

    def test_search_filters_by_name(self):
        response = self.client.get(self.url, {'q': 'live', 'show': 'all'})
        self.assertEqual([d.name for d in response.context['devices']], ['Live phone'])


class DeviceAutoReviveTests(TestCase):
    """An archived device that picks again must come back into view.

    Archiving is cleanup, not a block: a phone archived by mistake would
    otherwise keep working while being invisible to the admin who archived it.
    """

    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='Healthy Fridge')
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        self.picker = User.objects.create_user(username='picker1', password='pw12345678')
        self.picker.groups.add(picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)

        self.device = Device.objects.create(
            user=self.picker, customer=self.customer, device_fingerprint=FINGERPRINT,
            name='Archived phone', description='', last_login=timezone.now(),
            lists_picked=0, archived=True)
        self.smoothie = Product.objects.create(
            customer=self.customer, code='SMOOTHIE-1', description='Green smoothie')

        self.client.login(username='picker1', password='pw12345678')

    def test_scanning_a_picklist_unarchives_the_device(self):
        response = self.client.post('/orderpiqr/scan-picklist', data=json.dumps({
            'orderID': 'ORD-1',
            'picklist': ['SMOOTHIE-1'],
            'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertFalse(self.device.archived)

    def test_a_pick_unarchives_the_device(self):
        self.client.post('/orderpiqr/scan-picklist', data=json.dumps({
            'orderID': 'ORD-1',
            'picklist': ['SMOOTHIE-1'],
            'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')
        Device.objects.filter(pk=self.device.pk).update(archived=True)

        response = self.client.post('/orderpiqr/product-pick', data=json.dumps({
            'orderID': 'ORD-1', 'productCode': 'SMOOTHIE-1',
            'deviceFingerprint': FINGERPRINT, 'timeTakenMs': 500,
        }), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertFalse(self.device.archived)

    def test_activity_stamp_still_moves_for_a_device_that_was_not_archived(self):
        Device.objects.filter(pk=self.device.pk).update(
            archived=False, last_login=timezone.now() - timedelta(hours=3))

        self.client.post('/orderpiqr/scan-picklist', data=json.dumps({
            'orderID': 'ORD-1',
            'picklist': ['SMOOTHIE-1'],
            'deviceFingerprint': FINGERPRINT,
        }), content_type='application/json')

        self.device.refresh_from_db()
        self.assertFalse(self.device.archived)
        self.assertLess((timezone.now() - self.device.last_login).total_seconds(), 60)

    def test_re_registering_unarchives_the_device(self):
        response = self.client.post(reverse('name_entry'), {
            'name': 'Milo',
            'device_fingerprint': FINGERPRINT,
            'next': '/',
        })

        self.assertEqual(response.status_code, 302)
        self.device.refresh_from_db()
        self.assertFalse(self.device.archived)


class DevicesBulkActionTests(DeviceLifecycleTestCase):
    """The bulk endpoint mirrors the per-device views, including the delete
    guard: devices with picked lists are skipped and reported, never deleted."""

    def setUp(self):
        super().setUp()
        self.url = reverse('manage_devices_bulk_action')

    def post(self, payload):
        return self.client.post(self.url, json.dumps(payload),
                                content_type='application/json')

    def test_bulk_archive_and_skip_counts(self):
        live = self.make_device('Live', device_fingerprint='fp-a')
        dead = self.make_device('Dead', device_fingerprint='fp-b', archived=True)

        response = self.post({'action': 'archive',
                              'device_ids': [live.device_id, dead.device_id]})

        self.assertEqual(response.status_code, 200)
        live.refresh_from_db()
        self.assertTrue(live.archived)
        self.assertIn('1 device archived.', response.json()['message'])
        self.assertIn('1 device skipped (already archived).', response.json()['message'])

    def test_bulk_restore(self):
        dead = self.make_device('Dead', device_fingerprint='fp-c', archived=True)

        response = self.post({'action': 'restore', 'device_ids': [dead.device_id]})

        self.assertEqual(response.status_code, 200)
        dead.refresh_from_db()
        self.assertFalse(dead.archived)

    def test_bulk_delete_skips_devices_with_picklists(self):
        junk = self.make_device('Junk', device_fingerprint='fp-d')
        veteran = self.make_device('Veteran', device_fingerprint='fp-e')
        self.make_picklist(veteran)

        response = self.post({'action': 'delete',
                              'device_ids': [junk.device_id, veteran.device_id]})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Device.objects.filter(pk=junk.pk).exists())
        self.assertTrue(Device.objects.filter(pk=veteran.pk).exists())
        self.assertTrue(PickList.objects.filter(device=veteran).exists())
        self.assertIn('archive', response.json()['message'])

    def test_other_customers_devices_are_never_touched(self):
        foreign = self.make_device('Foreign', customer=self.other_customer,
                                   device_fingerprint='fp-f')

        response = self.post({'action': 'archive', 'device_ids': [foreign.device_id]})

        self.assertEqual(response.status_code, 400)
        foreign.refresh_from_db()
        self.assertFalse(foreign.archived)

    def test_select_all_honours_the_filters(self):
        live = self.make_device('Live', device_fingerprint='fp-g')
        dead = self.make_device('Dead', device_fingerprint='fp-h', archived=True)

        # The archived view selected with "all matching": only Dead restores.
        response = self.post({'action': 'restore', 'select_all': True,
                              'filters': {'show': 'archived'}})

        self.assertEqual(response.status_code, 200)
        dead.refresh_from_db()
        live.refresh_from_db()
        self.assertFalse(dead.archived)
        self.assertFalse(live.archived)
        self.assertIn('1 device restored.', response.json()['message'])

    def test_select_all_honours_the_search(self):
        old = self.make_device('Old warehouse phone', device_fingerprint='fp-i')
        new = self.make_device('New phone', device_fingerprint='fp-j')

        response = self.post({'action': 'archive', 'select_all': True,
                              'filters': {'q': 'old warehouse'}})

        self.assertEqual(response.status_code, 200)
        old.refresh_from_db()
        new.refresh_from_db()
        self.assertTrue(old.archived)
        self.assertFalse(new.archived)

    def test_seen_before_filter_matches_stale_devices(self):
        stale = self.make_device('Stale', device_fingerprint='fp-k',
                                 last_login=timezone.now() - timedelta(days=90))
        fresh = self.make_device('Fresh', device_fingerprint='fp-l')
        cutoff = (timezone.now() - timedelta(days=30)).date().isoformat()

        response = self.post({'action': 'archive', 'select_all': True,
                              'filters': {'seen_to': cutoff}})

        self.assertEqual(response.status_code, 200)
        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertTrue(stale.archived)
        self.assertFalse(fresh.archived)

    def test_invalid_action_rejected(self):
        device = self.make_device('Phone', device_fingerprint='fp-m')
        response = self.post({'action': 'explode', 'device_ids': [device.device_id]})
        self.assertEqual(response.status_code, 400)

    def test_requires_admin(self):
        picker_group, _ = Group.objects.get_or_create(name='orderpicker')
        picker = User.objects.create_user(username='picker9', password='pw12345678')
        picker.groups.add(picker_group)
        UserProfile.objects.create(user=picker, customer=self.customer)
        self.client.login(username='picker9', password='pw12345678')
        device = self.make_device('Phone', device_fingerprint='fp-n')

        response = self.post({'action': 'archive', 'device_ids': [device.device_id]})

        self.assertNotEqual(response.status_code, 200)
        device.refresh_from_db()
        self.assertFalse(device.archived)
