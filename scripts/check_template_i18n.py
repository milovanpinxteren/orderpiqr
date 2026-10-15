"""Catch translated text interpolated unescaped into JavaScript.

``{% trans %}`` and ``{% blocktrans %}`` do **not** autoescape. When their
output lands inside a JavaScript string literal, a translation containing the
quote character closes the literal early and the whole ``<script>`` block
becomes a syntax error — every bit of JavaScript on the page dies.

This is not hypothetical. French has 168 translations containing an apostrophe,
and before this check existed six pages rendered
``showNotification('Une erreur s'est produite', 'error')`` and had all their
JavaScript dead in French, in production.

The fix at each site is Django's ``escapejs`` filter:

    {% trans "An error occurred" as msg_error %}
    ...
    showNotification('{{ msg_error|escapejs }}', 'error');

Run: python scripts/check_template_i18n.py
Exits non-zero when a translation reaches a JS literal unescaped.

Scope note: HTML attributes such as ``placeholder="…"`` are NOT a problem and
are deliberately not reported — they are double-quoted HTML, where an
apostrophe is harmless. Only JavaScript contexts are checked: ``<script>``
bodies and ``on*=`` event handlers.
"""
import re
import sys
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / 'templates'

#: Django constructs, masked out before the JavaScript is tokenised so that
#: quotes belonging to a tag ({% if x == 'y' %}) are not mistaken for JS string
#: delimiters. That exact confusion produced six false positives when this was
#: first attempted with a naive regex.
DJANGO_CONSTRUCT = re.compile(r'\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}', re.DOTALL)

SCRIPT_BLOCK = re.compile(r'<script\b([^>]*)>(.*?)</script\s*>', re.DOTALL | re.IGNORECASE)
EVENT_ATTR = re.compile(r'\bon[a-z]+\s*=\s*"([^"]*)"|\bon[a-z]+\s*=\s*\'([^\']*)\'',
                        re.IGNORECASE)

#: Emits nothing at its own position, so it is safe anywhere.
TRANS_ASVAR = re.compile(r'\{%\s*(?:trans|translate)\b[^%]*\bas\s+\w+\s*%\}'
                         r'|\{%\s*blocktrans(?:late)?\b[^%]*\basvar\s+\w+')
TRANS_OUTPUT = re.compile(r'\{%\s*(?:trans|translate|blocktrans|blocktranslate)\b')
HAS_ESCAPEJS = re.compile(r'\|\s*escapejs\b')

#: Variables that can never carry a quote, so they need no escaping. Keeping
#: this list short is the point — everything else gets eyeballed.
SAFE_VARIABLES = {'csrf_token'}


def mask_django(text):
    """Blank out Django constructs, preserving length and newlines.

    Returns ``(masked_text, [(start, end, source), ...])``.
    """
    spans = []
    masked = list(text)
    for match in DJANGO_CONSTRUCT.finditer(text):
        spans.append((match.start(), match.end(), match.group(0)))
        for i in range(match.start(), match.end()):
            if masked[i] != '\n':      # keep line numbering intact
                masked[i] = '\x01'
    return ''.join(masked), spans


def js_string_spans(js):
    """Spans of every string literal in ``js``, as (start, end) pairs.

    Deliberately simple: tracks the three JS quote styles, backslash escapes
    and both comment forms. Regex literals are not modelled, which can only
    cause a miss, never a false alarm.
    """
    spans = []
    i, n = 0, len(js)
    while i < n:
        ch = js[i]
        if ch == '/' and i + 1 < n and js[i + 1] == '/':
            i = js.find('\n', i)
            if i == -1:
                break
        elif ch == '/' and i + 1 < n and js[i + 1] == '*':
            end = js.find('*/', i + 2)
            i = n if end == -1 else end + 2
        elif ch in '\'"`':
            quote, start = ch, i
            i += 1
            while i < n:
                if js[i] == '\\':
                    i += 2
                    continue
                if js[i] == quote:
                    break
                # An unterminated single/double-quoted literal cannot span
                # lines; bail so one stray quote does not swallow the file.
                if js[i] == '\n' and quote != '`':
                    break
                i += 1
            spans.append((start, min(i, n - 1) + 1))
            i += 1
        else:
            i += 1
    return spans


def js_regions(masked):
    """JavaScript regions as (start, end) offsets into the MASKED document.

    Must be given the masked text, not the source: an event handler such as
    ``onsubmit="return confirm('{% trans "Gone?" %}');"`` contains double
    quotes inside the Django tag, so matching the attribute against the raw
    source truncates the value at the first one and the site goes unchecked.
    Masking removes those quotes first.
    """
    regions = []
    for match in SCRIPT_BLOCK.finditer(masked):
        attrs = match.group(1)
        if re.search(r'\bsrc\s*=', attrs, re.IGNORECASE):
            continue                   # external script, no inline body
        if re.search(r'type\s*=\s*["\'](?!text/javascript|module)', attrs, re.IGNORECASE):
            continue                   # JSON-LD and friends are not JS
        regions.append((match.start(2), match.end(2)))
    for match in EVENT_ATTR.finditer(masked):
        group = 1 if match.group(1) is not None else 2
        regions.append((match.start(group), match.end(group)))
    return regions


def check_template(path, problems, warnings):
    text = path.read_text(encoding='utf-8')
    rel = path.relative_to(TEMPLATE_DIR.parent).as_posix()

    masked, spans = mask_django(text)

    literals = []
    for start, end in js_regions(masked):
        literals += [(start + ls, start + le)
                     for ls, le in js_string_spans(masked[start:end])]
    if not literals:
        return

    for start, end, construct in spans:
        if not any(ls < start and end <= le for ls, le in literals):
            continue
        if construct.startswith('{#'):
            continue
        if HAS_ESCAPEJS.search(construct):
            continue
        if TRANS_ASVAR.match(construct):
            continue                   # declares a variable, outputs nothing

        line = text.count('\n', 0, start) + 1
        snippet = ' '.join(construct.split())[:70]

        if TRANS_OUTPUT.match(construct):
            problems.append(
                f'{rel}:{line}: translation reaches a JS string literal '
                f'unescaped — a locale with an apostrophe breaks this whole '
                f'script block. Use "{{% trans \"…\" as v %}}" + '
                f'"{{{{ v|escapejs }}}}".  {snippet}')
        elif construct.startswith('{{'):
            if construct.strip('{} ').strip() in SAFE_VARIABLES:
                continue
            warnings.append(
                f'{rel}:{line}: variable in a JS string literal without '
                f'escapejs. Safe only if it is always numeric or already '
                f'JSON.  {snippet}')


def main():
    if not TEMPLATE_DIR.is_dir():
        sys.exit(f'no templates directory at {TEMPLATE_DIR}')

    problems, warnings = [], []
    templates = sorted(TEMPLATE_DIR.rglob('*.html'))
    for path in templates:
        check_template(path, problems, warnings)

    print(f'Checked {len(templates)} templates for unescaped translations in JavaScript.')

    if problems:
        print(f'\n{len(problems)} ERROR(S):')
        for problem in problems:
            print(f'  {problem}')
    else:
        print('No errors.')

    if warnings and '--quiet' not in sys.argv:
        print(f'\n{len(warnings)} variable(s) to eyeball:')
        for warning in warnings:
            print(f'  {warning}')

    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
