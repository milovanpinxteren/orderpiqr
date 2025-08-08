from django.utils.translation import gettext_lazy as _
from django.db import models

from .customers import Customer
from .products import  Product


class Order(models.Model):
    order_id = models.AutoField(primary_key=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    order_code = models.CharField(_("Order Code"), max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(_("Notes"), blank=True, null=True)

    class Meta:
        verbose_name = _("Order")
        verbose_name_plural = _("Orders")

    def __str__(self):
        return self.order_code


class OrderLine(models.Model):
    order = models.ForeignKey(Order, related_name='lines', on_delete=models.CASCADE, verbose_name=_("Order"))
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name=_("Product"))
    quantity = models.PositiveIntegerField(_("Quantity"))

    class Meta:
        verbose_name = _("Order Line")
        verbose_name_plural = _("Order Lines")

    def __str__(self):
        return _("Order %(order)s, Product: %(quantity)s x %(product)s") % {
            "order": self.order.order_code,
            "quantity": self.quantity,
            "product": self.product.description
        }




