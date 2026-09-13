"""Picker-account management on the manage/profile page."""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import activate

from orderpiqrApp.models import Customer, UserProfile


class PickerManagementTests(TestCase):
    def setUp(self):
        activate('en')
        self.customer = Customer.objects.create(name='House of Tests')
        admin_group, _ = Group.objects.get_or_create(name='companyadmin')
        self.picker_group, _ = Group.objects.get_or_create(name='orderpicker')

        self.admin = User.objects.create_user(username='boss', password='secret123')
        self.admin.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin, customer=self.customer)

        self.picker = User.objects.create_user(username='picker1', password='old-password')
        self.picker.groups.add(self.picker_group)
        UserProfile.objects.create(user=self.picker, customer=self.customer)

        self.client.login(username='boss', password='secret123')
        self.url = reverse('manage_profile')

    def test_profile_lists_picker_accounts(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'picker1')

    def test_set_picker_password(self):
        response = self.client.post(self.url, {
            'action': 'set_picker_password',
            'picker_id': self.picker.pk,
            'picker_password': 'new-password-123',
        })
        self.assertEqual(response.status_code, 302)
        self.picker.refresh_from_db()
        self.assertTrue(self.picker.check_password('new-password-123'))

    def test_cannot_set_password_of_other_customers_picker(self):
        other_customer = Customer.objects.create(name='Other company')
        outsider = User.objects.create_user(username='outsider', password='old-password')
        outsider.groups.add(self.picker_group)
        UserProfile.objects.create(user=outsider, customer=other_customer)

        self.client.post(self.url, {
            'action': 'set_picker_password',
            'picker_id': outsider.pk,
            'picker_password': 'hijacked-password',
        })
        outsider.refresh_from_db()
        self.assertTrue(outsider.check_password('old-password'))

    def test_cannot_set_password_of_admin_via_picker_action(self):
        # The admin user is not in the orderpicker group; the picker action
        # must not touch it even with a valid user id.
        self.client.post(self.url, {
            'action': 'set_picker_password',
            'picker_id': self.admin.pk,
            'picker_password': 'sneaky-password',
        })
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('secret123'))

    def test_short_password_rejected(self):
        self.client.post(self.url, {
            'action': 'set_picker_password',
            'picker_id': self.picker.pk,
            'picker_password': 'short',
        })
        self.picker.refresh_from_db()
        self.assertTrue(self.picker.check_password('old-password'))

    def test_create_picker_account(self):
        response = self.client.post(self.url, {
            'action': 'create_picker',
            'picker_username': 'picker2',
            'picker_password': 'fresh-password',
        })
        self.assertEqual(response.status_code, 302)
        new_picker = User.objects.get(username='picker2')
        self.assertTrue(new_picker.check_password('fresh-password'))
        self.assertTrue(new_picker.groups.filter(name='orderpicker').exists())
        self.assertEqual(new_picker.userprofile.customer, self.customer)

    def test_create_picker_rejects_duplicate_username(self):
        self.client.post(self.url, {
            'action': 'create_picker',
            'picker_username': 'picker1',
            'picker_password': 'fresh-password',
        })
        self.assertEqual(User.objects.filter(username='picker1').count(), 1)
