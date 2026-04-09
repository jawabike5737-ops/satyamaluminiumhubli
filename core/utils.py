from django.http import HttpResponse
from django.conf import settings
from django.contrib.staticfiles import finders   # ← ADD THIS
import os
import re
from decimal import Decimal
from datetime import datetime

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ─────────────────────────────────────────────
# CLEAN TEXT
# ─────────────────────────────────────────────
def clean_text(text):
    if not text:
        return ''
    return re.sub(r'[^\w\s,\.\-]', '', str(text))


# ─────────────────────────────────────────────
# FONT LOADER
# ─────────────────────────────────────────────
def _load_fonts(base_dir):
    """Try to register Times New Roman, fallback to DejaVu, then Helvetica."""
    times_regular = os.path.join(base_dir, 'fonts', 'times.ttf')
    times_bold    = os.path.join(base_dir, 'fonts', 'timesbd.ttf')
    times_italic  = os.path.join(base_dir, 'fonts', 'timesi.ttf')

    try:
        if os.path.exists(times_regular) and os.path.exists(times_bold):
            if 'TNR' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('TNR',      times_regular))
                pdfmetrics.registerFont(TTFont('TNR-Bold', times_bold))
                if os.path.exists(times_italic):
                    pdfmetrics.registerFont(TTFont('TNR-Italic', times_italic))
            return 'TNR', 'TNR-Bold', 'TNR-Italic'
    except Exception:
        pass

    # Use the project's static fonts directory to locate DejaVuSans
    dejavu = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'DejaVuSans.ttf')
    try:
        if os.path.exists(dejavu):
            if 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('DejaVu', dejavu))
            return 'DejaVu', 'DejaVu', 'DejaVu'
    except Exception:
        pass

    return 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'


# ─────────────────────────────────────────────
# INR FORMATTER  (Indian comma style)
# ─────────────────────────────────────────────
def format_inr(number):
    try:
        number = float(number)
    except Exception:
        number = 0.0
    s = f"{number:.2f}"
    integer, decimal = s.split('.')
    if len(integer) > 3:
        last3 = integer[-3:]
        rest = list(integer[:-3])
        new_rest = ''
        while len(rest) > 2:
            new_rest = ',' + ''.join(rest[-2:]) + new_rest
            rest = rest[:-2]
        new_rest = ''.join(rest) + new_rest
        integer = new_rest + ',' + last3
    return integer + '.' + decimal


