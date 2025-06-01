import qrcode
from PIL import Image
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from django.conf import settings
import os


class QRPDFGenerator:

    def generate_multiple(self, orders):
        output_dir = os.path.join(settings.MEDIA_ROOT, "qr_pdfs")
        os.makedirs(output_dir, exist_ok=True)

        filename = "qr_batch_orders.pdf"
        output_path = os.path.join(output_dir, filename)

        c = canvas.Canvas(output_path, pagesize=A4)

        for order in orders:
            lines = [order.order_code]
            for line in order.lines.all():
                lines.append(f"{line.product.code}\t{line.quantity}")
            qr_content = "\n".join(lines)

            qr = qrcode.make(qr_content)
            if not isinstance(qr, Image.Image):
                qr = qr.get_image()

            # Draw QR and label
            c.drawString(100, 800, f"Order: {order.order_code}")
            c.drawInlineImage(qr, 100, 600, width=200, height=200)
            c.showPage()  # Start new page for next order

        c.save()
        return output_path