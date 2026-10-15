"""The translation catalogs must be valid and compiled.

The pre-push hook in ``.githooks/pre-push`` runs the same two checkers, but a
hook can be bypassed with ``--no-verify``, is only active once someone sets
``core.hooksPath``, and does nothing in CI. These tests give the same guarantee
to anybody who runs the suite.

They shell out to the scripts rather than reimplementing the rules, so there is
exactly one definition of "the catalogs are OK" and the failure output a
developer sees here is identical to what the hook prints.
"""
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / 'scripts'


def run_checker(script, *args):
    """Run a checker script and return (exit code, combined output)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    return result.returncode, (result.stdout or '') + (result.stderr or '')


class TranslationCatalogTestCase(SimpleTestCase):
    """Guards the failure modes that have actually shipped from this repo."""

    def test_catalogs_are_valid_and_compiled(self):
        """No fuzzy guesses, no untranslated entries, no stale .mo files.

        Covers: placeholders renamed or dropped, `%%` doubling, mangled HTML,
        mismatched edge whitespace, wrong Plural-Forms headers, and a .po whose
        .mo was never recompiled — which matters because the Heroku release
        phase runs only `migrate`, so the .mo files ship from git.
        """
        code, output = run_checker(
            'check_translations.py', '--check-compiled', '--quiet')
        self.assertEqual(
            code, 0,
            'Translation catalogs have errors. Run '
            '"python scripts/check_translations.py --check-compiled" '
            f'for detail.\n\n{output}')

    def test_no_translation_reaches_javascript_unescaped(self):
        """`{% trans %}` does not autoescape.

        A translation containing an apostrophe inside a JS string literal
        breaks the whole script block. Six pages shipped with all their
        JavaScript dead in French before this was caught.
        """
        code, output = run_checker('check_template_i18n.py', '--quiet')
        self.assertEqual(
            code, 0,
            'A translation reaches a JavaScript string literal unescaped. '
            'Use "{% trans \'…\' as v %}" plus "{{ v|escapejs }}".'
            f'\n\n{output}')
