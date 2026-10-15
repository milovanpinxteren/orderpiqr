from django.utils.translation import gettext_lazy as _
from django.db import models
from datetime import date, datetime
import json
import re

class SettingDefinition(models.Model):
    class SettingType(models.TextChoices):
        STRING = 'str', _('String')
        BOOLEAN = 'bool', _('Boolean')
        INTEGER = 'int', _('Integer')
        FLOAT = 'float', _('Float')
        DATE = 'date', _('Date')
        DATETIME = 'datetime', _('DateTime')
        COLOR = 'color', _('Color (HEX)')
        URL = 'url', _('URL')
        IMAGE = 'img', _('Image')
        JSON = 'json', _('JSON')

    key = models.CharField(max_length=100, unique=True, verbose_name=_("Key"),
                           help_text=_("Internal name for this setting (e.g. 'language', 'sort_by_location')."))
    label = models.CharField(max_length=255, verbose_name=_("Label"),
                             help_text=_("Human-readable label shown in admin or forms (e.g. 'Language')."))
    help_text = models.TextField(blank=True, verbose_name=_("Help text"),
                                 help_text=_("Additional description or guidance for this setting."))
    setting_type = models.CharField(max_length=10, choices=SettingType.choices, default=SettingType.STRING,
                                    verbose_name=_("Type"),
                                    help_text=_("The type of this setting (e.g. boolean, integer, string)."))
    default_value = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("Default value"),
                                     help_text=_("Used if customer-specific value is not set."))
    options = models.JSONField(blank=True, null=True, verbose_name=_("Options"),
                               help_text=_("For 'choice' type settings: list of {value, label} options. E.g. [{\"value\": \"original\", \"label\": \"Original order\"}]"))

    def __str__(self):
        return f"{self.label} ({self.key})"

    # label/help_text/options hold English text typed into the database, which
    # makemessages never sees. These pass it through the catalog at render time
    # so the settings page follows the active language; see
    # orderpiqrApp.utils.setting_strings for the catalog entries.
    @property
    def translated_label(self):
        from orderpiqrApp.utils.setting_strings import translate_setting_text
        return translate_setting_text(self.label)

    @property
    def translated_help_text(self):
        from orderpiqrApp.utils.setting_strings import translate_setting_text
        return translate_setting_text(self.help_text)

    @property
    def translated_options(self):
        from orderpiqrApp.utils.setting_strings import translate_setting_options
        return translate_setting_options(self.options)

    def cast_value(self, raw_value):
        if raw_value is None:
            return None

        try:
            match self.setting_type:
                case self.SettingType.BOOLEAN:
                    return str(raw_value).lower() in ('1', 'true', 'yes', 'on')
                case self.SettingType.INTEGER:
                    return int(raw_value)
                case self.SettingType.FLOAT:
                    return float(raw_value)
                case self.SettingType.DATE:
                    return date.fromisoformat(raw_value)
                case self.SettingType.DATETIME:
                    return datetime.fromisoformat(raw_value)
                case self.SettingType.JSON:
                    return json.loads(raw_value)
                case self.SettingType.COLOR:
                    # Simple HEX color validation
                    if re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", raw_value):
                        return raw_value
                    raise ValueError("Invalid HEX color")
                case _:
                    return str(raw_value)
        except Exception:
            return raw_value  # fallback if parsing fails


class CustomerSettingValue(models.Model):
    customer = models.ForeignKey("Customer", on_delete=models.CASCADE, related_name="settings",
                                 verbose_name=_("Customer"))
    definition = models.ForeignKey(SettingDefinition, on_delete=models.CASCADE, related_name="customer_values",
                                   verbose_name=_("Setting"))
    value = models.CharField(max_length=255, verbose_name=_("Value"), help_text=_("The value set for this customer."))

    class Meta:
        unique_together = ("customer", "definition")
        verbose_name = _("Customer setting value")
        verbose_name_plural = _("Customer setting values")

    def __str__(self):
        return f"{self.customer} — {self.definition.key} = {self.value}"