# ─────────────────────────────────────────────
# MAIN PDF GENERATOR
# ─────────────────────────────────────────────
def generate_advance_acknowledgement_pdf(order, quotation, advance_amount):
    BRAND_DARK     = colors.HexColor('#1A1A2E')
    BRAND_ACCENT   = colors.HexColor('#C8972B')
    BRAND_LIGHT    = colors.HexColor('#F5F5F0')
    BRAND_GREEN    = colors.HexColor('#1B6B3A')
    BRAND_GREEN_BG = colors.HexColor('#EAF7EE')
    GREY_BORDER    = colors.HexColor('#CCCCCC')
    WHITE          = colors.white

    font, font_bold, font_italic = _load_fonts(settings.BASE_DIR)
    rupee     = '₹'
    today     = datetime.now().strftime('%d-%m-%Y')
    cust      = quotation.customer
    remaining = Decimal(str(quotation.total)) - Decimal(str(advance_amount))

    filename = f"Acknowledgement_{cust.name}_{today}.pdf"
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=45, rightMargin=45,
        topMargin=35,  bottomMargin=35,
    )

    PAGE_W = A4[0] - 90

    # ── Paragraph styles ──────────────────────
    def S(name, fn, fs, color=BRAND_DARK, leading=None, align=0, bold=False):
        return ParagraphStyle(
            name=name,
            fontName=fn,
            fontSize=fs,
            textColor=color,
            leading=leading or fs * 1.4,
            alignment=align,
        )

    sty_company_name   = S('cn',  font_bold,   22, BRAND_DARK,  28, align=1)
    sty_company_sub    = S('cs',  font,        10, colors.HexColor('#555555'), 14, align=1)
    sty_doc_title      = S('dt',  font_bold,   14, WHITE,       18, align=1)
    sty_section_header = S('sh',  font_bold,   10, WHITE,       14)
    sty_label          = S('lbl', font_bold,   10, BRAND_DARK,  14)
    sty_value          = S('val', font,        10, BRAND_DARK,  14)
    sty_footer         = S('ft',  font_italic,  8, colors.HexColor('#888888'), 12, align=1)
    sty_thankyou       = S('ty',  font_bold,   12, BRAND_GREEN, 16, align=1)
    sty_msg            = S('mg',  font,        10, BRAND_DARK,  15, align=1)

    elements = []

    # ═══════════════════════════════════════════
    # 1.  HEADER — logo + company name centred
    # ═══════════════════════════════════════════

    # ✅ Production-safe logo loading
    logo_path = finders.find('logo.png')
    if not logo_path:
        fallback = os.path.join(settings.BASE_DIR, 'static', 'logo.png')
        if os.path.exists(fallback):
            logo_path = fallback

    logo_img = Image(logo_path, width=0.9*inch, height=0.9*inch) \
               if logo_path else Paragraph('', sty_value)

    company_block = [
        logo_img,
        Paragraph('SATYAM ALUMINIUM', sty_company_name),
        Paragraph('Shop No. 4, Ganesh Plaza, Gokul Road, Hubballi \u2013 580030', sty_company_sub),
        Paragraph('Phone: +91 80737 09478 &nbsp;|&nbsp; Email: satyamaluminiumhubli@gmail.com', sty_company_sub),
        Paragraph('GSTIN: 29ADRP1399D1ZX', sty_company_sub),
    ]

    header_tbl = Table([[item] for item in company_block], colWidths=[PAGE_W])
    header_tbl.setStyle(TableStyle([
        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
        ('LEFTPADDING',  (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_tbl)
    elements.append(Spacer(1, 6))

    # Gold divider
    elements.append(HRFlowable(width='100%', thickness=2.5, color=BRAND_ACCENT, spaceAfter=4))
    elements.append(HRFlowable(width='100%', thickness=0.5, color=BRAND_DARK,   spaceAfter=10))

    # ═══════════════════════════════════════════
    # 2.  DOCUMENT TITLE BANNER
    # ═══════════════════════════════════════════
    title_tbl = Table(
        [[Paragraph('ADVANCE PAYMENT ACKNOWLEDGEMENT', sty_doc_title)]],
        colWidths=[PAGE_W]
    )
    title_tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, -1), BRAND_DARK),
        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING',   (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 10),
        ('LEFTPADDING',  (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('ROUNDEDCORNERS', [4]),
    ]))
    elements.append(title_tbl)
    elements.append(Spacer(1, 16))

    # ═══════════════════════════════════════════
    # 3.  CUSTOMER & ORDER INFO (two columns)
    # ═══════════════════════════════════════════
    def section_header(text):
        t = Table([[Paragraph(text, sty_section_header)]], colWidths=[(PAGE_W / 2) - 6])
        t.setStyle(TableStyle([
            ('BACKGROUND',   (0, 0), (-1, -1), BRAND_ACCENT),
            ('TOPPADDING',   (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
            ('LEFTPADDING',  (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        return t

    def info_row(label, value):
        return [Paragraph(label, sty_label), Paragraph(str(value), sty_value)]

    col_w = (PAGE_W / 2) - 6

    cust_rows = [
        [section_header('CUSTOMER DETAILS'), ''],
        info_row('Name',    cust.name),
        info_row('Phone',   cust.phone),
        info_row('Address', getattr(cust, 'address', '\u2013')),
    ]
    cust_tbl = Table(cust_rows, colWidths=[col_w * 0.42, col_w * 0.58])
    cust_tbl.setStyle(TableStyle([
        ('SPAN',         (0, 0), (1, 0)),
        ('BACKGROUND',   (0, 1), (-1, -1), BRAND_LIGHT),
        ('BOX',          (0, 0), (-1, -1), 0.8, GREY_BORDER),
        ('LINEBELOW',    (0, 1), (-1, -2), 0.4, GREY_BORDER),
        ('TOPPADDING',   (0, 1), (-1, -1), 7),
        ('BOTTOMPADDING',(0, 1), (-1, -1), 7),
        ('LEFTPADDING',  (0, 1), (-1, -1), 10),
        ('RIGHTPADDING', (0, 1), (-1, -1), 10),
        ('TOPPADDING',   (0, 0), (-1, 0), 0),
        ('BOTTOMPADDING',(0, 0), (-1, 0), 0),
        ('LEFTPADDING',  (0, 0), (-1, 0), 0),
        ('RIGHTPADDING', (0, 0), (-1, 0), 0),
    ]))

    order_rows = [
        [section_header('ORDER DETAILS'), ''],
        info_row('Quotation No.', quotation.id),
        info_row('Order No.',     order.id),
        info_row('Date',          today),
        info_row('Order Total',   f'{rupee} {format_inr(quotation.total)}'),
    ]
    order_tbl = Table(order_rows, colWidths=[col_w * 0.45, col_w * 0.55])
    order_tbl.setStyle(TableStyle([
        ('SPAN',         (0, 0), (1, 0)),
        ('BACKGROUND',   (0, 1), (-1, -1), BRAND_LIGHT),
        ('BOX',          (0, 0), (-1, -1), 0.8, GREY_BORDER),
        ('LINEBELOW',    (0, 1), (-1, -2), 0.4, GREY_BORDER),
        ('TOPPADDING',   (0, 1), (-1, -1), 7),
        ('BOTTOMPADDING',(0, 1), (-1, -1), 7),
        ('LEFTPADDING',  (0, 1), (-1, -1), 10),
        ('RIGHTPADDING', (0, 1), (-1, -1), 10),
        ('TOPPADDING',   (0, 0), (-1, 0), 0),
        ('BOTTOMPADDING',(0, 0), (-1, 0), 0),
        ('LEFTPADDING',  (0, 0), (-1, 0), 0),
        ('RIGHTPADDING', (0, 0), (-1, 0), 0),
    ]))

    side_by_side = Table([[cust_tbl, order_tbl]], colWidths=[col_w, col_w], hAlign='LEFT')
    side_by_side.setStyle(TableStyle([
        ('LEFTPADDING',  (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING',   (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 0),
        ('ALIGN',        (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ('RIGHTPADDING', (0, 0), (0, -1), 12),
    ]))
    elements.append(side_by_side)
    elements.append(Spacer(1, 18))

    # ═══════════════════════════════════════════
    # 4.  PAYMENT SUMMARY TABLE
    # ═══════════════════════════════════════════
    pay_header_style = ParagraphStyle(
        'ph', fontName=font_bold, fontSize=10, textColor=WHITE, leading=14
    )
    pay_data = [
        [Paragraph('PAYMENT SUMMARY', pay_header_style), '', ''],
        [
            Paragraph('Description', sty_label),
            Paragraph('Amount',      sty_label),
            Paragraph('Status',      sty_label),
        ],
        [
            Paragraph('Order Total',  sty_value),
            Paragraph(f'{rupee} {format_inr(quotation.total)}', sty_value),
            Paragraph('\u2014', sty_value),
        ],
        [
            Paragraph('Advance Paid', sty_value),
            Paragraph(f'{rupee} {format_inr(advance_amount)}', sty_value),
            Paragraph('Received \u2713', ParagraphStyle(
                'ok', fontName=font_bold, fontSize=10,
                textColor=BRAND_GREEN, leading=14)),
        ],
        [
            Paragraph('Balance Remaining', sty_label),
            Paragraph(f'{rupee} {format_inr(remaining)}',
                      ParagraphStyle('bal', fontName=font_bold, fontSize=11,
                                     textColor=colors.HexColor('#C0392B'), leading=14)),
            Paragraph('Due on delivery', sty_value),
        ],
    ]

    col_a, col_b, col_c = PAGE_W * 0.45, PAGE_W * 0.30, PAGE_W * 0.25
    pay_tbl = Table(pay_data, colWidths=[col_a, col_b, col_c])
    pay_tbl.setStyle(TableStyle([
        ('SPAN',         (0, 0), (2, 0)),
        ('BACKGROUND',   (0, 0), (2, 0), BRAND_DARK),
        ('ALIGN',        (0, 0), (2, 0), 'CENTER'),
        ('TOPPADDING',   (0, 0), (2, 0), 9),
        ('BOTTOMPADDING',(0, 0), (2, 0), 9),
        ('BACKGROUND',   (0, 1), (-1, 1), colors.HexColor('#E8E8E8')),
        ('BACKGROUND',   (0, 2), (-1, 2), WHITE),
        ('BACKGROUND',   (0, 3), (-1, 3), colors.HexColor('#F0FFF4')),
        ('BACKGROUND',   (0, 4), (-1, 4), colors.HexColor('#FFF5F5')),
        ('BOX',          (0, 0), (-1, -1), 0.8, GREY_BORDER),
        ('INNERGRID',    (0, 1), (-1, -1), 0.4, GREY_BORDER),
        ('LINEBELOW',    (0, 0), (-1, 0), 2, BRAND_ACCENT),
        ('TOPPADDING',   (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING',(0, 1), (-1, -1), 8),
        ('LEFTPADDING',  (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(pay_tbl)
    elements.append(Spacer(1, 18))

    # ═══════════════════════════════════════════
    # 5.  CONFIRMATION BOX
    # ═══════════════════════════════════════════
    confirm_data = [
        [Paragraph('Thank you for choosing Satyam Aluminium!', sty_thankyou)],
        [Paragraph(
            f'We have received your advance payment of '
            f'<b>{rupee} {format_inr(advance_amount)}</b> against your order. '
            f'Your order is confirmed and work is currently in progress. '
            f'The remaining balance of <b>{rupee} {format_inr(remaining)}</b> '
            f'is payable as per the terms and conditions.',
            sty_msg
        )],
    ]
    confirm_tbl = Table(confirm_data, colWidths=[PAGE_W])
    confirm_tbl.setStyle(TableStyle([
        ('BOX',          (0, 0), (-1, -1), 1.2, BRAND_GREEN),
        ('LINEBELOW',    (0, 0), (-1, 0), 0.5, BRAND_GREEN),
        ('BACKGROUND',   (0, 0), (-1, -1), BRAND_GREEN_BG),
        ('TOPPADDING',   (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 12),
        ('LEFTPADDING',  (0, 0), (-1, -1), 16),
        ('RIGHTPADDING', (0, 0), (-1, -1), 16),
        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
    ]))
    elements.append(confirm_tbl)
    elements.append(Spacer(1, 22))

    # ═══════════════════════════════════════════
    # 6.  FOOTER
    # ═══════════════════════════════════════════
    elements.append(HRFlowable(
        width='100%', thickness=0.5, color=GREY_BORDER,
        spaceBefore=4, spaceAfter=8
    ))
    elements.append(Paragraph(
        'This is a computer-generated acknowledgement and does not require a physical signature.',
        sty_footer
    ))
    elements.append(Paragraph(
        f'Generated on {today} &nbsp;|&nbsp; Satyam Aluminium, Hubballi',
        sty_footer
    ))

    doc.build(elements)
    return response