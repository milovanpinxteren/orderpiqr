"""Robust reading of user-supplied CSV import files.

Merchants upload CSVs made with Excel, Numbers, Google Sheets or exported
from other systems (e.g. Shopify). Those files differ in delimiter
(comma vs semicolon vs tab), encoding (UTF-8 with/without BOM, cp1252),
header naming and capitalisation. This module normalises all of that so
import views only deal with clean dict rows.
"""
import csv
import io

from django.utils.translation import gettext as _


class CSVImportError(Exception):
    """Parsing failed in a way the user must fix; str() is user-friendly."""


def _decode(raw):
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1', errors='replace')


def _detect_delimiter(text):
    sample = '\n'.join(text.splitlines()[:10])
    try:
        return csv.Sniffer().sniff(sample, delimiters=',;\t').delimiter
    except csv.Error:
        first_line = text.splitlines()[0] if text.splitlines() else ''
        counts = {d: first_line.count(d) for d in (',', ';', '\t')}
        best = max(counts, key=counts.get)
        return best if counts[best] else ','


def _normalize_header(header):
    return ' '.join(header.replace('﻿', '').replace('_', ' ').split()).lower()


def read_csv_rows(uploaded_file, fields, max_size=5 * 1024 * 1024):
    """Read an uploaded CSV file into canonical dict rows.

    fields: {canonical_name: {'aliases': (...), 'required': bool}} where
    aliases are normalized (lowercase, spaces instead of underscores) and
    tried in order. Returns a list of (line_number, row_dict) with every
    canonical name present ('' when the file has no value). Raises
    CSVImportError with a message the user can act on.
    """
    if uploaded_file.size > max_size:
        raise CSVImportError(_("The file is larger than 5MB. Please split it into smaller files."))

    text = _decode(uploaded_file.read())
    if not text.strip():
        raise CSVImportError(_("The file is empty."))

    delimiter = _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        raw_header = next(reader)
    except StopIteration:
        raise CSVImportError(_("The file is empty."))

    normalized = [_normalize_header(h) for h in raw_header]
    column_map = {}
    for canonical, spec in fields.items():
        for alias in spec['aliases']:
            if alias in normalized:
                column_map[canonical] = normalized.index(alias)
                break

    missing = [name for name, spec in fields.items()
               if spec.get('required') and name not in column_map]
    if missing:
        raise CSVImportError(
            _("Could not find the required column(s) {missing}. "
              "Found columns: {found}. Please use the format shown below.").format(
                missing=', '.join('"%s"' % m for m in missing),
                found=', '.join('"%s"' % h.strip() for h in raw_header if h.strip()) or '-',
            ))

    rows = []
    for line_number, raw_row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in raw_row):
            continue
        row = {}
        for canonical in fields:
            index = column_map.get(canonical)
            value = raw_row[index] if index is not None and index < len(raw_row) else ''
            row[canonical] = (value or '').strip()
        rows.append((line_number, row))

    if not rows:
        raise CSVImportError(_("The file contains no data rows below the header."))

    return rows


def parse_bool(value, default=True):
    """Interpret a spreadsheet truthy/falsy cell value."""
    value = (value or '').strip().lower()
    if not value:
        return default
    if value in ('true', '1', 'yes', 'y', 'ja', 'actief', 'active', 'waar'):
        return True
    if value in ('false', '0', 'no', 'n', 'nee', 'inactief', 'inactive', 'onwaar'):
        return False
    return default


PRODUCT_CSV_FIELDS = {
    'code': {
        'required': True,
        'aliases': ('code', 'product code', 'productcode', 'sku', 'variant sku',
                    'barcode', 'variant barcode', 'artikelcode', 'artikelnummer'),
    },
    'description': {
        'required': True,
        'aliases': ('description', 'product description', 'title', 'name',
                    'product name', 'omschrijving', 'beschrijving', 'naam'),
    },
    'location': {
        'required': False,
        'aliases': ('location', 'warehouse location', 'locatie', 'magazijnlocatie'),
    },
    'active': {
        'required': False,
        'aliases': ('active', 'actief', 'enabled', 'status'),
    },
}

ORDER_CSV_FIELDS = {
    'order_code': {
        'required': True,
        'aliases': ('order code', 'order', 'order number', 'order id',
                    'ordernummer', 'bestelnummer', 'name'),
    },
    'product_code': {
        'required': True,
        'aliases': ('product code', 'productcode', 'sku', 'variant sku',
                    'lineitem sku', 'barcode', 'artikelcode', 'artikelnummer', 'code'),
    },
    'amount': {
        'required': False,
        'aliases': ('amount', 'quantity', 'qty', 'aantal', 'lineitem quantity'),
    },
    'notes': {
        'required': False,
        'aliases': ('notes', 'note', 'opmerking', 'opmerkingen'),
    },
}
