from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models


class Customer(models.Model):
    customer_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    description = models.TextField()

    def __str__(self):
        return self.name

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)



class Product(models.Model):
    product_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=255)
    description = models.TextField()
    location = models.IntegerField()
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.description

class Device(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)  # Link Device to User
    device_id = models.AutoField(primary_key=True)
    device_fingerprint = models.CharField(max_length=255, unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField()
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    last_login = models.DateTimeField()
    lists_picked = models.IntegerField()

    def __str__(self):
        return self.name


class PickList(models.Model):
    picklist_id = models.AutoField(primary_key=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    picklist_code = models.CharField(max_length=255, null=True, blank=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)  # Link PickList to a Device
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)
    pick_time = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    time_taken = models.DurationField(null=True, blank=True)  # Total time taken for the full pick list
    successful = models.BooleanField(null=True, blank=True)  # Was the picklist successful?
    notes = models.TextField(blank=True, null=True)  # Optional field for any notes about the picklist

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update the `lists_picked` field after saving the PickList
        self.device.lists_picked = self.device.picklist_set.count()
        self.device.save()

    def __str__(self):
        return f"PickList {self.picklist_id} for Device {self.device.name}"

class ProductPick(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)  # The product being picked
    picklist = models.ForeignKey(PickList, related_name='products', on_delete=models.CASCADE)  # Link the product to a picklist
    quantity = models.IntegerField()  # Quantity of this product picked
    time_taken = models.DurationField(null=True, blank=True)  # Time taken for this specific product
    successful = models.BooleanField(null=True, blank=True)  # Was this specific product picked successfully?
    notes = models.TextField(blank=True, null=True)  # Optional field for additional information

    def __str__(self):
        return f"Pick of {self.product} in PickList {self.picklist.picklist_id}"




