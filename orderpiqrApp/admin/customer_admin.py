from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, DateTimeField, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.timesince import timesince
from django.utils.translation import gettext_lazy as _

from orderpiqrApp.models import (
    Customer, Device, Order, PickList, Product, ProductPick, ScanEvent, UserProfile,
)

#: How far back the "recent" columns look.
ACTIVITY_WINDOW_DAYS = 30


def activity_window_start():
    """Start of the recent-activity window, aligned to local midnight.

    Day-aligned on purpose: the annotation and the link in the same row each
    call this, and a rolling "now" would give them cutoffs milliseconds apart —
    so the number in the column could disagree with the list it links to.
    """
    midnight = timezone.localtime(timezone.now()).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=ACTIVITY_WINDOW_DAYS - 1)


def _count_per_customer(queryset, customer_path='customer'):
    """A scalar count of ``queryset``, correlated to the outer Customer row.

    Subqueries rather than several ``Count()`` aggregates: aggregates over
    different relations in one queryset multiply each other's joins, which
    silently inflates every number on the row.
    """
    grouped = (queryset
               .filter(**{customer_path: OuterRef('pk')})
               .order_by()
               .values(customer_path)
               .annotate(n=Count('pk'))
               .values('n')[:1])
    return Coalesce(Subquery(grouped, output_field=IntegerField()), 0)


class CustomerAdmin(admin.ModelAdmin):
    """The page that answers "how many customers, and are they still picking".

    Every count links into the child changelist filtered to that customer,
    because the question after "how many products does this one have" is always
    "which ones" — and that used to mean paginating and counting by hand.
    """

    list_display = ('name', 'users_count', 'devices_count', 'products_count',
                    'orders_recent', 'picklists_recent', 'lines_picked_recent',
                    'errors_recent', 'last_pick')
    # Only the name opens the customer: the other columns are links of their
    # own, and a row-wide link would nest inside them.
    list_display_links = ('name',)
    search_fields = ['name', 'description']
    ordering = ('name',)

    def get_queryset(self, request):
        """Override queryset to filter by user"""
        queryset = super().get_queryset(request)
        if not request.user.is_superuser:
            if request.user.groups.filter(name='companyadmin').exists():
                user_profile = UserProfile.objects.get(user=request.user)
                # Show only companies linked to the current user
                queryset = queryset.filter(customer_id=user_profile.customer_id)
            else:
                return queryset.none()

        since = activity_window_start()
        return queryset.annotate(
            n_users=_count_per_customer(UserProfile.objects.all()),
            n_devices=_count_per_customer(Device.objects.all()),
            n_devices_active=_count_per_customer(Device.objects.filter(archived=False)),
            n_products=_count_per_customer(Product.objects.filter(active=True)),
            n_orders=_count_per_customer(Order.objects.filter(created_at__gte=since)),
            n_picklists=_count_per_customer(PickList.objects.filter(created_at__gte=since)),
            n_lines_picked=_count_per_customer(
                ProductPick.objects.filter(outcome=ProductPick.Outcome.PICKED,
                                           picklist__created_at__gte=since),
                customer_path='picklist__customer'),
            n_errors=_count_per_customer(
                ScanEvent.objects.filter(severity='error', created_at__gte=since)),
            last_pick_at=Subquery(
                PickList.objects.filter(customer=OuterRef('pk'))
                .order_by('-updated_at').values('updated_at')[:1],
                output_field=DateTimeField()),
        )

    # --- counts, each one a link into the list it counts -------------------

    def _count_link(self, model, params, label):
        url = reverse('admin:%s_%s_changelist'
                      % (model._meta.app_label, model._meta.model_name))
        return format_html('<a href="{}?{}">{}</a>', url, urlencode(params), label)

    def _recent_params(self, obj, **extra):
        return {'customer__customer_id__exact': obj.pk,
                'created_at__gte': activity_window_start().isoformat(),
                **extra}

    def users_count(self, obj):
        return self._count_link(
            UserProfile, {'customer__customer_id__exact': obj.pk}, obj.n_users)
    users_count.short_description = _('Users')
    users_count.admin_order_field = 'n_users'

    def devices_count(self, obj):
        """Active over total: most customers carry a tail of dead phones that
        were archived rather than deleted (picklists cascade off them)."""
        label = '%s / %s' % (obj.n_devices_active, obj.n_devices)
        return self._count_link(
            Device,
            {'customer__customer_id__exact': obj.pk, 'archived__exact': '0'},
            label)
    devices_count.short_description = _('Devices')
    devices_count.admin_order_field = 'n_devices_active'

    def products_count(self, obj):
        return self._count_link(
            Product,
            {'customer__customer_id__exact': obj.pk, 'active__exact': '1'},
            obj.n_products)
    products_count.short_description = _('Products')
    products_count.admin_order_field = 'n_products'

    def orders_recent(self, obj):
        return self._count_link(Order, self._recent_params(obj), obj.n_orders)
    orders_recent.short_description = _('Orders (30d)')
    orders_recent.admin_order_field = 'n_orders'

    def picklists_recent(self, obj):
        return self._count_link(PickList, self._recent_params(obj), obj.n_picklists)
    picklists_recent.short_description = _('Picklists (30d)')
    picklists_recent.admin_order_field = 'n_picklists'

    def lines_picked_recent(self, obj):
        # No link: ProductPick has no changelist of its own.
        return obj.n_lines_picked
    lines_picked_recent.short_description = _('Lines picked (30d)')
    lines_picked_recent.admin_order_field = 'n_lines_picked'

    def errors_recent(self, obj):
        return self._count_link(
            ScanEvent, self._recent_params(obj, severity__exact='error'), obj.n_errors)
    errors_recent.short_description = _('Errors (30d)')
    errors_recent.admin_order_field = 'n_errors'

    def last_pick(self, obj):
        if obj.last_pick_at is None:
            return '—'
        when = timezone.localtime(obj.last_pick_at)
        # timesince() is translated by Django's own catalog, so this needs no
        # string of its own.
        return format_html('{} <span style="color:#666;">({})</span>',
                           date_format(when, 'SHORT_DATE_FORMAT'), timesince(when))
    last_pick.short_description = _('Last pick')
    last_pick.admin_order_field = 'last_pick_at'


admin.site.register(Customer, CustomerAdmin)
