"""Empty the fuzzy translations that ``makemessages`` invents.

When ``makemessages`` finds a new msgid, msgmerge guesses a translation from
whatever existing entry looks similar and marks it ``#, fuzzy``. The guess is
frequently a different sentence entirely: Romanian "No products in this
picklist." was filled in with the translation of "Pick of %(product)s in
picklist %(picklist_id)s", placeholders and all.

Those guesses are dangerous in two ways. ``compilemessages`` drops fuzzy
entries, so the string renders in English while the .po file looks translated
and a reviewer skips it. And if anyone clears the flag without rereading the
text — which is what happened here — the wrong sentence goes live.

Django's ``makemessages`` has no ``--no-fuzzy-matching`` (that is a msgmerge
flag it does not forward), so the guessing cannot be switched off. Run this
immediately after every ``makemessages`` instead: it clears the flag and empties
the text, turning each guess back into an honest untranslated entry.

    python manage.py makemessages -a -i ".venv/*" -i "node_modules/*" -i "staticfiles/*"
    python scripts/strip_fuzzy_translations.py
    # ...translate the now-empty entries, then:
    python manage.py compilemessages

``--dry-run`` reports what it would empty without writing.
"""
import argparse
import sys
from pathlib import Path

try:
    import polib
except ImportError:
    sys.exit('polib is required: pip install polib')

LOCALE_DIR = Path(__file__).resolve().parent.parent / 'locale'
DOMAINS = ('django', 'djangojs')


def strip_catalog(path, dry_run):
    """Empty every fuzzy entry in one catalog. Returns what was emptied."""
    catalog = polib.pofile(str(path))
    emptied = []

    for entry in catalog:
        if 'fuzzy' not in entry.flags or entry.obsolete:
            continue
        emptied.append((entry.msgid, entry.msgstr))
        entry.flags.remove('fuzzy')
        entry.msgstr = ''
        if entry.msgstr_plural:
            entry.msgstr_plural = {key: '' for key in entry.msgstr_plural}

    if emptied and not dry_run:
        catalog.save(str(path))
    return emptied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--locales', nargs='*', help='default: every locale on disk')
    parser.add_argument('--domains', nargs='*', default=list(DOMAINS))
    parser.add_argument('--dry-run', action='store_true',
                        help='report without writing')
    args = parser.parse_args()

    locales = args.locales or sorted(
        path.name for path in LOCALE_DIR.iterdir() if path.is_dir())

    total = 0
    for locale in locales:
        for domain in args.domains:
            path = LOCALE_DIR / locale / 'LC_MESSAGES' / f'{domain}.po'
            if not path.exists():
                continue
            emptied = strip_catalog(path, args.dry_run)
            if not emptied:
                continue
            total += len(emptied)
            print(f'{locale}/{domain}: emptied {len(emptied)} fuzzy entr(ies)')
            for msgid, guess in emptied:
                print(f'    "{msgid[:60]}" had been guessed as "{guess[:60]}"')

    verb = 'would empty' if args.dry_run else 'emptied'
    print(f'\n{verb} {total} fuzzy entr(ies). '
          f'{"Nothing written." if args.dry_run else "These now need translating."}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
