"""Mechanical checks on the gettext catalogs in ``locale/``.

Catches the translation mistakes that are objectively wrong rather than a
matter of wording, which is exactly the class a human reviewer skims past:

* a placeholder that was renamed, dropped, or invented — these raise at render
  time or silently print the wrong number
* HTML markup that was mangled, which breaks the page layout
* ``#, fuzzy`` entries, which ``compilemessages`` silently drops from the .mo,
  so the string renders in English while the .po looks translated
* empty translations in a locale that is supposed to be complete
* whitespace that does not match, which runs words together in the UI

Run: python scripts/check_translations.py
Exits non-zero when anything is wrong, so it can gate a deploy.

``--locales`` / ``--domains`` narrow the run. ``SOURCE_LOCALE`` is skipped for
the empty-translation and identical-text checks, because an untranslated entry
there correctly falls back to the msgid.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import polib
except ImportError:
    sys.exit('polib is required: pip install polib')

LOCALE_DIR = Path(__file__).resolve().parent.parent / 'locale'
SOURCE_LOCALE = 'en'
DOMAINS = ('django', 'djangojs')

#: %(name)s, %s, %d and {name} / {} — every interpolation style in the app.
PERCENT_NAMED = re.compile(r'%\([^)]*\)[sdifgeErxX%]')
PERCENT_POSITIONAL = re.compile(r'%[sdifgeErxX]')
#: Only a bare name in braces. Deliberately not ``\{[^{}]*\}``: a help_text
#: documents a JSON example (``[{"value": "original", ...}]``) whose inner
#: labels translators may legitimately localise, and the loose pattern read
#: that example as a placeholder and flagged every locale.
BRACE_FORMAT = re.compile(r'\{[a-zA-Z_][a-zA-Z0-9_]*\}|\{\}')
HTML_TAG = re.compile(r'</?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>')

#: How many plural forms each language actually has, per CLDR and per Django's
#: own catalogs in django/conf/locale/<lang>/LC_MESSAGES/django.po.
#:
#: This exists because ``makemessages`` seeds every new catalog with English's
#: ``nplurals=2; plural=(n != 1)`` no matter the language, and nobody notices:
#: Polish shipped 2 forms instead of 4, Romanian 2 instead of 3 and Ukrainian
#: 3 instead of 4, so none of them could inflect a counted noun at all.
EXPECTED_NPLURALS = {
    'en': 2, 'nl': 2, 'de': 2, 'fr': 2,
    'ro': 3,
    'pl': 4, 'uk': 4,
}

#: Translations that are legitimately identical to the English. Without this,
#: the identical-text check is pure noise for loanwords and symbols.
IDENTICAL_IS_FINE = {
    'Barcode', 'EAN', 'SKU', 'QR', 'QR code', 'API', 'CSV', 'JSON', 'URL',
    'OrderPiqr', 'Orderpiqr', 'Shopify', 'WooCommerce', 'E-mail', 'Email',
    'Picker', 'Pick', 'Scan', 'Import', 'Export', 'Status', 'Total', 'Online',
    'Offline', 'Product', 'Service', 'Server', 'Token', 'Partner', 'Locatie',
    '%(count)s', '-', '—', ':', '/',
}


def placeholders(text):
    """The multiset of interpolations in ``text``, as a sorted list."""
    return sorted(
        PERCENT_NAMED.findall(text)
        + PERCENT_POSITIONAL.findall(PERCENT_NAMED.sub('', text))
        + BRACE_FORMAT.findall(text)
    )


def html_tags(text):
    """Tag names in document order — catches dropped and reordered markup."""
    return HTML_TAG.findall(text)


def describe_tag_difference(source_tags, translation_tags):
    """Summarise an HTML mismatch instead of dumping both tag lists.

    The long tour strings carry forty-odd tags, and printing both sequences
    buries the one that actually changed.
    """
    source_counts = Counter(source_tags)
    translation_counts = Counter(translation_tags)

    changes = []
    for tag in sorted(set(source_counts) | set(translation_counts)):
        expected, actual = source_counts[tag], translation_counts[tag]
        if expected != actual:
            changes.append(f'<{tag}> {expected}x -> {actual}x')

    if changes:
        return 'tag counts differ: ' + ', '.join(changes)

    # Same tags, different order — report where the sequences diverge.
    for index, (expected, actual) in enumerate(zip(source_tags, translation_tags)):
        if expected != actual:
            return (f'tags reordered at position {index}: '
                    f'expected <{expected}>, found <{actual}>')
    return 'tag sequences differ in length'


def translated_forms(entry):
    """Every non-empty translation on an entry, singular or plural."""
    if entry.msgstr_plural:
        return [t for t in entry.msgstr_plural.values() if t]
    return [entry.msgstr] if entry.msgstr else []


def source_for(entry, index=0):
    """The English text a given translation form corresponds to."""
    if entry.msgstr_plural and index > 0 and entry.msgid_plural:
        return entry.msgid_plural
    return entry.msgid


def check_entry(entry, locale, domain, problems, warnings):
    where = f'{locale}/{domain}:{entry.linenum}'
    short = entry.msgid.replace('\n', ' ')[:70]

    if 'fuzzy' in entry.flags:
        problems.append(
            f'{where}: FUZZY — compilemessages drops this, so it renders in '
            f'English: "{short}" -> "{entry.msgstr[:70]}"')

    forms = translated_forms(entry)

    if not forms and locale != SOURCE_LOCALE:
        problems.append(f'{where}: UNTRANSLATED: "{short}"')
        return

    for index, translation in enumerate(
            entry.msgstr_plural.values() if entry.msgstr_plural else [entry.msgstr]):
        if not translation:
            if locale != SOURCE_LOCALE:
                problems.append(
                    f'{where}: UNTRANSLATED plural form {index}: "{short}"')
            continue

        source = source_for(entry, index)

        expected, actual = placeholders(source), placeholders(translation)
        if expected != actual:
            problems.append(
                f'{where}: PLACEHOLDER MISMATCH on "{short}": '
                f'English has {expected or "none"}, translation has {actual or "none"}')

        # makemessages writes a literal % from a template as %%, and Django
        # un-escapes it at render time. A translator who "tidies" %%(name)s
        # down to %(name)s leaves a string that still looks right here but
        # prints a stray % to the user, so the doubling has to match too.
        if source.count('%%') != translation.count('%%'):
            problems.append(
                f'{where}: DOUBLED-PERCENT MISMATCH on "{short}": English has '
                f'{source.count("%%")} "%%" sequence(s), translation has '
                f'{translation.count("%%")} — keep %% exactly as in the English')

        source_tags, translation_tags = html_tags(source), html_tags(translation)
        if source_tags != translation_tags:
            problems.append(
                f'{where}: HTML MISMATCH on "{short}": '
                f'{describe_tag_difference(source_tags, translation_tags)}')

        for edge, label in ((lambda s: s[:1], 'leading'), (lambda s: s[-1:], 'trailing')):
            if edge(source).isspace() != edge(translation).isspace():
                problems.append(
                    f'{where}: {label.upper()} WHITESPACE differs on "{short}" — '
                    'words will run together or gain a stray space')

        # A judgement call, not an error: French "Date" and German "Name" are
        # correct translations. Reported separately so it never drowns out the
        # errors above, and never fails the run.
        if (locale != SOURCE_LOCALE and translation == source
                and source not in IDENTICAL_IS_FINE and len(source) > 3):
            warnings.append(
                f'{where}: identical to English, worth a look: "{short}"')


def check_compiled(catalog, po_path, locale, domain, problems):
    """Verify the committed .mo actually carries the .po's translations.

    Nothing compiles on deploy — the Heroku release phase only runs ``migrate``
    — so the ``.mo`` files ship from git. A translated ``.po`` whose ``.mo`` was
    never recompiled is invisible: the catalog looks finished and production
    still serves English.

    Compares catalog content, not timestamps: a fresh clone or a branch switch
    writes every file at once, so mtimes say nothing about staleness.
    """
    mo_path = po_path.with_suffix('.mo')
    if not mo_path.exists():
        problems.append(
            f'{locale}/{domain}: NOT COMPILED — {mo_path.name} is missing. '
            f'Run "python manage.py compilemessages".')
        return

    try:
        compiled = {entry.msgid: entry for entry in polib.mofile(str(mo_path))}
    except Exception as exc:  # a truncated or corrupt .mo
        problems.append(f'{locale}/{domain}: UNREADABLE {mo_path.name}: {exc}')
        return

    # msgfmt drops fuzzy and untranslated entries, so only compare the ones it
    # should have kept.
    stale = []
    for entry in catalog:
        if entry.obsolete or 'fuzzy' in entry.flags:
            continue
        if entry.msgid_plural:
            expected = entry.msgstr_plural or {}
            if not any(expected.values()):
                continue
            actual = compiled.get(entry.msgid)
            if actual is None or dict(actual.msgstr_plural) != dict(expected):
                stale.append(entry.msgid)
        else:
            if not entry.msgstr:
                continue
            actual = compiled.get(entry.msgid)
            if actual is None or actual.msgstr != entry.msgstr:
                stale.append(entry.msgid)

    if stale:
        problems.append(
            f'{locale}/{domain}: STALE {mo_path.name} — {len(stale)} entr(ies) '
            f'differ from the .po, so production would serve the old text. '
            f'Run "python manage.py compilemessages". First: '
            f'"{stale[0][:60]}"')


def check_plural_header(catalog, locale, domain, problems):
    """Verify the catalog declares the right number of plural forms.

    A wrong ``nplurals`` is silent: gettext just picks the wrong form, so
    "5 zamowien" comes out as "5 zamowienia" and nothing anywhere complains.
    """
    header = catalog.metadata.get('Plural-Forms', '')
    match = re.search(r'nplurals\s*=\s*(\d+)', header)
    if not match:
        problems.append(
            f'{locale}/{domain}: NO Plural-Forms header — plural entries cannot '
            f'work. Copy the value from Django\'s own catalog for this language.')
        return

    declared = int(match.group(1))
    expected = EXPECTED_NPLURALS.get(locale)
    if expected is not None and declared != expected:
        problems.append(
            f'{locale}/{domain}: WRONG Plural-Forms — header declares '
            f'nplurals={declared} but {locale} has {expected} plural forms. '
            f'Counted nouns will take the wrong form. Copy the value from '
            f'django/conf/locale/{locale}/LC_MESSAGES/django.po.')
        return

    # The header and the entries have to agree, or msgfmt rejects the catalog.
    for entry in catalog:
        if entry.obsolete or not entry.msgid_plural:
            continue
        forms = len(entry.msgstr_plural or {})
        if forms != declared:
            problems.append(
                f'{locale}/{domain}:{entry.linenum}: entry has {forms} plural '
                f'form(s) but the header declares nplurals={declared}: '
                f'"{entry.msgid[:55]}"')


def _normalize_msgid(msgid):
    """Fold away differences that must not change the translation."""
    return msgid.strip().rstrip('.:!?').casefold()


def check_duplicate_translations(catalog, locale, domain, warnings):
    """Flag one translation reused verbatim for two different English strings.

    This is the fingerprint of an accepted msgmerge guess, which is how the
    worst bugs in this repo shipped: French ``Product found`` carried the
    msgstr of ``No products found`` and was displayed on *successful* scans.

    A warning, not an error — distinct English strings legitimately collapse to
    one translation sometimes ("Delete"/"Remove", "Qty"/"Quantity"). The point
    is to put the pairs in front of a human.
    """
    by_translation = {}
    for entry in catalog:
        if entry.obsolete or not entry.msgstr or entry.msgid_plural:
            continue
        # Short strings collide constantly and harmlessly; long prose does not.
        if len(entry.msgstr) < 12:
            continue
        by_translation.setdefault(entry.msgstr, []).append(entry)

    for translation, entries in sorted(by_translation.items()):
        if len(entries) < 2:
            continue
        # The source has ~40 msgid pairs differing only in capitalisation or a
        # trailing period ("Save Settings"/"Save settings", "Last Seen"/"Last
        # seen"). One translation for those is not merely acceptable, it is
        # required, and reporting them buries the pairs that matter.
        if len({_normalize_msgid(e.msgid) for e in entries}) < 2:
            continue
        ids = ' | '.join(f'"{e.msgid[:45]}"' for e in entries)
        warnings.append(
            f'{locale}/{domain}:{entries[0].linenum}: SAME translation for '
            f'{len(entries)} different msgids — check none is a stale guess: '
            f'{ids} all render as "{translation[:55]}"')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--locales', nargs='*', help='default: every locale on disk')
    parser.add_argument('--domains', nargs='*', default=list(DOMAINS))
    parser.add_argument('--quiet', action='store_true',
                        help='errors only — skip the warning lists')
    parser.add_argument('--check-compiled', action='store_true',
                        help='also fail if a .mo is missing or out of date')
    args = parser.parse_args()

    locales = args.locales or sorted(
        path.name for path in LOCALE_DIR.iterdir() if path.is_dir())

    problems, warnings, checked = [], [], 0
    for locale in locales:
        for domain in args.domains:
            path = LOCALE_DIR / locale / 'LC_MESSAGES' / f'{domain}.po'
            if not path.exists():
                problems.append(f'{locale}/{domain}: MISSING catalog at {path}')
                continue
            catalog = polib.pofile(str(path))
            for entry in catalog:
                if entry.obsolete:
                    continue
                checked += 1
                check_entry(entry, locale, domain, problems, warnings)
            check_plural_header(catalog, locale, domain, problems)
            check_duplicate_translations(catalog, locale, domain, warnings)
            if args.check_compiled:
                check_compiled(catalog, path, locale, domain, problems)

    print(f'Checked {checked} entries across {len(locales)} locales.')

    if problems:
        print(f'\n{len(problems)} ERROR(S) — these are wrong, not debatable:')
        for problem in problems:
            print(f'  {problem}')
    else:
        print('No errors.')

    if warnings and not args.quiet:
        print(f'\n{len(warnings)} entr(ies) to eyeball:')
        for warning in warnings:
            print(f'  {warning}')

    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
