"""`device_user`/`device_username` on PickListSerializer (R5): who was
actually holding the device, not just which device it was — devices are
often shared across a shift.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from orderpiqrApp.models import Customer, Device, PickList, UserProfile


class PicklistPickerIdentityTestCase(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Warehouse A')
        self.user = User.objects.create_user(username='picker-a', password='x')
        UserProfile.objects.create(user=self.user, customer=self.customer)

        self.other_customer = Customer.objects.create(name='Warehouse B')
        self.other_user = User.objects.create_user(username='picker-b', password='x')
        UserProfile.objects.create(user=self.other_user, customer=self.other_customer)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def make_device(self, customer=None, user=None, name='Scanner 1'):
        return Device.objects.create(
            customer=customer or self.customer,
            user=user,
            name=name,
            description='',
            last_login=timezone.now(),
            lists_picked=0,
        )

    def make_picklist(self, device, code='PL-1', customer=None):
        return PickList.objects.create(
            customer=customer or self.customer,
            device=device,
            picklist_code=code,
            pick_started=True,
        )


class ListAndDetailTests(PicklistPickerIdentityTestCase):
    def test_list_shows_device_user_and_username(self):
        held_by = User.objects.create_user(username='nightshift-nina', password='x')
        device = self.make_device(user=held_by)
        self.make_picklist(device)

        response = self.client.get('/api/picklists/')
        row = response.data['results'][0]

        self.assertEqual(row['device_user'], held_by.pk)
        self.assertEqual(row['device_username'], 'nightshift-nina')

    def test_detail_shows_device_user_and_username(self):
        held_by = User.objects.create_user(username='nightshift-nina', password='x')
        device = self.make_device(user=held_by)
        picklist = self.make_picklist(device)

        response = self.client.get(f'/api/picklists/{picklist.picklist_id}/')

        self.assertEqual(response.data['device_user'], held_by.pk)
        self.assertEqual(response.data['device_username'], 'nightshift-nina')

    def test_device_without_a_user_is_null_not_an_error(self):
        device = self.make_device(user=None)
        picklist = self.make_picklist(device)

        list_response = self.client.get('/api/picklists/')
        detail_response = self.client.get(f'/api/picklists/{picklist.picklist_id}/')

        for response in (list_response.data['results'][0], detail_response.data):
            self.assertIsNone(response['device_user'])
            self.assertIsNone(response['device_username'])


class ScopingTests(PicklistPickerIdentityTestCase):
    def test_list_excludes_other_customers_picklists(self):
        foreign_device = self.make_device(customer=self.other_customer, user=self.other_user)
        self.make_picklist(foreign_device, code='PL-FOREIGN', customer=self.other_customer)

        own_device = self.make_device(user=self.user)
        mine = self.make_picklist(own_device, code='PL-MINE')

        response = self.client.get('/api/picklists/')
        codes = [row['picklist_code'] for row in response.data['results']]

        self.assertEqual(codes, ['PL-MINE'])
        self.assertEqual(response.data['results'][0]['picklist_id'], mine.picklist_id)

    def test_detail_on_another_customers_picklist_is_404(self):
        foreign_device = self.make_device(customer=self.other_customer, user=self.other_user)
        foreign = self.make_picklist(foreign_device, code='PL-FOREIGN', customer=self.other_customer)

        response = self.client.get(f'/api/picklists/{foreign.picklist_id}/')
        self.assertEqual(response.status_code, 404)
