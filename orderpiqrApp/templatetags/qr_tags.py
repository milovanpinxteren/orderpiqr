import base64
from io import BytesIO

import qrcode
from django import template

register = template.Library()


def _render_qr(content, box_size=10, border=2, error_correction=qrcode.constants.ERROR_CORRECT_L):
    qr = qrcode.QRCode(
        version=1,
        error_correction=error_correction,
        box_size=box_size,
        border=border,
    )
    qr.add_data(content)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return f"data:image/png;base64,{img_str}"


@register.simple_tag
def qr_code_base64(order):
    """
    Generate a QR code for an order and return it as a base64 data URL.
    The QR content matches the format used in the PDF generator.
    """
    lines = [order.order_code]
    for line in order.lines.all():
        lines.append(f"{line.quantity}\t{line.product.code}")
    qr_content = "\n".join(lines)

    return _render_qr(qr_content)


@register.simple_tag
def qr_code_data_url(content, box_size=8):
    """QR for any string — used for login QRs, which are printed and taped up.

    Medium error correction so a smudged or partly covered sheet still scans.
    """
    return _render_qr(
        content, box_size=box_size, border=3,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
