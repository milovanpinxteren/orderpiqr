from django.utils.translation import gettext_lazy as _
from django.db import models
from .customers import Customer
from .orders import Order
from .devices import Device
from .products import Product


class PickList(models.Model):
    picklist_id = models.AutoField(primary_key=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Source Order"))
    picklist_code = models.CharField(_("Picklist Code"), max_length=255, null=True, blank=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name=_("Device"))
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now_add=True)
    pick_started = models.BooleanField(_("Pick Started"), null=True, blank=True)
    pick_time = models.DateTimeField(_("Pick Time"), auto_now_add=True, null=True, blank=True)
    time_taken = models.DurationField(_("Time Taken"), null=True, blank=True)
    successful = models.BooleanField(_("Successful"), null=True, blank=True)
    notes = models.TextField(_("Notes"), blank=True, null=True)

    class Meta:
        verbose_name = _("Pick List")
        verbose_name_plural = _("Pick Lists")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.device.lists_picked = self.device.picklist_set.count()
        self.device.save()

    def __str__(self):
        return _("PickList %(id)s for Device %(device)s") % {
            "id": self.picklist_id,
            "device": self.device.name
        }





class ProductPick(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name=_("Product"))
    picklist = models.ForeignKey(PickList, related_name='products', on_delete=models.CASCADE,
                                 verbose_name=_("Pick List"))
    quantity = models.IntegerField(_("Quantity"))
    time_taken = models.DurationField(_("Time Taken"), null=True, blank=True)
    successful = models.BooleanField(_("Successful"), null=True, blank=True)
    notes = models.TextField(_("Notes"), blank=True, null=True)

    class Meta:
        verbose_name = _("Product Pick")
        verbose_name_plural = _("Product Picks")

    def __str__(self):
        return _("Pick of %(product)s in PickList %(picklist_id)s") % {
            "product": self.product,
            "picklist_id": self.picklist.picklist_id
        }

