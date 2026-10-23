from collections import Counter
from datetime import timedelta, timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
import json
from django.views.decorators.http import require_GET, require_POST
from orderpiqrApp.models import Device, Order, PickList, Product, ProductPick, ScanEvent
from orderpiqrApp.utils.build_id import get_build_id
from django.utils.dateparse import parse_datetime
from orderpiqrApp.utils.devices import (
    get_customer,
    register_device,
    resolve_device,
    resolve_device_unauthenticated,
    stamp_device_context,
    touch_device,
)
from orderpiqrApp.utils.inventory import decrement_inventory_for_picklist
from orderpiqrApp.utils.products import resolve_product
from orderpiqrApp.utils.scan_events import log_scan_event

# How long a picklist lock survives its holder going silent. Device.last_login
# is stamped on every pick, so a live picker refreshes this continuously; only
# a device that has stopped talking to us loses its claim.
STALE_LOCK_AFTER = timedelta(minutes=10)


def _resolve_device(request, device_fingerprint):
    """Fetch the device for this fingerprint.

    An authenticated request resolves within the user's own customer. Without a
    session the fingerprint is all we have, and it may be registered for several
    customers — that is unresolvable, so it errors instead of guessing.
    Returns (device, error_response) — both can be None (device not found).
    """
    if request.user.is_authenticated:
        customer = get_customer(request.user)
        if customer is None:
            return None, None
        return resolve_device(request, payload={'deviceFingerprint': device_fingerprint},
                              customer=customer, touch=False), None

    device, ambiguous = resolve_device_unauthenticated(device_fingerprint)
    if ambiguous:
        return None, JsonResponse({
            'status': 'error',
            'message': _('This device is registered for multiple companies. Please log in.')
        }, status=409)
    return device, None


def _parse_client_ts(value):
    """Device-clock timestamp from a queued event, or None.

    A phone's clock can be wrong or deliberately set far ahead; a timestamp
    outside a sane window around now is dropped rather than stored, so it can
    never drag a dashboard's time axis off scale.
    """
    if not value:
        return None
    try:
        parsed = parse_datetime(str(value))
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, dt_timezone.utc)
        now = timezone.now()
        if not (now - timedelta(days=7) <= parsed <= now + timedelta(minutes=5)):
            return None
        return parsed
    except (ValueError, TypeError, OverflowError):
        return None


@require_GET
def client_version(request):
    """Current client build id, polled by the long-lived scan page.

    The scan page is a PWA pickers leave open for days; it compares this
    against the build id it was rendered with and reloads itself (at a safe
    moment) when they differ. Public: the id is a hash of public static files.
    """
    return JsonResponse({'buildId': get_build_id()})


@require_GET
def service_worker(request):
    """The app-shell service worker, rendered rather than served as a static
    file so its cache name carries the current build id.

    A static serviceWorker.js can't see server state, and a cache name that
    never changes would mean every phone keeps a pre-cache from before the
    last deploy forever — the fetch handler inside only ever reads from
    CACHE_NAME, so a new name on every deploy is what makes 'activate' throw
    the stale one away and repopulate it. Cache-Control: no-cache so the
    browser re-checks the script itself on every registration update, rather
    than caching the rendering of the previous deploy for a day.
    """
    response = render(request, 'serviceWorker.js', {
        'cache_name': 'orderpiqr-shell-' + get_build_id(),
    }, content_type='application/javascript')
    response['Cache-Control'] = 'no-cache'
    return response


