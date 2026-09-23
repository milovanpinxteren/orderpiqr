

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
   python manage.py makemessages -d djangojs -l it
   ```

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

To extract and update messages for **all languages**:

```bash
# For templates and Python
python manage.py makemessages -a

# For JavaScript
python manage.py makemessages -a -d djangojs
```

Then compile everything:

```bash
python manage.py compilemessages
```

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
