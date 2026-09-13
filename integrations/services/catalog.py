"""Full-catalog product sync, platform-neutral: walks connector.fetch_variants()
and resolves every variant against the customer's products. Long-running —
must only run in the worker (via SyncJob), never inside a web request."""

import logging

from integrations.canonical import ExternalLine
from integrations.models import ProductLink, SyncJob
from integrations.services.intake import _auto_create_product, _clip, resolve_line

logger = logging.getLogger(__name__)


def sync_products(connection, job=None):
    """Walk the platform catalog and resolve every variant against the
    customer's products using the connection's identifier chain. Under the
    auto_create policy, unmatched variants become new products (this is how
    a fresh install imports the catalog). Returns (linked, unresolved).

    When a SyncJob is passed (worker path), progress counters are flushed to
    it periodically so the console can show a live progress bar."""
    connector = connection.get_connector()
    config = connection.get_config()
    auto_create = config['unknown_product_policy'] == 'auto_create'
    linked = 0
    unresolved = 0
    processed = 0

    if job is not None:
        try:
            job.total = connector.count_variants()
        except Exception:
            logger.exception("Variant count failed for connection %s", connection.pk)
        job.save(update_fields=['total'])

    def flush_progress(force=False):
        if job is not None and (force or processed % 100 == 0):
            job.processed = processed
            job.linked = linked
            job.unresolved = unresolved
            job.save(update_fields=['processed', 'linked', 'unresolved'])

    for variant in connector.fetch_variants():
        processed += 1
        flush_progress()
        if ProductLink.objects.filter(
            connection=connection,
            external_variant_id=variant.external_variant_id,
            locked=True,
        ).exists():
            linked += 1
            continue
        line = ExternalLine(
            external_variant_id=variant.external_variant_id,
            external_product_id=variant.external_product_id,
            quantity=0,
            title=variant.title,
            identifiers=variant.identifiers,
            location=variant.location,
        )
        product = resolve_line(connection, line, config)
        if product is None and auto_create and any(
                str(v).strip() for v in (variant.identifiers or {}).values()):
            product = _auto_create_product(connection, line, config)
        if product is not None:
            location = _clip(variant.location, 50)
            if location and product.location != location:
                # Location metafield configured -> platform is source of truth
                product.location = location
                product.save(update_fields=['location'])
            linked += 1
        else:
            unresolved += 1
            # Record the unresolved variant so the console can list it.
            ProductLink.objects.update_or_create(
                connection=connection,
                external_variant_id=variant.external_variant_id,
                defaults={
                    'product': None,
                    'external_product_id': variant.external_product_id,
                    'identifier_value': '',
                    'match_method': '',
                    'title': _clip(variant.title, 255),
                },
            )
    flush_progress(force=True)
    logger.info("Product sync for connection %s: %s linked, %s unresolved",
                connection.pk, linked, unresolved)
    return linked, unresolved


def enqueue_product_sync(connection):
    """Queue a product sync for the worker. Reuses an already-queued or
    running job so repeated clicks don't stack syncs. Returns the SyncJob."""
    job = (SyncJob.objects
           .filter(connection=connection, kind='product_sync',
                   status__in=['pending', 'running'])
           .order_by('-created_at')
           .first())
    if job is None:
        job = SyncJob.objects.create(connection=connection, kind='product_sync')
    return job
