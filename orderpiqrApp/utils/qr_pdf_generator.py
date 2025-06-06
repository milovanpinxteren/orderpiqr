import qrcode
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from django.conf import settings
import os
from django.utils.translation import gettext_lazy as _
import uuid

class QRPDFGenerator:

    def generate_multiple(self, orders):
        output_dir = os.path.join(settings.MEDIA_ROOT, "qr_pdfs")
        os.makedirs(output_dir, exist_ok=True)

        filename = f"qr_batch_orders_{uuid.uuid4().hex}.pdf"
        output_path = os.path.join(output_dir, filename)

        page_width, page_height = A4
        c = canvas.Canvas(output_path, pagesize=A4)

        for order in orders:
            # Generate QR content
            lines = [order.order_code]
            for line in order.lines.all():
                lines.append(f"{line.quantity}\t{line.product.code}")
            qr_content = "\n".join(lines)

            qr = qrcode.make(qr_content)
            if not isinstance(qr, Image.Image):
                qr = qr.get_image()

            # Header: Order Code
            c.setFont("Helvetica-Bold", 28)
            header_text = f"Order: {order.order_code}"
            text_width = c.stringWidth(header_text, "Helvetica-Bold", 28)
            header_x = (page_width - text_width) / 2
            header_y = page_height - 80
            c.drawString(header_x, header_y, header_text)

            # Centered QR Code
            qr_width = qr_height = 100 * mm
            qr_x = (page_width - qr_width) / 2
            qr_y = header_y - qr_height  # extra space below header
            c.drawInlineImage(qr, qr_x, qr_y, width=qr_width, height=qr_height)

            # Product Table
            data = [[_("Code"), _("Name"), _("Location"), _("Quantity")]]
            for line in order.lines.all():
                data.append([
                    line.product.code,
                    line.product.description,
                    line.product.location,
                    line.quantity
                ])

            table = Table(data, colWidths=[100, 300, 100])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ]))

            table.wrapOn(c, page_width, 100)
            table.drawOn(c, 40, 40)  # 40mm margin from bottom and left

            c.showPage()

        c.save()
        return filename
