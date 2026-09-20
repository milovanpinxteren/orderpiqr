"""Merchant portal pages for platform integrations and API tokens."""
import logging

from django.contrib import messages
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from drf_hashed_token.models import HashedToken
from integrations.models import Connection
from orderpiqrApp.utils.decorators import company_admin_required
from orderpiqrApp.views.manage_views import get_base_context

logger = logging.getLogger(__name__)


def _customer_connection(request, connection_id):
    customer = get_base_context(request)['customer']
    return get_object_or_404(Connection, pk=connection_id, customer=customer)


# ============================================
# Integrations
# ============================================

@company_admin_required
def integrations_list(request):
    context = get_base_context(request, 'integrations')
    customer = context['customer']
    if not customer:
        messages.error(request, _("No customer profile found for your account."))
        return redirect('login')

    connections = (
        Connection.objects
        .filter(customer=customer)
        .exclude(status='disconnected')
        .annotate(
            orders_synced=Count('order_links', distinct=True),
            products_linked=Count(
                'product_links', distinct=True,
                filter=Q(product_links__product__isnull=False)),
            last_event_at=Max('inbox__received_at'),
        )
        .order_by('platform', '-created_at')
    )
    rows = []
    for connection in connections:
        shop = getattr(connection, 'shopify_shop', None)
        rows.append({
            'connection': connection,
            'config': connection.get_config(),
            'shopify_admin_url': (
                f"https://admin.shopify.com/store/"
                f"{shop.shop_domain.replace('.myshopify.com', '')}/apps"
                if shop else ''),
        })
    context['connections'] = rows
    return render(request, 'manage/integrations/list.html', context)


@company_admin_required
@require_POST
def integrations_connect_woocommerce(request):
    """Issue a pairing key and show it exactly once."""
    from integrations_woocommerce.models import PairingToken
    context = get_base_context(request, 'integrations')
    customer = context['customer']
    if not customer:
        messages.error(request, _("No customer profile found for your account."))
        return redirect('login')

    raw_key, token = PairingToken.issue(customer)
    context['pairing_key'] = raw_key
    context['expires_at'] = token.expires_at
    return render(request, 'manage/integrations/pairing_key.html', context)


@company_admin_required
@require_POST
def integration_toggle(request, connection_id):
    """Pause an active connection or resume a paused one."""
    connection = _customer_connection(request, connection_id)
    if connection.status == 'active':
        connection.status = 'paused'
        messages.success(request, _("Integration paused. Incoming orders are "
                                    "on hold until you resume it."))
    elif connection.status == 'paused':
        connection.status = 'active'
        messages.success(request, _("Integration resumed."))
    connection.save(update_fields=['status'])
    return redirect('manage_integrations')


@company_admin_required
@require_POST
def integration_disconnect(request, connection_id):
    connection = _customer_connection(request, connection_id)
    connection.status = 'disconnected'
    connection.save(update_fields=['status'])
    if connection.platform == 'woocommerce':
        # Best effort: stop the store from delivering webhooks to us.
        try:
            from integrations_woocommerce import services
            services.remove_webhooks(connection.woocommerce_store)
        except Exception:
            logger.info("Webhook cleanup failed for connection %s", connection.pk)
    messages.success(request, _("Integration disconnected."))
    return redirect('manage_integrations')


@company_admin_required
def integration_config(request, connection_id):
    """Edit the platform-neutral sync settings of a connection."""
    connection = _customer_connection(request, connection_id)
    if connection.platform == 'shopify':
        return redirect('manage_integrations')  # managed from the Shopify app

    if request.method == 'POST':
        config = dict(connection.config or {})
        config['auto_queue'] = 'auto_queue' in request.POST
        config['fulfill_on_complete'] = 'fulfill_on_complete' in request.POST
        fulfill_status = request.POST.get('fulfill_status', '').strip()[:64]
        if fulfill_status:
            config['fulfill_status'] = fulfill_status
        else:
            config.pop('fulfill_status', None)
        connection.config = config
        connection.save(update_fields=['config', 'updated_at'])
        messages.success(request, _("Integration settings saved."))
        return redirect('manage_integrations')

    context = get_base_context(request, 'integrations')
    context['connection'] = connection
    context['config'] = connection.get_config()
    return render(request, 'manage/integrations/config.html', context)


# ============================================
# API tokens
# ============================================

def _customer_tokens(customer):
    return (HashedToken.objects
            .filter(user__userprofile__customer=customer)
            .select_related('user')
            .order_by('-created'))


@company_admin_required
def api_tokens(request):
    """Self-service API tokens for the customer's users (one live and one
    test token per user; see drf_hashed_token)."""
    context = get_base_context(request, 'api_tokens')
    customer = context['customer']
    if not customer:
        messages.error(request, _("No customer profile found for your account."))
        return redirect('login')

    new_token = None
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            stage = request.POST.get('stage', HashedToken.TokenStage.LIVE)
            if stage not in HashedToken.TokenStage.values:
                stage = HashedToken.TokenStage.LIVE
            # One token per user+stage: regenerating replaces the old one.
            HashedToken.objects.filter(user=request.user, stage=stage).delete()
            raw_token, key_hash = HashedToken.generate_token()
            token = HashedToken.objects.create(
                user=request.user, key_hash=key_hash, stage=stage)
            new_token = f"{token.get_stage_display()}_{raw_token}"
            messages.success(request, _(
                "API token created. Copy it now – it will not be shown again."))
        elif action == 'revoke':
            deleted, _unused = (_customer_tokens(customer)
                                .filter(key_hash=request.POST.get('key_hash', ''))
                                .delete())
            if deleted:
                messages.success(request, _("API token revoked."))

    context['tokens'] = _customer_tokens(customer)
    context['new_token'] = new_token
    context['stages'] = HashedToken.TokenStage.choices
    return render(request, 'manage/settings/api_tokens.html', context)
