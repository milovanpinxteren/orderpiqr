from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.db import models


class Customer(models.Model):
    customer_id = models.AutoField(primary_key=True)
    name = models.CharField(_("Name"), max_length=255)
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



class Product(models.Model):
    product_id = models.AutoField(primary_key=True)
    code = models.CharField(_("Product Code"), max_length=255)
    description = models.TextField(_("Description"))
    location = models.IntegerField(_("Location"))
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    active = models.BooleanField(default=True, verbose_name=_("Active"))

    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")

    def __str__(self):
        return self.description

class Device(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name=_("User"))
    device_id = models.AutoField(primary_key=True)
    device_fingerprint = models.CharField(_("Device Fingerprint"), max_length=255, unique=True, null=True, blank=True)
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"))
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    last_login = models.DateTimeField(_("Last Login"))
    lists_picked = models.IntegerField(_("Lists Picked"))

    class Meta:
        verbose_name = _("Device")
        verbose_name_plural = _("Devices")

    def __str__(self):
        return self.name


class PickList(models.Model):
    picklist_id = models.AutoField(primary_key=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"))
    picklist_code = models.CharField(_("Picklist Code"), max_length=255, null=True, blank=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name=_("Device"))
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now_add=True)
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
        return f"PickList {self.picklist_id} for Device {self.device.name}"

class ProductPick(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name=_("Product"))
    picklist = models.ForeignKey(PickList, related_name='products', on_delete=models.CASCADE, verbose_name=_("Pick List"))
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




