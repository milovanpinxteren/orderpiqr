

## 🌍 Internationalization (i18n)

This project supports multiple languages using Django’s built-in translation system — for both templates and JavaScript.

### ✅ Supported Languages

Languages are defined in `settings.py`:

```python
LANGUAGES = [
    ('nl', 'Nederlands'),
    ('en', 'English'),
    ('de', 'Deutsch'),
    ('fr', 'Français'),
    ('ro', 'Română'),
    ('pl', 'Polski'),
    ('uk', 'Українська'),
]
```

---

## ➕ Adding a New Language

1. **Add the language to `settings.py`:**

   ```python
   LANGUAGES = [
       # existing entries...
       ('it', 'Italiano'),  # ← example for Italian
   ]
   ```

2. **Create translation files:**

   ```bash
   python manage.py makemessages -l it
   python manage.py makemessages -d djangojs -e js,html -l it
   ```

   Then set the new catalog's `Plural-Forms` header. `makemessages` seeds it
   with the English two-form rule regardless of the language, and a wrong
   header means the language can never inflect a counted noun. Copy the value
   from Django's own catalog for that language:
   `.venv/Lib/site-packages/django/conf/locale/it/LC_MESSAGES/django.po`.
   (This bit was missed for `pl`, `ro` and `uk`, which all shipped with the
   wrong rule.)

3. **Translate the `.po` files:**

   Edit:
   - `locale/it/LC_MESSAGES/django.po`  ← for templates and Python
   - `locale/it/LC_MESSAGES/djangojs.po` ← for JavaScript

4. **Compile the translations:**

   ```bash
   python manage.py compilemessages
   ```

---

## 🔄 Updating All Translations

Run these four steps in order, for **all languages**. The flags are not
optional — see the notes below each one.

```bash
# 1. Templates and Python
python manage.py makemessages -a \
    -i ".venv/*" -i "node_modules/*" -i "staticfiles/*" -i "requirements.txt" -i "qr_pdfs/*"

# 2. JavaScript — note -e js,html
python manage.py makemessages -a -d djangojs -e js,html \
    -i ".venv/*" -i "node_modules/*" -i "staticfiles/*" -i "requirements.txt" -i "qr_pdfs/*"

# 3. Empty the translations msgmerge invented (ALWAYS run this)
python scripts/strip_fuzzy_translations.py

# 4. ...translate the now-empty entries, then check and compile
python scripts/check_translations.py
python manage.py compilemessages
```

**`-e js,html` on the djangojs domain.** By default that domain scans only
`.js`, so the `gettext()` calls inside the `<script>` block of
`templates/shopify/app.html` (and a few in `templates/index.html`) are never
extracted and silently render in English. With the flag they are. xgettext
emits some cosmetic `unterminated string` / `RegExp literal` warnings while
parsing Django template syntax as JavaScript; they are harmless — verified that
the flag adds only the expected msgids and removes none.

**`strip_fuzzy_translations.py`.** Django's `makemessages` does not forward
msgmerge's `--no-fuzzy-matching`, so guessing cannot be switched off. msgmerge
fills every new msgid with the translation of whatever looked similar and marks
it `#, fuzzy`; the guess is routinely a different sentence ("Could not start
sync" came back as "Could not start the camera"). `compilemessages` then drops
fuzzy entries, so the string renders in English while the `.po` looks
translated. The script turns each guess back into an honest empty entry. One
regeneration produced **528** of them.

**`check_translations.py`.** Fails on the mistakes that are objectively wrong
rather than a matter of wording: renamed or dropped placeholders, mismatched
`%%` doubling, mangled HTML, surviving fuzzy flags, empty entries and empty
plural forms, and whitespace that does not match at the edges. It also lists
translations identical to the English for a human to eyeball. Run it before
every compile.

**Commit the `.mo` files.** The Heroku `release` phase runs only `migrate`, so
nothing compiles on deploy — the compiled catalogs ship from git. A `.po` change
without its `.mo` has no effect in production.

**A literal `%` in a `{% trans %}` string is extracted as `%%`.** That is
correct: Django looks up the doubled form and un-escapes it at render time.
Translations must keep the `%%` exactly as the msgid has it.

---

## ✅ Translations Are Verified Before Every Push

A tracked `pre-push` hook refuses the push if the catalogs are broken. **Enable
it once per clone** — `core.hooksPath` is local config and is not cloned:

```bash
git config core.hooksPath .githooks
```

It runs two checks, both of which also run as tests
(`orderpiqrApp/tests/test_translation_catalogs.py`), so CI and anyone running
the suite gets the same guarantee even if the hook is bypassed:

```bash
python scripts/check_translations.py --check-compiled   # catalogs
python scripts/check_template_i18n.py                   # templates
```

`check_translations.py --check-compiled` fails on renamed or dropped
placeholders, mismatched `%%` doubling, mangled HTML, mismatched edge
whitespace, surviving `fuzzy` flags, untranslated entries, empty plural forms,
a wrong `Plural-Forms` header, and a `.mo` that does not match its `.po`. It
also prints two advisory lists for a human to skim: translations identical to
the English, and one translation reused for two different English strings —
the latter being the fingerprint of an accepted msgmerge guess.

`check_template_i18n.py` fails if a `{% trans %}` lands in a JavaScript string
literal without `|escapejs`. `{% trans %}` does **not** autoescape, so a
translation containing an apostrophe terminates the literal and kills the whole
`<script>` block. French did exactly that on six pages in production.

**What this cannot check.** Neither tool can tell that a grammatical, correctly
formatted translation is a translation of the *wrong sentence*. That is how
Romanian shipped `Inactive` as "Activ" and French showed "Aucun produit trouvé"
on a *successful* scan — both from msgmerge guesses someone accepted. After any
`makemessages`, step 3 above is what protects you; read new translations against
their msgids rather than trusting a "0 untranslated" count.

To bypass in a genuine emergency: `git push --no-verify`.

---

## 🧾 Using Translations in Templates and Python

In Django templates:

```django
{% trans "Welcome to Orderpiqr!" %}
```

In Python code:

```python
from django.utils.translation import gettext_lazy as _
title = _("Welcome to Orderpiqr!")
```

---

## 🧪 Using Translations in JavaScript

1. **Load the JavaScript catalog in your template:**

   ```html
   <script src="{% url 'javascript-catalog' %}"></script>
   ```

2. **Access translations in your JS modules:**

   ```js
   const gettext = window.gettext;

   alert(gettext("Order Importance: Enabled"));
   ```

3. **Make sure the strings are wrapped with `gettext()` so they get extracted:**

   ```js
   gettext("Scan successful!");
   ```

---

## 📁 Translation File Locations

| File                       | Purpose                     |
|----------------------------|-----------------------------|
| `django.po`                | Templates + Python views    |
| `djangojs.po`              | JavaScript translations     |

All files are located under:
```
locale/<lang_code>/LC_MESSAGES/
```
