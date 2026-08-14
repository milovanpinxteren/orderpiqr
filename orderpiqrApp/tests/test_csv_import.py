"""Tests for the CSV import flows (manage portal) and the csv_import helper.

These cover the failure modes that broke the Shopify App Store review:
semicolon-delimited files, unexpected header names/casing, non-UTF-8
encodings, short rows and files that yield zero imported products.
"""
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from orderpiqrApp.models import Customer, Order, Product, UserProfile
from orderpiqrApp.utils.csv_import import (
    CSVImportError, ORDER_CSV_FIELDS, PRODUCT_CSV_FIELDS, parse_bool, read_csv_rows,
)


def upload(content, name='products.csv'):
    if isinstance(content, str):
        content = content.encode('utf-8')
    return SimpleUploadedFile(name, content, content_type='text/csv')


class ReadCsvRowsTests(TestCase):
    def test_plain_comma_csv(self):
        rows = read_csv_rows(upload("code,description,location,active\nA1,Widget,Shelf 1,true\n"),
                             PRODUCT_CSV_FIELDS)
        self.assertEqual(rows, [(2, {'code': 'A1', 'description': 'Widget',
                                     'location': 'Shelf 1', 'active': 'true'})])

    def test_semicolon_csv(self):
        rows = read_csv_rows(upload("code;description;location\nA1;Widget;Shelf 1\n"),
                             PRODUCT_CSV_FIELDS)
        self.assertEqual(rows[0][1]['code'], 'A1')
        self.assertEqual(rows[0][1]['description'], 'Widget')

    def test_uppercase_and_spaced_headers(self):
        rows = read_csv_rows(upload("Product Code,DESCRIPTION\nA1,Widget\n"), PRODUCT_CSV_FIELDS)
        self.assertEqual(rows[0][1]['code'], 'A1')

    def test_shopify_product_export_headers(self):
        rows = read_csv_rows(upload("Handle,Title,Variant SKU\nwidget,Widget,A1\n"),
                             PRODUCT_CSV_FIELDS)
        self.assertEqual(rows[0][1]['code'], 'A1')
        self.assertEqual(rows[0][1]['description'], 'Widget')

    def test_utf8_bom_and_cp1252(self):
        rows = read_csv_rows(upload('﻿code,description\nA1,Widget\n'.encode('utf-8')),
                             PRODUCT_CSV_FIELDS)
        self.assertEqual(rows[0][1]['code'], 'A1')
        rows = read_csv_rows(upload('code,description\nA1,Caf\xe9\n'.encode('cp1252')),
                             PRODUCT_CSV_FIELDS)
        self.assertEqual(rows[0][1]['description'], 'Café')

    def test_short_rows_do_not_crash(self):
        rows = read_csv_rows(upload("code,description,location,active\nA1,Widget\n"),
                             PRODUCT_CSV_FIELDS)
        self.assertEqual(rows[0][1]['location'], '')

    def test_missing_required_columns_raises(self):
        with self.assertRaises(CSVImportError):
            read_csv_rows(upload("foo,bar\n1,2\n"), PRODUCT_CSV_FIELDS)

    def test_empty_file_raises(self):
        with self.assertRaises(CSVImportError):
            read_csv_rows(upload(""), PRODUCT_CSV_FIELDS)

    def test_header_only_raises(self):
        with self.assertRaises(CSVImportError):
            read_csv_rows(upload("code,description\n"), PRODUCT_CSV_FIELDS)

    def test_parse_bool(self):
        self.assertTrue(parse_bool('ja'))
        self.assertTrue(parse_bool(''))
        self.assertFalse(parse_bool('false'))
        self.assertFalse(parse_bool('0'))


class ImportViewTestBase(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Testco', description='')
        self.user = User.objects.create_user('admin1', password='pw12345678')
        group, _created = Group.objects.get_or_create(name='companyadmin')
        self.user.groups.add(group)
        UserProfile.objects.create(user=self.user, customer=self.customer)
        self.client.force_login(self.user)


class ProductsImportViewTests(ImportViewTestBase):
    url = reverse('manage_products_import')

    def test_semicolon_csv_imports(self):
        response = self.client.post(self.url, {
            'csv_file': upload("code;description;location\nA1;Widget;Shelf 1\n")})
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(customer=self.customer, code='A1')
        self.assertEqual(product.location, 'Shelf 1')

    def test_shopify_export_imports(self):
        response = self.client.post(self.url, {
            'csv_file': upload("Handle,Title,Variant SKU\nwidget,Widget,A1\n")})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.filter(customer=self.customer, code='A1').exists())

    def test_wrong_columns_shows_error_not_success(self):
        response = self.client.post(self.url, {
            'csv_file': upload("foo,bar\n1,2\n")}, follow=True)
        self.assertEqual(response.status_code, 200)
        messages = [m for m in response.context['messages']]
        self.assertTrue(any(m.level_tag == 'error' for m in messages))
        self.assertEqual(Product.objects.count(), 0)

    def test_zero_rows_imported_is_an_error(self):
        response = self.client.post(self.url, {
            'csv_file': upload("code,description\n,\n,\n")}, follow=True)
        messages = [m for m in response.context['messages']]
        self.assertTrue(any(m.level_tag == 'error' for m in messages))

    def test_uppercase_extension_accepted(self):
        response = self.client.post(self.url, {
            'csv_file': upload("code,description\nA1,Widget\n", name='PRODUCTS.CSV')})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.filter(code='A1').exists())

    def test_no_500_on_garbage_bytes(self):
        response = self.client.post(self.url, {
            'csv_file': upload(b'\x00\x01\x02\xff\xfe')}, follow=True)
        self.assertEqual(response.status_code, 200)


class OrdersImportViewTests(ImportViewTestBase):
    url = reverse('manage_orders_import')

    def setUp(self):
        super().setUp()
        Product.objects.create(customer=self.customer, code='SKU-1',
                               description='Widget', location='A')

    def test_import_with_alias_headers(self):
        response = self.client.post(self.url, {
            'csv_file': upload("Order Number;SKU;Quantity\nORD-1;SKU-1;2\n",
                               name='orders.csv')})
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(customer=self.customer, order_code='ORD-1')
        self.assertEqual(order.lines.get().quantity, 2)

    def test_unknown_product_reports_error(self):
        response = self.client.post(self.url, {
            'csv_file': upload("order_code,product_code\nORD-2,NOPE\n",
                               name='orders.csv')}, follow=True)
        messages = [m for m in response.context['messages']]
        self.assertTrue(any(m.level_tag in ('error', 'warning') for m in messages))
