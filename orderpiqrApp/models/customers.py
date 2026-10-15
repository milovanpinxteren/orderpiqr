from django.utils.translation import gettext_lazy as _, pgettext_lazy
from django.db import models
from django.contrib.auth.models import User


class Customer(models.Model):
    customer_id = models.AutoField(primary_key=True)
    # Translators: label for the name of a customer company (the tenant), not
    # of a person. Polish once translated the shared "Name" msgid as "Imie"
    # (a person's given name), which was wrong here, on devices, and on the
    # printed picklist column — hence the separate contexts.
    name = models.CharField(pgettext_lazy("company", "Name"), max_length=255)
    description = models.TextField(_("Description"))

    class Meta:
        verbose_name = _("Customer")
        verbose_name_plural = _("Customers")

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name=_("User"))
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))

    class Meta:
        verbose_name = _("User Profile")
        verbose_name_plural = _("User Profiles")

    def __str__(self):
        return str(self.user)



