"""Keep a diagnostic line from killing the script that printed it.

The translation tooling prints translated text — msgids, guessed translations,
template snippets — and a Windows console hands Python a legacy codepage
(cp1252 here) that cannot encode Polish or Romanian. One 'ż' in a report raised
UnicodeEncodeError mid-run: ``strip_fuzzy_translations.py`` died after some
catalogs had already been written and before the rest were looked at, so the
step the README calls mandatory half-ran and the operator saw only a traceback.
The same crash in ``check_translations.py`` is worse — it gates ``git push``,
so a catalog error in the wrong language refuses the push without ever printing
which entry is wrong.

Imported by sibling scripts in this directory, which are always run as
``python scripts/<name>.py`` (the hook, the README, and the tests all do), so
``scripts/`` is on sys.path.
"""
import sys


def force_utf8_output():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