@require_POST
def scan_event(request):
    """Fire-and-forget pick-flow health logging from the picker client.

    POST /orderpiqr/scan-event with JSON {eventType, scannedCode, picklistCode,
    message, deviceFingerprint, reason, severity, buildId, clientTs, displayMode}.
    Responds {'status': 'ok'} whether or not anything was stored — the endpoint
    must not leak device/customer existence, and it must never create a write
    surface for unauthenticated callers beyond resolvable devices.
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    event_type = data.get('eventType')
    valid_types = {key for key, _label in ScanEvent.EVENT_TYPES}
    if event_type not in valid_types:
        return JsonResponse({'status': 'error', 'message': 'Invalid eventType'}, status=400)

    device_fingerprint = data.get('deviceFingerprint', '')
    device, device_error = _resolve_device(request, device_fingerprint)
    if device_error:
        # Ambiguous fingerprint: don't guess a tenant, and don't tell the
        # caller anything either — this endpoint is fire-and-forget.
        return JsonResponse({'status': 'ok'})

    if device is not None:
        customer = device.customer
    elif request.user.is_authenticated:
        customer = get_customer(request.user)
    else:
        customer = None

    if customer is None:
        # Unresolvable device and no authenticated customer: swallow silently.
        return JsonResponse({'status': 'ok'})

    stamp_device_context(device, request, payload=data)

    log_scan_event(
        customer,
        device,
        event_type,
        scanned_code=data.get('scannedCode') or '',
        picklist_code=data.get('picklistCode') or '',
        message=data.get('message') or '',
        reason=data.get('reason') or '',
        severity=data.get('severity'),
        build_id=data.get('buildId') or '',
        client_ts=_parse_client_ts(data.get('clientTs')),
    )
    return JsonResponse({'status': 'ok'})


@require_POST
def scan_picklist(request):
    # Parse JSON
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    picklist = data.get('picklist', [])
    device_fingerprint = data.get('deviceFingerprint', '')
    order_id = data.get('orderID', None)

    # Validate required fields
    if not order_id:
        return JsonResponse({'status': 'error', 'message': 'orderID is required'}, status=400)

    if not device_fingerprint:
        return JsonResponse({'status': 'error', 'message': 'deviceFingerprint is required'}, status=400)

    if not picklist:
        return JsonResponse({'status': 'error', 'message': 'picklist is empty'}, status=400)

    local_time = timezone.localtime(timezone.now())

    # Fetch or create device
    device, device_error = _resolve_device(request, device_fingerprint)
    if device_error:
        return device_error
    if device:
        # Update last_login on activity
        touch_device(device, local_time)
        # Once per list, not once per pick: these values barely ever change.
        stamp_device_context(device, request, payload=data)
    else:
        if not request.user.is_authenticated:
            # The picker is about to be sent back to the login screen. Attribute
            # it to whatever tenant the fingerprint alone can resolve — often
            # nothing, which is precisely why this bounce was invisible before.
            orphan, ambiguous = resolve_device_unauthenticated(device_fingerprint)
            if orphan is not None and not ambiguous:
                log_scan_event(orphan.customer, orphan, 'auth_bounce',
                               picklist_code=order_id, reason='session_lost',
                               message='Scanned a list with no session — sent back to login')
            return JsonResponse({
                'status': 'error',
                'message': _('Device not found and user not authenticated')
            }, status=401)

        # Register this device for the picker's own customer. An existing row
        # for the same fingerprint under another customer is left untouched.
        device, _created = register_device(
            request,
            name=f"Auto-created device ({local_time.strftime('%Y-%m-%d %H:%M')})",
            fingerprint=device_fingerprint,
        )
        if device is None:
            return JsonResponse({
                'status': 'error',
                'message': _('User has no customer profile')
            }, status=400)

    # Process picklist in a transaction
    try:
        with transaction.atomic():
            # Check if there's a queued Order for this order_id
            order = Order.objects.select_for_update().filter(
                order_code=order_id,
                customer=device.customer
            ).first()

            # If order exists and is queued, lock it
            if order:
                if order.status == 'in_progress':
                    # Only block when a *different* device holds the active
                    # picklist. The same device re-scanning its own order is a
                    # restart (phone held steady over the QR, or the app
                    # reloaded mid-pick) and falls through to the restart
                    # logic below.
                    # Matched on picklist_code (unique per customer), not the
                    # order FK — a picklist that predates the queue claim may
                    # have order=None.
                    holders = list(PickList.objects.filter(
                        picklist_code=order_id,
                        customer=device.customer,
                        pick_started=True,
                        successful__isnull=True,
                    ).exclude(device=device).select_related('device'))
                    if holders:
                        # A device identity is only a UUID in localStorage, so a
                        # picker whose storage was evicted comes back as "another
                        # device" and gets locked out of their own list with no
                        # way forward. Hand the list over when the holder has
                        # gone quiet: the restart path below preserves every
                        # successful pick, so a takeover never loses work.
                        now = timezone.now()
                        last_seen = max(h.device.last_login for h in holders)
                        if last_seen > now - STALE_LOCK_AFTER:
                            # The ScanEvent copy stays English: it is a stored
                            # diagnostic the health page aggregates, so it must
                            # not depend on the picker's language.
                            log_scan_event(
                                device.customer, device, 'picklist_rejected',
                                picklist_code=order_id,
                                message='This order is already being picked by another device')
                            return JsonResponse({'status': 'error', 'message': _(
                                'This order is already being picked by another device'
                            )}, status=409)

                        held_by = ', '.join(sorted(
                            (h.device.name or f'device {h.device.pk}').strip() for h in holders))
                        idle_minutes = int((now - last_seen).total_seconds() // 60)
                        log_scan_event(
                            device.customer, device, 'lock_takeover',
                            picklist_code=order_id,
                            message=(f"Took over a stale lock held by {held_by} "
                                     f"(idle {idle_minutes}m); picks already recorded are preserved"))
                elif order.status == 'completed':
                    log_scan_event(device.customer, device, 'picklist_rejected',
                                   picklist_code=order_id,
                                   message='This order has already been completed')
                    return JsonResponse({'status': 'error', 'message': _(
                        'This order has already been completed')}, status=409)
                elif order.status == 'queued':
                    # Lock the order by setting status to in_progress
                    order.status = 'in_progress'
                    order.save(update_fields=['status'])

            try:
                pick_list = PickList.objects.select_for_update().get(
                    picklist_code=order_id,
                    customer=device.customer
                )
                pick_list.device = device
                pick_list.updated_at = local_time
                pick_list.pick_started = True
                new_note = f"Restarted by device {device.name} at {local_time.strftime('%Y-%m-%d %H:%M')}"
                pick_list.notes = (pick_list.notes or "") + "\n" + new_note
                pick_list.save()

                # A restart must not erase recorded work: deleting everything
                # here turned every accidental or panic re-scan (e.g. after a
                # stop-the-line overlay) into a wiped list. Pending rows are
                # rebuilt below; successful rows survive and count against the
                # re-scanned list's quantities.
                ProductPick.objects.filter(picklist=pick_list).exclude(successful=True).delete()
                preserved = Counter(
                    ProductPick.objects.filter(picklist=pick_list, successful=True)
                    .values_list('product_id', flat=True))
                created = False

            except PickList.DoesNotExist:
                pick_list = PickList.objects.create(
                    picklist_code=order_id,
                    customer=device.customer,
                    device=device,
                    updated_at=local_time,
                    pick_started=True,
                    order=order  # Link to order if it exists
                )
                preserved = Counter()
                created = True

            # Original product handling
            already_picked = {}
            for product_code in picklist:
                product = resolve_product(device.customer, product_code)
                if not product:
                    # Raising (not returning) matters: it rolls back the
                    # transaction, so the order lock and half-built picklist
                    # don't survive a list we refused.
                    raise Product.DoesNotExist(product_code)
                if preserved[product.pk] > 0:
                    # This unit was already picked before the restart; tell
                    # the client so it drops it from the list on screen.
                    preserved[product.pk] -= 1
                    already_picked[product.code] = already_picked.get(product.code, 0) + 1
                    continue
                ProductPick.objects.create(
                    product=product,
                    picklist=pick_list,
                    quantity=1,
                )

    except Product.DoesNotExist as exc:
        missing_code = exc.args[0] if exc.args else '?'
        log_scan_event(device.customer, device, 'picklist_rejected',
                       scanned_code=missing_code, picklist_code=order_id,
                       message=f"Unknown product code '{missing_code}'. "
                               "Add it to your products and scan the list again.")
        return JsonResponse({'status': 'error', 'message': _(
            "Unknown product code '%(code)s'. "
            "Add it to your products and scan the list again."
        ) % {'code': missing_code}}, status=404)
    except IntegrityError as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Database integrity error: {str(e)}'
        }, status=409)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Unexpected error: {str(e)}'
        }, status=500)

    return JsonResponse({
        'status': 'ok',
        'message': _('Picklist processed successfully'),
        'created': created,
        'picklist_id': pick_list.picklist_id,
        'product_count': len(picklist),
        # Units kept from before a restart, keyed by primary product code.
        'already_picked': already_picked,
    })


def _client_pick_id(payload):
    """The client's id for this pick operation, or '' when it sent none.

    Trimmed to the column width so an oversized or junk value can never turn a
    retry into a 500 — an unrecognisable id simply means no replay protection.
    """
    return str(payload.get("pickId") or "").strip()[:64]


def _duplicate_pick_row(picklist, pick_id):
    """The row this pick id already marked on this picklist, or None.

    The id is stamped on every row an operation marks, so one hit means the
    whole operation (single or bulk) already landed.
    """
    if not pick_id:
        return None
    return (ProductPick.objects.filter(picklist=picklist, client_pick_id=pick_id)
            .select_related("product").order_by("id").first())


def product_pick(request):
    payload = json.loads(request.body.decode("utf-8"))
    order_id = payload.get("orderID")
    product_code = payload.get("productCode")
    device_fp = payload.get("deviceFingerprint")
    successful = bool(payload.get("successful", True))
    manual_override = bool(payload.get("manualOverride", False))
    time_taken_ms = payload.get("timeTakenMs")
    pick_id = _client_pick_id(payload)
    scanned_at = payload.get("scannedAt") or timezone.now().isoformat()

    device, device_error = _resolve_device(request, device_fp)
    if device_error:
        return device_error
    if not device:
        return JsonResponse({"status": "error", "message": _("Device not found with given fingerprint")}, status=404)
    # Update last_login on activity
    touch_device(device)

    if manual_override:
        # Logged before any lookup can fail: an override is a picker telling
        # us scanning didn't work, and that signal must survive even when the
        # pick itself cannot be recorded (every override was silently lost
        # for two weeks because this log sat behind the picklist 404).
        log_scan_event(device.customer, device, 'manual_override',
                       scanned_code=product_code, picklist_code=order_id,
                       message="Pick confirmed manually instead of by scan")

    picklist = (PickList.objects.filter(picklist_code=order_id, customer=device.customer, device=device)
                .select_related("customer", "device")
                .first())
    if not picklist:
        log_scan_event(device.customer, device, 'sync_error',
                       scanned_code=product_code, picklist_code=order_id,
                       message=f"Pick registered but no picklist '{order_id}' exists for this device")
        # error_code lets the client stop the line: without it every further
        # scan of this dead list is silently lost the same way.
        return JsonResponse({"status": "error", "error_code": "picklist_not_found",
                             "message": _("PickList not found for device/customer")}, status=404)

    # A retried pick must not consume a second row. Answered before the product
    # lookup and before any write: this call already succeeded once, so the only
    # honest reply is the original one.
    already = _duplicate_pick_row(picklist, pick_id)
    if already is not None:
        return JsonResponse({
            "status": "ok",
            "duplicate": True,
            "picklist_code": picklist.picklist_code,
            "product_code": already.product.code,
            "updated_productpick_id": already.id,
            "remaining_for_product": ProductPick.objects.filter(
                picklist=picklist, product=already.product, successful__isnull=True).count(),
        }, status=200)

    try:
        product = resolve_product(device.customer, product_code)
        if not product:
            raise Product.DoesNotExist()
    except Product.DoesNotExist:
        log_scan_event(device.customer, device, 'sync_error',
                       scanned_code=product_code, picklist_code=order_id,
                       message=f"Pick registered but product '{product_code}' does not exist for this customer")
        return JsonResponse({"status": "error", "message": _("Product not found")}, status=404)

    # Find the next unpicked row for this product in this picklist
    qs = ProductPick.objects.filter(picklist=picklist, product=product).order_by("id")
    pp = qs.filter(successful__isnull=True).first() or qs.filter(successful=False).first()
    if not pp:
        # Idempotent: nothing left to update for this product
        return JsonResponse({"status": "noop", "message": _("No pending ProductPick rows for this product.")},
                            status=200, )

    # timeTakenMs is optional, matching the bulk path. A pick that sat in the
    # client's offline queue has no live stopwatch to report, and `int(None)`
    # here used to raise — losing the very pick the retry was meant to save.
    try:
        time_taken = timedelta(milliseconds=int(time_taken_ms)) if time_taken_ms else None
    except (TypeError, ValueError):
        time_taken = None

    # Update fields
    pp.successful = successful
    pp.time_taken = time_taken
    pp.client_pick_id = pick_id

    # Append device/scanned info to notes
    stamp = f"device={device_fp}; scanned_at={scanned_at}"
    pp.notes = f"{pp.notes}\n{stamp}" if pp.notes else stamp

    pp.save(update_fields=["successful", "time_taken", "notes", "client_pick_id"])

    remaining_for_product = qs.filter(successful__isnull=True).count()

    return JsonResponse(
        {
            "status": "ok",
            "picklist_code": picklist.picklist_code,
            "product_code": product.code,
            "updated_productpick_id": pp.id,
            "remaining_for_product": remaining_for_product,
        },
        status=200,
    )


@require_POST
def bulk_product_pick(request):
    payload = json.loads(request.body.decode("utf-8"))
    order_id = payload.get("orderID")
    product_code = payload.get("productCode")
    device_fp = payload.get("deviceFingerprint")
    quantity = payload.get("quantity")
    time_taken_ms = payload.get("timeTakenMs")
    pick_id = _client_pick_id(payload)
    scanned_at = payload.get("scannedAt") or timezone.now().isoformat()

    if not quantity or int(quantity) < 1:
        return JsonResponse({"status": "error", "message": "quantity must be at least 1"}, status=400)

    quantity = int(quantity)
    manual_override = bool(payload.get("manualOverride", False))

    device, device_error = _resolve_device(request, device_fp)
    if device_error:
        return device_error
    if not device:
        return JsonResponse({"status": "error", "message": _("Device not found")}, status=404)
    touch_device(device)

    if manual_override:
        # Same contract as product_pick: logged before any lookup can fail. This
        # is the high-volume override path — "All N taken" after a triple-tap on
        # an unscannable line — and it was counted as zero, so every override
        # figure we have under-reports the products that cannot be scanned.
        log_scan_event(device.customer, device, 'manual_override',
                       scanned_code=product_code, picklist_code=order_id,
                       message=f"{quantity} units confirmed manually instead of by scan")

    picklist = (PickList.objects.filter(picklist_code=order_id, customer=device.customer, device=device)
                .select_related("customer", "device")
                .first())
    if not picklist:
        # Without this the bulk path's stop-the-line 404 was only ever recorded
        # by the client, i.e. never when the phone was offline.
        log_scan_event(device.customer, device, 'sync_error',
                       scanned_code=product_code, picklist_code=order_id,
                       message=f"Bulk pick of {quantity} registered but no picklist "
                               f"'{order_id}' exists for this device")
        return JsonResponse({"status": "error", "error_code": "picklist_not_found",
                             "message": _("PickList not found")}, status=404)

    # Checked before the availability test, which is what a replay would trip
    # over: the rows this operation marked are no longer unpicked, so a retry
    # would otherwise be rejected with "only N unpicked rows available".
    already = _duplicate_pick_row(picklist, pick_id)
    if already is not None:
        return JsonResponse({
            "status": "ok",
            "duplicate": True,
            "picklist_code": picklist.picklist_code,
            "product_code": already.product.code,
            "updated_count": ProductPick.objects.filter(
                picklist=picklist, client_pick_id=pick_id).count(),
            "remaining_for_product": ProductPick.objects.filter(
                picklist=picklist, product=already.product, successful__isnull=True).count(),
        }, status=200)

    product = resolve_product(device.customer, product_code)
    if not product:
        return JsonResponse({"status": "error", "message": _("Product not found")}, status=404)

    qs = ProductPick.objects.filter(
        picklist=picklist, product=product, successful__isnull=True
    ).order_by("id")

    available = qs.count()
    if quantity > available:
        return JsonResponse({
            "status": "error",
            "message": _("Requested %(wanted)s but only %(available)s unpicked rows available")
                       % {"wanted": quantity, "available": available}
        }, status=400)

    time_taken = timedelta(milliseconds=int(time_taken_ms)) if time_taken_ms else timedelta(0)
    stamp = f"device={device_fp}; scanned_at={scanned_at}; bulk_pick=true"

    with transaction.atomic():
        picks_to_update = list(qs.select_for_update()[:quantity])
        for i, pp in enumerate(picks_to_update):
            pp.successful = True
            pp.time_taken = time_taken if i == 0 else timedelta(0)
            pp.notes = f"{pp.notes}\n{stamp}" if pp.notes else stamp
            # Every row this operation marks carries the id, so the duplicate
            # check above finds it no matter which row it looks at.
            pp.client_pick_id = pick_id
            pp.save(update_fields=["successful", "time_taken", "notes", "client_pick_id"])

    remaining = qs.filter(successful__isnull=True).count()

    return JsonResponse({
        "status": "ok",
        "picklist_code": picklist.picklist_code,
        "product_code": product.code,
        "updated_count": quantity,
        "remaining_for_product": remaining,
    }, status=200)


def complete_picklist(request):
    if request.method == 'POST':
        try:
            # Parse the incoming JSON request
            data = json.loads(request.body)
            device_fingerprint = data.get('deviceFingerprint', '')
            order_id = data.get('orderID', None)  # Assuming orderID is passed in the request
            # Fetch the device using the fingerprint
            device, device_error = _resolve_device(request, device_fingerprint)
            if device_error:
                return device_error
            if not device:
                raise Device.DoesNotExist()
            # Update last_login on activity
            touch_device(device)
            picklist = PickList.objects.filter(picklist_code=order_id, customer=device.customer,
                                               device=device).first()
            if picklist and picklist.successful:
                # Already completed by this device. A retried completion used to
                # fall through and run the whole finish again: inventory
                # decremented twice, the platform write-back queued twice, and
                # time_taken stretched to "now minus pick_time" every time.
                return JsonResponse({
                    'status': 'ok',
                    'duplicate': True,
                    'message': _('Picklist processed successfully'),
                })
            elif picklist:
                now = timezone.localtime(timezone.now())  # now in local time
                pick_time = timezone.localtime(picklist.pick_time)  # ensure pick_time is also local
                picklist.time_taken = now - pick_time
                picklist.successful = True  # or set based on some logic
                picklist.save()

                # Decrement inventory for picked products (if inventory management enabled)
                decrement_inventory_for_picklist(picklist, request.user)

                # Mark the linked order as completed if it exists
                if picklist.order:
                    picklist.order.status = 'completed'
                    picklist.order.completed_at = now
                    picklist.order.save(update_fields=['status', 'completed_at'])

                    # Queue platform write-backs (Shopify fulfillment etc.)
                    from integrations.services.events import order_completed
                    order_completed(picklist.order)
            else:
                # No picklist means the scan was never registered (e.g. the
                # server rejected it at scan time). Saying "ok" here would let
                # the picker walk away believing the work was recorded.
                log_scan_event(device.customer, device, 'sync_error',
                               picklist_code=order_id,
                               message='Completion reported but no picklist exists for this device and order')
                return JsonResponse({
                    'status': 'error',
                    'error_code': 'picklist_not_found',
                    'message': _('No picklist found for this device and order')
                }, status=404)

            return JsonResponse({'status': 'ok', 'message': _('Picklist processed successfully')})

        except Device.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': _('Device not found with given fingerprint')}, status=404)
        except Product.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': _('Product not found for one of the product codes')},
                                status=404)
        except Exception as e:

            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)
