from django.utils.translation import gettext_lazy as _
from django.db import models

from .customers import Customer


class Product(models.Model):
    product_id = models.AutoField(primary_key=True)
    code = models.CharField(_("Product Code"), max_length=255)
    description = models.TextField(_("Description"))
    location = models.CharField(_("Location"), max_length=50)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    active = models.BooleanField(default=True, verbose_name=_("Active"))

    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")

    def __str__(self):
        return self.description
