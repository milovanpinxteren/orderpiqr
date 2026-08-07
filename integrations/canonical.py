"""Canonical (platform-neutral) representations exchanged between platform
connectors and the integrations core. Connectors translate platform payloads
into these; nothing platform-specific may leak past this boundary."""

from dataclasses import dataclass, field


@dataclass
class ExternalLine:
    """One order line as reported by the platform."""
    external_variant_id: str
    quantity: int
    # Candidate identifiers for matching against Product.code,
    # keyed by identifier type: {'barcode': ..., 'sku': ..., 'metafield': ...}
    identifiers: dict = field(default_factory=dict)
    title: str = ''
    external_product_id: str = ''


@dataclass
class ExternalOrder:
    """One order as reported by the platform."""
    external_order_id: str
    order_number: str
    lines: list = field(default_factory=list)  # list[ExternalLine]
    note: str = ''
    # open | cancelled | fulfilled_elsewhere
    status: str = 'open'


@dataclass
class ExternalVariant:
    """One product variant as reported by the platform (product sync)."""
    external_variant_id: str
    external_product_id: str = ''
    title: str = ''
    identifiers: dict = field(default_factory=dict)
    inventory_quantity: int | None = None
