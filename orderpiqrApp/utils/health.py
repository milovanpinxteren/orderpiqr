"""Pick-flow health: shared logic behind the manage health page and the
`/api/health/outcomes/` endpoint. Extracted so the two surfaces can never
drift apart on what "lost" or "the window" means — one answer to "what
actually happened", read from two places.
"""
from datetime import datetime, time, timedelta

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _

from orderpiqrApp.utils.build_id import get_build_id

# The "picked" predicate, used wherever a quantity needs to be split by
# outcome (health counters, R4's per-line aggregates) — one definition so the
# two never compute "picked" two different ways.
PICKED_Q = Q(outcome='picked')


def health_window(params):
    """Resolve the dashboard's time window from a dict-like of query params
    (``request.GET`` or ``request.query_params`` both work).

    Returns (start, end, preset, label). Every number on the page is computed
    from this one window — the previous version filtered the event list by the
    dates but the tiles by a separate rolling 7 days, and ignored the filter
    entirely for stale picklists, so three parts of one screen could describe
    three different periods.

    The default is the last 24 hours rather than the calendar day: shifts run
    into the evening, and the question is almost always asked the next morning.
    """
    now = timezone.now()
    date_from = parse_date(params.get('date_from', '') or '')
    date_to = parse_date(params.get('date_to', '') or '')

    if date_from or date_to:
        start = (timezone.make_aware(datetime.combine(date_from, time.min))
                 if date_from else now - timedelta(days=365))
        end = (timezone.make_aware(datetime.combine(date_to, time.max))
               if date_to else now)
        return start, end, 'custom', _('custom range')

    preset = params.get('preset') or '24h'
    today = timezone.localdate(now)
    if preset == 'today':
        return (timezone.make_aware(datetime.combine(today, time.min)), now,
                'today', _('today'))
    if preset == 'yesterday':
        yesterday = today - timedelta(days=1)
        return (timezone.make_aware(datetime.combine(yesterday, time.min)),
                timezone.make_aware(datetime.combine(yesterday, time.max)),
                'yesterday', _('yesterday'))
    if preset == '7d':
        return now - timedelta(days=7), now, '7d', _('last 7 days')
    if preset == '30d':
        return now - timedelta(days=30), now, '30d', _('last 30 days')
    return now - timedelta(hours=24), now, '24h', _('last 24 hours')


def pick_outcomes(customer, start, end):
    """Did the work actually get recorded? The metric that measures real harm.

    Lines left pending on a list the client marked complete are picks the
    picker made and the server never stored. On 2026-10-11 that was 15.2% of
    all lines; nothing on the health page would have shown it.

    Returns (outcomes, current_build) instead of mutating a view context, so
    both the HTML page and the API can call this the same way.
    """
    # Imported here (not at module level) to avoid a circular import: these
    # models import from orderpiqrApp.utils in turn.
    from orderpiqrApp.models import Device, PickList, ProductPick

    picklists = PickList.objects.filter(
        customer=customer, pick_time__gte=start, pick_time__lte=end, archived=False)

    completed_ids = list(picklists.filter(successful=True).values_list('picklist_id', flat=True))
    total_lines = ProductPick.objects.filter(picklist__in=picklists).count()
    # Union on purpose: completion normally resolves pending rows to lost, but
    # a completion that bypassed the hooks (admin-direct ORM write) leaves them
    # pending — those are lost all the same.
    lost_lines = ProductPick.objects.filter(picklist__in=picklists).filter(
        Q(outcome='lost') | Q(outcome='pending', picklist_id__in=completed_ids)).count()
    short_lines = ProductPick.objects.filter(
        picklist__in=picklists, outcome='short').count()

    restarted = picklists.filter(notes__contains='Restarted by device')

    # Fleet facts for the same window, so every number on the page describes one
    # period. A device still on an older build matters because a half-rolled-out
    # deploy looks exactly like "the app broke this morning".
    devices_used = picklists.exclude(device__isnull=True).values('device_id').distinct().count()
    current_build = get_build_id()
    outcomes = {
        'lists_total': picklists.count(),
        'lists_completed': len(completed_ids),
        'lists_open': picklists.filter(successful__isnull=True).count(),
        'lines_total': total_lines,
        'lines_short': short_lines,
        'lines_lost': lost_lines,
        'lines_lost_pct': round(100.0 * lost_lines / total_lines, 1) if total_lines else 0.0,
        'lists_restarted': restarted.count(),
        'devices_used': devices_used,
        'devices_on_old_build': Device.objects.filter(
            customer=customer, last_login__gte=start, last_login__lte=end,
        ).exclude(last_build_id='').exclude(last_build_id=current_build).count(),
    }
    return outcomes, current_build


def build_pick_aggregates(order_ids):
    """One grouped query: how many units were picked/short/lost per
    (order, product), across that order's non-archived pick lists.

    Returns {(order_id, product_id): {'picked': n, 'short': n, 'lost': n}}.
    Deliberately a single query over all requested orders rather than one
    per order — this is what makes enriching a whole page of order lines
    cheap enough to do unconditionally (see OrderViewSet.get_serializer).
    """
    from orderpiqrApp.models import ProductPick

    rows = (ProductPick.objects
            .filter(picklist__order_id__in=order_ids, picklist__archived=False)
            .values('picklist__order_id', 'product_id')
            .annotate(
                picked=Coalesce(Sum('quantity', filter=PICKED_Q), 0),
                short=Coalesce(Sum('quantity', filter=Q(outcome='short')), 0),
                lost=Coalesce(Sum('quantity', filter=Q(outcome='lost')), 0),
            ))
    return {
        (row['picklist__order_id'], row['product_id']): {
            'picked': row['picked'],
            'short': row['short'],
            'lost': row['lost'],
        }
        for row in rows
    }
