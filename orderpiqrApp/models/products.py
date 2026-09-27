from django.core.exceptions import ObjectDoesNotExist, ValidationError
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
    inventory_quantity = models.PositiveIntegerField(
        _("Inventory Quantity"),
        default=0,
        help_text=_("Current stock quantity for this product.")
    )

    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        # Keep the denormalised ProductBarcode.customer in step when a product
        # is moved to another customer (superuser/shell paths) — otherwise the
        # old tenant keeps resolving the alias. A collision with a code the new
        # customer already uses surfaces as an IntegrityError rather than a
        # silent cross-tenant leak.
        old_customer_id = None
        if self.pk is not None:
            old_customer_id = (Product.objects.filter(pk=self.pk)
                               .values_list('customer_id', flat=True).first())
        super().save(*args, **kwargs)
        if old_customer_id is not None and old_customer_id != self.customer_id:
            self.barcodes.update(customer_id=self.customer_id)


class ProductBarcode(models.Model):
    """An alternative scan code for a product.

    Suppliers rotate EANs (new packaging, new batches), so at any moment several
    barcodes can be in physical circulation for the same product. Scans and order
    lines resolve against the primary ``Product.code`` first, then these aliases
    (see ``orderpiqrApp.utils.products.resolve_product``).

    ``customer`` is denormalised from ``product.customer`` so the per-customer
    uniqueness of alias codes can live in a DB constraint. ``Product.code`` itself
    has no unique constraint, so primary-vs-alias collisions are enforced at the
    write surfaces (API serializer, manage views) via ``code_conflict``.
    """
    product = models.ForeignKey(Product, related_name='barcodes', on_delete=models.CASCADE,
                                verbose_name=_("Product"))
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name=_("Customer"),
                                 editable=False)
    code = models.CharField(_("Barcode"), max_length=255)

    class Meta:
        verbose_name = _("Product Barcode")
        verbose_name_plural = _("Product Barcodes")
        constraints = [
            models.UniqueConstraint(
                fields=['customer', 'code'],
                name='unique_barcode_per_customer',
            ),
        ]

    def save(self, *args, **kwargs):
        self.customer = self.product.customer
        super().save(*args, **kwargs)

    def clean(self):
        """Form-level guard (admin inline, model forms): duplicate and
        primary-vs-alias collisions become field errors instead of an
        IntegrityError. ``customer`` is editable=False, so Django's own
        validate_unique skips the (customer, code) constraint. Programmatic
        writes (set_alias_codes/set_primary_code) validate via code_conflict
        at their own call sites instead."""
        try:
            product = self.product
        except ObjectDoesNotExist:
            return  # unsaved parent (new product form): nothing to check against yet
        code = (self.code or '').strip()
        if not code:
            return
        if code == product.code:
            raise ValidationError({'code': _("This barcode is the same as the product's own code.")})
        if Product.objects.filter(customer=product.customer, code=code).exclude(pk=product.pk).exists():
            raise ValidationError({'code': _("'%(code)s' is already another product's primary code.") % {'code': code}})
        if ProductBarcode.objects.filter(customer=product.customer, code=code).exclude(pk=self.pk).exists():
            raise ValidationError({'code': _("Barcode '%(code)s' is already in use.") % {'code': code}})

    def __str__(self):
        return f"{self.code} → {self.product.description}"
