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
from django.templatetags.static import static
from django.contrib.staticfiles import finders


class QRPDFGenerator:

    def generate_multiple(self, orders):
        output_dir = os.path.join(settings.MEDIA_ROOT, "qr_pdfs")
        os.makedirs(output_dir, exist_ok=True)

        filename = f"orderpiqr_orders_{uuid.uuid4().hex}.pdf"
        output_path = os.path.join(output_dir, filename)

        page_width, page_height = A4
        c = canvas.Canvas(output_path, pagesize=A4)

        for order in orders:
            # Generate QR content
            margin = 20  # points (≈7mm)
            c.setStrokeColor(colors.lightgrey)
            c.setLineWidth(1)
            c.rect(margin, margin, page_width - 2 * margin, page_height - 2 * margin)

            lines = [order.order_code]
            for line in order.lines.all():
                lines.append(f"{line.quantity}\t{line.product.code}")
            qr_content = "\n".join(lines)

            qr = qrcode.make(qr_content)
            if not isinstance(qr, Image.Image):
                qr = qr.get_image()

            # Header: Order Code
            static_relative_path = "orderpiqrApp/img/favicon.png"
            logo_path = finders.find(static_relative_path)

            if logo_path and os.path.exists(logo_path):
                logo_width = 40 * mm
                logo_height = 16 * mm
                logo_x = 10
                logo_y = page_height - logo_height - 50  # 20pt top margin
                c.drawImage(
                    logo_path,
                    logo_x,
                    logo_y,
                    width=logo_width,
                    height=logo_height,
                    preserveAspectRatio=True,
                    mask='auto'  # ✅ ensures transparent background
                )
                header_y = logo_y  # Leave space under logo
            else:
                print(f"⚠️ Logo not found at: {static_relative_path}")
                header_y = page_height - 30

            # Draw Header
            c.setFont("Helvetica-Bold", 28)
            header_text = f"Order: {order.order_code}"
            text_width = c.stringWidth(header_text, "Helvetica-Bold", 28)
            header_x = (page_width - text_width) / 2
            c.drawString(header_x, header_y, header_text)
            header_y -= 10
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

            table = Table(data, colWidths=[95, 250, 90, 60])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
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
