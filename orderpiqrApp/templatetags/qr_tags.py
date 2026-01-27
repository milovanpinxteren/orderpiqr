import base64
from io import BytesIO

import qrcode
from django import template

register = template.Library()


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

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(qr_content)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return f"data:image/png;base64,{img_str}"
