# Add this import at the top for login_required
from django.contrib.auth.decorators import login_required
import logging
logger = logging.getLogger(__name__)
_OPEN_BUFFERS = []



# ================= MEASUREMENT PDF =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from io import BytesIO
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models import Q
from django.views.decorators.http import require_POST
from django.urls import reverse

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, KeepTogether
)

from django.utils.text import get_valid_filename

from .models import Customer, Measurement
from .models import Service, Quotation, QuotationItem, Company
from .utils import to_decimal, format_quantity
import re


def _q_tax_type(q):
    """Return unified tax_type for a quotation instance.

    Prioritise the new `tax_type` field; fall back to legacy `gst_type`.
    Returns one of: 'none', 'gst', 'igst'.
    """
    try:
        tt = getattr(q, 'tax_type', None)
        if tt:
            return tt
    except Exception:
        pass
    # fallback: legacy boolean-like field
    try:
        legacy = getattr(q, 'gst_type', None)
        if legacy == 'with_gst':
            return 'gst'
    except Exception:
        pass
    return 'none'


def strip_dimensions(text):
    """Remove dimension patterns like (6x6), (6 × 6), (6.000 × 5.000) from text."""
    if not text:
        return text
    # Remove anything in parentheses that looks like NxM or N x M with numbers
    try:
        cleaned = re.sub(r"\s*\(\s*\d+(?:\.\d+)?\s*[×xX]\s*\d+(?:\.\d+)?\s*\)\s*", ' ', str(text))
        # also remove stray multiple spaces
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        return cleaned
    except Exception:
        return text

# ── Colour palette (white & grey) ──────────────────────────────
DARK_GREY    = colors.HexColor("#2C2C2C")   # headings, strong text
MID_GREY     = colors.HexColor("#555555")   # body text
LIGHT_GREY   = colors.HexColor("#F2F2F2")   # alternating row / card bg
BORDER_GREY  = colors.HexColor("#CCCCCC")   # all borders
HEADER_BG    = colors.HexColor("#3A3A3A")   # table header bg
ACCENT_GREY  = colors.HexColor("#6C6C6C")   # totals row / accent
WHITE        = colors.HexColor("#FFFFFF")
BANNER_BG    = colors.HexColor("#E8E8E8")   # top page banner

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


# ── Styles ─────────────────────────────────────────────────────
def _styles():
    return {
        "section_head": ParagraphStyle(
            "section_head",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=WHITE,
            alignment=TA_LEFT,
        ),
        "label": ParagraphStyle(
            "label",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            textColor=MID_GREY,
        ),
        "value": ParagraphStyle(
            "value",
            fontName="Helvetica",
            fontSize=8.5,
            textColor=DARK_GREY,
        ),
        "item_name": ParagraphStyle(
            "item_name",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=DARK_GREY,
            spaceBefore=4,
            spaceAfter=2,
        ),
        "item_desc": ParagraphStyle(
            "item_desc",
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=MID_GREY,
            spaceAfter=4,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName="Helvetica",
            fontSize=7,
            textColor=MID_GREY,
            alignment=TA_CENTER,
        ),
    }


# ── Canvas: header banner + footer ────────────────────────────
def _make_canvas_cb(customer, measurement_date):

    def on_page(canvas, doc):
        canvas.saveState()

        # ── Top banner ─────────────────────────────────────────
        banner_h = 26 * mm

        # Light grey banner background
        canvas.setFillColor(BANNER_BG)
        canvas.rect(0, PAGE_H - banner_h, PAGE_W, banner_h, fill=1, stroke=0)

        # Dark top stripe
        canvas.setFillColor(HEADER_BG)
        canvas.rect(0, PAGE_H - 3 * mm, PAGE_W, 3 * mm, fill=1, stroke=0)

        # Company name
        canvas.setFillColor(DARK_GREY)
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawCentredString(PAGE_W / 2, PAGE_H - 13 * mm, "SATYAM PARAS JAYSHREE ASSOCIATES")

        # Tagline
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MID_GREY)
        canvas.drawCentredString(
            PAGE_W / 2, PAGE_H - 19 * mm,
            "Aluminium Works & Fabrication  |  Quality You Can See"
        )

        # Bottom border of banner
        canvas.setStrokeColor(BORDER_GREY)
        canvas.setLineWidth(0.8)
        canvas.line(0, PAGE_H - banner_h, PAGE_W, PAGE_H - banner_h)

        # ── Footer ─────────────────────────────────────────────
        canvas.setStrokeColor(BORDER_GREY)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)

        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MID_GREY)
        canvas.drawString(MARGIN, 10 * mm, f"Customer: {customer.name}")
        canvas.drawCentredString(PAGE_W / 2, 10 * mm, f"Date: {measurement_date}")
        canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, f"Page {doc.page}")

        canvas.restoreState()

    return on_page, on_page


# ── View ───────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.platypus import *
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
@login_required(login_url='/login/')
def measurement_pdf(request, cust_id):

    customer    = get_object_or_404(Customer, id=cust_id)
    measurement = Measurement.objects.filter(customer=customer).order_by('-id').first()

    if not measurement:
        return HttpResponse("No measurements found.", status=404)

    # ── Palette: clean light blue theme ──────────────────────────────────────
    C_HDR_DARK   = colors.HexColor("#1A5FA8")   # deep blue  — header band
    C_HDR_MID    = colors.HexColor("#2B7FD4")   # medium blue — accent
    C_BLUE_LIGHT = colors.HexColor("#E8F4FD")   # light blue  — info bg / title
    C_BLUE_PALE  = colors.HexColor("#F0F8FF")   # faintest blue — alt rows
    C_TBL_HDR    = colors.HexColor("#1A5FA8")   # table header bg
    C_BORDER     = colors.HexColor("#B3D4F0")   # soft blue border
    C_TEXT       = colors.HexColor("#0A0A0A")   # near-black text
    C_MUTED      = colors.HexColor("#3A3A3A")   # dark grey
    C_LABEL      = colors.HexColor("#1A5FA8")   # blue labels
    C_WHITE      = colors.white
    C_HDR_TXT    = colors.HexColor("#FFFFFF")
    C_TOTAL_BG   = colors.HexColor("#D6ECFA")   # light blue total row

    TNR      = "Times-Roman"
    TNR_BOLD = "Times-Bold"
    TNR_ITAL = "Times-Italic"
    SANS     = "Helvetica"
    SANS_B   = "Helvetica-Bold"

    # ── Page geometry ─────────────────────────────────────────────────────────
    PAGE_W, PAGE_H = A4
    MARGIN    = 36
    CONTENT_W = PAGE_W - 2 * MARGIN
    HDR_H     = 90   # canvas-drawn header height

    # ── Canvas callback ───────────────────────────────────────────────────────
    def draw_page(canv, doc):
        canv.saveState()

        # White background
        canv.setFillColor(C_WHITE)
        canv.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

        # Header band
        canv.setFillColor(C_HDR_DARK)
        canv.rect(0, PAGE_H - HDR_H, PAGE_W, HDR_H, fill=1, stroke=0)

        # Angled lighter accent on right
        p = canv.beginPath()
        p.moveTo(PAGE_W * 0.55, PAGE_H - HDR_H)
        p.lineTo(PAGE_W,        PAGE_H - HDR_H)
        p.lineTo(PAGE_W,        PAGE_H)
        p.lineTo(PAGE_W * 0.70, PAGE_H)
        p.close()
        canv.setFillColor(C_HDR_MID)
        canv.drawPath(p, fill=1, stroke=0)

        # Thin stripe below header
        canv.setFillColor(colors.HexColor("#5BB3F0"))
        canv.rect(0, PAGE_H - HDR_H - 3, PAGE_W, 3, fill=1, stroke=0)

        # Company name
        canv.setFont(TNR_BOLD, 22)
        canv.setFillColor(C_HDR_TXT)
        canv.drawCentredString(PAGE_W / 2, PAGE_H - 34, "SATYAM PARAS JAYSHREE ASSOCIATES")

        # Tagline / subtitle
        canv.setFont(TNR_ITAL, 9)
        canv.setFillColor(colors.HexColor("#A8D8F8"))
        canv.drawCentredString(PAGE_W / 2, PAGE_H - 50, "Precision Measurements & Fabrication")

        # Thin divider inside header
        canv.setStrokeColor(colors.HexColor("#4A9FD8"))
        canv.setLineWidth(0.5)
        canv.line(MARGIN, PAGE_H - 58, PAGE_W - MARGIN, PAGE_H - 58)

        # "MEASUREMENT REPORT" label
        canv.setFont(SANS_B, 8.5)
        canv.setFillColor(colors.HexColor("#C8E8FA"))
        canv.drawCentredString(PAGE_W / 2, PAGE_H - 72,
                               f"MEASUREMENT REPORT  —  Customer: {customer.name.upper()}")

        # Left accent bar (content area)
        canv.setFillColor(C_HDR_DARK)
        canv.rect(6, 6, 3.5, PAGE_H - HDR_H - 9, fill=1, stroke=0)

        # Outer border
        canv.setStrokeColor(C_BORDER)
        canv.setLineWidth(0.8)
        canv.rect(6, 6, PAGE_W - 12, PAGE_H - 12, fill=0, stroke=1)

        canv.restoreState()

    # ── Paragraph styles ─────────────────────────────────────────────────────
    def PS(name, **kw):
        return ParagraphStyle(name, **kw)

    s_sec    = PS("Sec",   fontName=SANS_B,  fontSize=8.5,  alignment=TA_LEFT,
                  textColor=C_HDR_DARK, leading=12, spaceBefore=4, spaceAfter=3)
    s_item   = PS("Item",  fontName=SANS_B,  fontSize=9,    alignment=TA_LEFT,
                  textColor=C_TEXT,    leading=13, spaceBefore=6, spaceAfter=2)
    s_label  = PS("Lbl",   fontName=SANS_B,  fontSize=7,    alignment=TA_LEFT,
                  textColor=C_LABEL,   leading=10)
    s_val    = PS("Val",   fontName=SANS,    fontSize=9,    alignment=TA_LEFT,
                  textColor=C_TEXT,    leading=13)
    s_val_r  = PS("ValR",  fontName=SANS,    fontSize=9,    alignment=TA_RIGHT,
                  textColor=C_TEXT,    leading=13)
    s_name   = PS("Name",  fontName=TNR_BOLD, fontSize=11,  alignment=TA_LEFT,
                  textColor=C_TEXT,    leading=14)
    s_footer = PS("Ftr",   fontName=SANS,    fontSize=7,    alignment=TA_CENTER,
                  textColor=C_MUTED,   leading=11)

    def th(txt, align=TA_CENTER):
        return Paragraph(
            f"<font name='{SANS_B}' size='8' color='#FFFFFF'>{txt}</font>",
            PS("TH", alignment=align, leading=11),
        )

    def td(txt, align=TA_CENTER, color="#0A0A0A", bold=False):
        fn = SANS_B if bold else SANS
        return Paragraph(
            f"<font name='{fn}' size='8.5' color='{color}'>{txt}</font>",
            PS("TD", alignment=align, leading=12),
        )

    class ThinRule(Flowable):
        def __init__(self, width, color=C_BORDER, thickness=0.7,
                     space_before=3, space_after=3):
            super().__init__()
            self.width        = width
            self.color        = color
            self.thickness    = thickness
            self.space_before = space_before
            self.space_after  = space_after

        def draw(self):
            self.canv.setStrokeColor(self.color)
            self.canv.setLineWidth(self.thickness)
            self.canv.line(0, self.space_after, self.width, self.space_after)

        def wrap(self, *args):
            return self.width, self.space_before + self.space_after + self.thickness

    # ── Build document ────────────────────────────────────────────────────────
    response = HttpResponse(content_type='application/pdf')
    safe_name = re.sub(r'[^A-Za-z0-9]+', '_', customer.name or 'customer').strip('_')
    response['Content-Disposition'] = f'attachment; filename="Measurement_{safe_name}.pdf"'

    doc = SimpleDocTemplate(
        response, pagesize=A4,
        leftMargin=MARGIN + 4,   # +4 clears the left accent bar
        rightMargin=MARGIN,
        topMargin=HDR_H + 14,
        bottomMargin=34,
    )

    elems = []

    # ── CUSTOMER DETAILS CARD ─────────────────────────────────────────────────
    elems.append(Paragraph("CUSTOMER DETAILS", s_sec))
    elems.append(ThinRule(CONTENT_W, color=C_HDR_DARK, thickness=1.4,
                          space_before=2, space_after=4))

    info_data = [
        [
            [Paragraph("NAME",           s_label), Paragraph(clean_text(customer.name),    s_name)],
            [Paragraph("PHONE",          s_label), Paragraph(clean_text(customer.phone) or "\u2014", s_val)],
        ],
        [
            [Paragraph("ADDRESS",        s_label), Paragraph(clean_text(customer.address) or "\u2014", s_val)],
            [Paragraph("MEASUREMENT ID", s_label), Paragraph(f"# {measurement.id}",        s_val)],
        ],
    ]
    info_tbl = Table(info_data, colWidths=[CONTENT_W * 0.55, CONTENT_W * 0.45])
    info_tbl.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.8, C_BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.6, C_BORDER),
        ("BACKGROUND",    (0, 0), (0,  -1), C_WHITE),
        ("BACKGROUND",    (1, 0), (1,  -1), C_BLUE_LIGHT),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    elems.append(info_tbl)
    elems.append(Spacer(1, 10))

    # ── MEASUREMENT DETAILS ───────────────────────────────────────────────────
    elems.append(Paragraph("MEASUREMENT DETAILS", s_sec))
    elems.append(ThinRule(CONTENT_W, color=C_HDR_DARK, thickness=1.4,
                          space_before=2, space_after=4))

    col_w = [CONTENT_W * f for f in (0.18, 0.18, 0.18, 0.14, 0.18, 0.14)]
    # Columns: Height | Width | Length | Qty | Area | Unit

    items_qs = (
        measurement.items
        .select_related('service')
        .prefetch_related('subitems')
        .all()
    )

    for idx, item in enumerate(items_qs, start=1):
        item_name = (
            item.service.name if item.service
            else (getattr(item, 'custom_item_name', None) or item.description or "—")
        )

        elems.append(Paragraph(f"{idx}.  {item_name}", s_item))

        # Table header row
        rows = [[
            th("Height"), th("Width"), th("Length"),
            th("Qty"),    th("Area"),  th("Unit"),
        ]]

        total_area = Decimal('0')
        unit = getattr(item, 'unit', '') or ''

        for sub in item.subitems.all():
            # Safe value extraction
            h = sub.height   if sub.height   is not None else Decimal('0')
            w = sub.width    if sub.width    is not None else Decimal('0')
            l = sub.length   if sub.length   is not None else Decimal('0')
            q = sub.quantity if sub.quantity is not None else Decimal('1')

            # Area logic: h×w×q  OR  l×q  OR  q
            if h and w:
                area = h * w * q
            elif l:
                area = l * q
            else:
                area = q

            total_area += area

            rows.append([
                td(f"{h:.2f}" if h else "—"),
                td(f"{w:.2f}" if w else "—"),
                td(f"{l:.2f}" if l else "—"),
                td(f"{q:.2f}"),
                td(f"{area:.2f}"),
                td(unit or "—"),
            ])

        # Total row
        rows.append([
            td("", bold=False), td("", bold=False), td("", bold=False),
            td("Total", bold=True, color="#0D3E7A"),
            td(f"{total_area:.2f}", bold=True, color="#0D3E7A"),
            td(unit or "—", color="#0D3E7A"),
        ])

        tbl = Table(rows, colWidths=col_w)

        # Build row-level alternating style commands
        row_styles = [
            # Header
            ("BACKGROUND",    (0, 0), (-1, 0),  C_TBL_HDR),
            ("TOPPADDING",    (0, 0), (-1, 0),  6),
            ("BOTTOMPADDING", (0, 0), (-1, 0),  6),
            # Data rows padding
            ("TOPPADDING",    (0, 1), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
            # Total row
            ("BACKGROUND",    (0, -1), (-1, -1), C_TOTAL_BG),
            ("LINEABOVE",     (0, -1), (-1, -1), 0.8, C_HDR_DARK),
            # Borders
            ("BOX",           (0, 0), (-1, -1),  0.8, C_BORDER),
            ("INNERGRID",     (0, 0), (-1, -1),  0.4, C_BORDER),
            ("ALIGN",         (0, 0), (-1, -1),  "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1),  "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1),  6),
            ("RIGHTPADDING",  (0, 0), (-1, -1),  6),
        ]

        # Alternating row backgrounds for data rows
        for r in range(1, len(rows) - 1):
            bg = C_WHITE if r % 2 == 1 else C_BLUE_PALE
            row_styles.append(("BACKGROUND", (0, r), (-1, r), bg))

        tbl.setStyle(TableStyle(row_styles))
        elems.append(tbl)
        elems.append(Spacer(1, 8))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    elems.append(Spacer(1, 4))
    elems.append(ThinRule(CONTENT_W, color=C_BORDER, thickness=0.5,
                          space_before=0, space_after=4))
    elems.append(Paragraph(
        f"<font color='#1A5FA8'>This document is system-generated and does not "
        f"require a physical signature.</font>  &nbsp;|&nbsp;  "
        f"Measurement ID: #{measurement.id}",
        s_footer,
    ))

    doc.build(elems, onFirstPage=draw_page, onLaterPages=draw_page)
    return response


from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
import re
import os
from datetime import datetime

import openpyxl
from django.conf import settings
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# Register DejaVuSans globally (if available in staticfiles)
FONT_PATH = os.path.join(settings.BASE_DIR, 'staticfiles', 'fonts', 'DejaVuSans.ttf')
try:
    if os.path.exists(FONT_PATH):
        if 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('DejaVuSans', FONT_PATH))
except Exception:
    logger.exception('Failed to register DejaVuSans: %s', FONT_PATH)
from django.contrib.staticfiles import finders
from io import BytesIO
from django.db import transaction
import psutil
import os

from .utils import generate_advance_acknowledgement_pdf, get_ram_usage, to_decimal
from .services import calculate_salary
from .models import (
    Customer, Order, Employee, Attendance, Payment,
    Service, Company, Quotation, QuotationItem, OrderPayment, TermCondition,
    QuotationTerm, Measurement, MeasurementItem, MeasurementSubItem,
)
from .models import PaymentDetails
from .forms import PaymentDetailsForm


def get_service_by_code(request, service_code):
    """Return service data as JSON for AJAX lookups by service_code."""
    try:
        svc = Service.objects.filter(service_code__iexact=service_code).first()
        if not svc:
            return JsonResponse({'success': False, 'error': 'Not found'}, status=404)

        data = {
            'success': True,
            'id': svc.id,
            'service_code': svc.service_code,
            'name': svc.name,
            'description': svc.description,
            'rate': str(svc.default_rate or 0),
            'unit': svc.unit,
            'category': svc.category,
            'image_url': svc.image.url if svc.image else '',
        }
        return JsonResponse(data)
    except Exception as e:
        logger.exception('get_service_by_code error: %s', e)
        return JsonResponse({'success': False, 'error': 'Server error'}, status=500)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, HRFlowable,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ================= CURRENCY FORMATTING =================
def format_inr(number):
    """Format number in Indian numbering system (e.g., 1,01,745.00)"""
    s = f"{to_decimal(number):.2f}"
    parts = s.split(".")
    integer = parts[0]
    decimal = parts[1]

    if len(integer) > 3:
        last3 = integer[-3:]
        rest = integer[:-3]
        rest = list(rest)
        new_rest = ""

        while len(rest) > 2:
            new_rest = "," + "".join(rest[-2:]) + new_rest
            rest = rest[:-2]

        new_rest = "".join(rest) + new_rest
        integer = new_rest + "," + last3

    return integer + "." + decimal


def check_memory():
    """Print current process RSS memory in MB for quick monitoring."""
    try:
        process = psutil.Process(os.getpid())
        mem = process.memory_info().rss / 1024 / 1024
        print(f"RAM Used: {mem:.2f} MB")
    except Exception as e:
        logger.exception('Unhandled exception: %s', e)


# ================= FONT / LOGO HELPERS =================
def _load_unicode_font():
    """Register and return DejaVuSans font for rupee rendering."""
    font_name = 'DejaVuSans'
    candidates = []
    try:
        candidates.append(os.path.join(settings.BASE_DIR, 'fonts', 'DejaVuSans.ttf'))
    except Exception as e:
        logger.exception('Unhandled exception: %s', e)
    candidates += [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    ]
    windir = os.environ.get('WINDIR')
    if windir:
        candidates.append(os.path.join(windir, 'Fonts', 'DejaVuSans.ttf'))

    font_path = None
    for p in candidates:
        if p and os.path.exists(p):
            font_path = p
            break

    registered = pdfmetrics.getRegisteredFontNames()
    if font_path:
        try:
            if font_name not in registered:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
            return font_name, '₹'
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)

    return 'Helvetica', 'Rs.'


def _register_times_new_roman():
    """Attempt to register Times New Roman cross-platform."""
    candidates = []
    windir = os.environ.get('WINDIR')
    if windir:
        candidates += [os.path.join(windir, 'Fonts', x) for x in (
            'Times New Roman.ttf', 'TimesNewRoman.ttf', 'times.ttf', 'timesbd.ttf')]
    candidates += [
        '/Library/Fonts/Times New Roman.ttf',
        '/System/Library/Fonts/Supplemental/Times New Roman.ttf'
    ]
    candidates += [
        '/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSerif.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'
    ]

    for p in candidates:
        try:
            if p and os.path.exists(p):
                name = 'TimesNewRoman'
                if name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(name, p))
                return name
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            continue
    return None


def _load_logo_image(logo_name='logo.png', width=100, height=100, circular=False):
    """Locate logo.png and return a ReportLab Image object."""
    from reportlab.platypus import Image as RLImage, Spacer as RLSpacer
    def _find_logo(logo_name='logo.png'):
        lp = None
        try:
            lp = finders.find(logo_name) if finders else None
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            lp = None
        if not lp:
            candidate = settings.BASE_DIR / 'static' / logo_name
            if candidate.exists():
                lp = str(candidate)
        return lp

    logo_path = _find_logo(logo_name)
    if not logo_path:
        # fallback: try common static filenames
        logo_path = None

    if not logo_path or not os.path.exists(logo_path):
        return RLSpacer(width, height)

    if circular:
        try:
            from PIL import Image as PILImage, ImageDraw
            img = PILImage.open(logo_path).convert('RGBA')
            try:
                size = max(img.size)
                square = PILImage.new('RGBA', (size, size), (255, 255, 255, 0))
                try:
                    offset = ((size - img.width) // 2, (size - img.height) // 2)
                    square.paste(img, offset)
                    mask = PILImage.new('L', (size, size), 0)
                    try:
                        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
                        square.putalpha(mask)
                        buf = BytesIO()
                        square.save(buf, format='PNG')
                        buf.seek(0)
                        try:
                            _OPEN_BUFFERS.append(buf)
                        except Exception:
                            pass
                        return RLImage(buf, width=width, height=height)
                    finally:
                        try:
                            mask.close()
                        except Exception:
                            pass
                finally:
                    try:
                        square.close()
                    except Exception:
                        pass
            finally:
                try:
                    img.close()
                except Exception:
                    pass
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)

    try:
        return RLImage(str(logo_path), width=width, height=height)
    except Exception as e:
        logger.exception('Unhandled exception: %s', e)
        return RLSpacer(width, height)


def clean_text(text):
    if not text:
        return ''
    return re.sub(r'[^\w\s,.\-]', '', text)


# ================= SALARY PDF HELPERS (module-level) =================
GOLD  = colors.HexColor('#B8962E')
DARK  = colors.HexColor('#0D1B2A')
CREAM = colors.HexColor('#F7F4EF')
RULE  = colors.HexColor('#D4C5A0')
RED   = colors.HexColor('#8B1A1A')
GREEN = colors.HexColor('#1A6B2B')
GREY  = colors.HexColor('#777777')
LGREY = colors.HexColor('#888888')
WHITE = colors.white

_FONTS_REGISTERED = False


def _register_fonts():
    global _FONTS_REGISTERED

    if _FONTS_REGISTERED:
        return

    try:
        candidates = []
        windir = os.environ.get('WINDIR')
        if windir:
            candidates += [os.path.join(windir, 'Fonts', x) for x in (
                'DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')]

        # project-local fonts folder
        try:
            candidates.append(str(settings.BASE_DIR / 'fonts' / 'DejaVuSans.ttf'))
            candidates.append(str(settings.BASE_DIR / 'fonts' / 'DejaVuSans-Bold.ttf'))
            candidates.append(str(settings.BASE_DIR / 'static' / 'fonts' / 'DejaVuSans.ttf'))
            candidates.append(str(settings.BASE_DIR / 'static' / 'fonts' / 'DejaVuSans-Bold.ttf'))
        except Exception:
            pass

        # common Unix locations
        candidates += [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        ]

        regular_path = None
        bold_path = None
        for p in candidates:
            try:
                if not p:
                    continue
                if os.path.exists(p):
                    if 'Bold' in os.path.basename(p) or 'bold' in os.path.basename(p):
                        if not bold_path:
                            bold_path = p
                    else:
                        if not regular_path:
                            regular_path = p
            except Exception:
                continue

        # Fallback: try to find any DejaVu file in Windows fonts directory
        if not (regular_path or bold_path):
            try:
                if windir:
                    font_dir = os.path.join(windir, 'Fonts')
                    for fname in ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf'):
                        fp = os.path.join(font_dir, fname)
                        if os.path.exists(fp):
                            if 'Bold' in fname:
                                bold_path = bold_path or fp
                            else:
                                regular_path = regular_path or fp
            except Exception:
                pass

        if regular_path and 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('DejaVuSans', regular_path))

        if bold_path and 'DejaVuSans-Bold' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', bold_path))

    except Exception as e:
        logger.exception('Unhandled exception while registering fonts: %s', e)

    _FONTS_REGISTERED = True


def _get_fonts():
    """Return (data_font, data_bold, rupee_char) after registering TTFs."""
    _register_fonts()
    try:
        pdfmetrics.getFont('DejaVuSans')
        return 'DejaVuSans', 'DejaVuSans-Bold', '₹'
    except Exception as e:
        logger.exception('Unhandled exception: %s', e)
        return 'Helvetica', 'Helvetica-Bold', 'Rs.'


def _ps(name, font, size, align=TA_LEFT, color=None, leading=None):
    if color is None:
        color = DARK
    return ParagraphStyle(
        name, fontName=font, fontSize=size,
        alignment=align, textColor=color,
        leading=leading or round(size * 1.35),
    )


def _section_heading(text, page_w):
    heading = Paragraph(
        f"<font name='DejaVuSans-Bold' size='12' color='#0D1B2A'>{text}</font>",
        _ps('_sh', 'DejaVuSans-Bold', 12, TA_LEFT, DARK),
    )
    return [heading, Spacer(1, 3),
            HRFlowable(width=page_w, thickness=1.2, color=GOLD, spaceAfter=9)]


def _info_cell(label, value, data_font, data_bold):
    return Paragraph(
        f"<font name='{data_bold}' size='7.5' color='#888888'>{label}</font><br/>"
        f"<font name='{data_bold}' size='10' color='#0D1B2A'>{value}</font>",
        _ps(f'_ic_{label}', data_font, 10, TA_LEFT, DARK, 16),
    )


def _fmt(amount, rupee):
    """Return '₹ 1,23,456.00' style string."""
    try:
        val = to_decimal(amount).quantize(Decimal('0.01'))
        s = f"{val:,.2f}"
        return f"{rupee} {s}"
    except Exception as e:
        logger.exception('Unhandled exception: %s', e)
        return f"{rupee} {amount}"


# ================= DASHBOARD =================

def dashboard(request):
    ram = get_ram_usage()
    check_memory()
    recent_orders = list(Order.objects.select_related('customer').order_by('-created_at')[:10])
    return render(request, 'dashboard.html', {
        'customers': Customer.objects.count(),
        'orders': Order.objects.count(),
        'employees': Employee.objects.count(),
        'recent_orders': recent_orders,
        'ram': ram,
    })


# ================= AUTH =================
def login_user(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get('username'),
            password=request.POST.get('password')
        )
        if user:
            login(request, user)
            return redirect('dashboard')
        else:
            return render(request, 'login.html', {
                'error': 'Invalid username or password'
            })
    return render(request, 'login.html')

def logout_user(request):
    logout(request)
    return redirect('login')


# ================= CUSTOMERS =================
@login_required(login_url='/login/')
def customers(request):
    # paginate customers to reduce memory usage
    customer_qs = Customer.objects.only('id', 'name', 'phone', 'address').order_by('-id')
    paginator = Paginator(customer_qs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'customers.html', {
        'data': page_obj.object_list,
        'page_obj': page_obj,
        'total_customers': paginator.count
    })


@login_required(login_url='/login/')
def add_customer(request):
    if request.method == "POST":
        name = request.POST.get('name')
        phone = request.POST.get('phone')
        address = request.POST.get('address')

        if not name or not phone:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': 'Name and Phone are required'})
            return render(request, 'add_customer.html', {'error': 'Name and Phone are required'})

        customer = Customer.objects.create(name=name, phone=phone, address=address)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            # After AJAX add, redirect to create quotation and prefill the new customer
            return JsonResponse({
                'status': 'success',
                'message': 'Customer added successfully',
                'customer': {'id': customer.id, 'name': customer.name, 'phone': customer.phone},
                'redirect': reverse('create_quotation') + '?customer_id=' + str(customer.id)
            })
        return redirect('customers')
    return render(request, 'add_customer.html')


@login_required(login_url='/login/')
def edit_customer(request, id):
    customer = get_object_or_404(Customer, id=id)

    if request.method == "POST":
        customer.name = request.POST.get('name')
        customer.phone = request.POST.get('phone')
        customer.address = request.POST.get('address')
        customer.save()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Customer updated successfully'})
        return redirect('customers')
    return render(request, 'edit_customer.html', {'customer': customer})


@login_required(login_url='/login/')
def delete_customer(request, id):
    customer = get_object_or_404(Customer, id=id)

    if request.method == "POST":
        customer.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Customer deleted successfully'})
        return redirect('customers')
    return render(request, 'confirm_delete.html', {'obj': customer})


@login_required(login_url='/login/')
def example_ajax_form(request):
    return render(request, 'example_ajax_form.html', {
        'customers': Customer.objects.all().order_by('-id')[:50]
    })


@login_required(login_url='/login/')
def take_measurements(request, cust_id):
    customer = get_object_or_404(Customer, id=cust_id)
    return render(request, 'take_measurements.html', {'customer': customer})

@login_required(login_url='/login/')
def save_measurements(request, cust_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    import json
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        logger.exception('Unhandled exception: %s', e)
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    customer = get_object_or_404(Customer, id=cust_id)

    with transaction.atomic():
        m = Measurement.objects.filter(customer=customer).order_by('id').first()
        if not m:
            m = Measurement.objects.create(customer=customer)

        # BUG 4 FIX: Removed unused `existing_items` dead code that was here.

        for item in payload.get('items', []):
            desc = (item.get('description') or 'Item').strip()
            item_type = item.get('item_type') or MeasurementItem.SIZE
            unit = item.get('unit') or 'Sq Ft'

            service = None
            service_id = item.get('service_id')
            if service_id:
                try:
                    service = Service.objects.get(id=int(service_id))
                except Exception:
                    service = None

            custom_name = (item.get('custom_item_name') or '').strip()
            ppu = to_decimal(item.get('price_per_unit') or '0')

            existing_item = None
            try:
                if service:
                    existing_item = m.items.filter(service=service).first()
                else:
                    existing_item = m.items.filter(service__isnull=True, custom_item_name=custom_name).first()
            except Exception:
                existing_item = None

            if existing_item:
                # BUG 1 + 2 FIX: Delete all old subitems and recreate from payload.
                # This replaces the broken append+weak-dedup logic. No more duplicates,
                # no more "6" vs "6.0" false-distinct strings.
                existing_item.subitems.all().delete()

                if ppu and ppu != Decimal('0'):
                    existing_item.rate = ppu
                existing_item.description = desc
                existing_item.item_type = item_type
                existing_item.unit = unit

                total_price = Decimal('0')
                for sub in item.get('subs', []):
                    h_val = sub.get('height') if sub.get('height') not in (None, '') else None
                    w_val = sub.get('width') if sub.get('width') not in (None, '') else None
                    l_val = sub.get('length') if sub.get('length') not in (None, '') else None
                    qty_in = sub.get('quantity') or sub.get('qty') or 1

                    try:
                        qty_dec = to_decimal(qty_in).quantize(Decimal('0.001'))
                    except Exception:
                        try:
                            qty_dec = Decimal(int(qty_in))
                        except Exception:
                            qty_dec = Decimal('1')

                    try:
                        h_dec = to_decimal(h_val) if h_val is not None else None
                    except Exception:
                        h_dec = None
                    try:
                        w_dec = to_decimal(w_val) if w_val is not None else None
                    except Exception:
                        w_dec = None
                    try:
                        l_dec = to_decimal(l_val) if l_val is not None else None
                    except Exception:
                        l_dec = None

                    si = MeasurementSubItem.objects.create(
                        item=existing_item,
                        height=h_dec,
                        width=w_dec,
                        length=l_dec,
                        quantity=qty_dec
                    )

                    try:
                        if si.height is not None and si.width is not None:
                            area_val = si.height * si.width * si.quantity
                        elif si.length is not None:
                            area_val = si.length * si.quantity
                        else:
                            area_val = si.quantity
                    except Exception:
                        area_val = Decimal('0')

                    total_price += (area_val * ppu)

                try:
                    MeasurementItem.objects.filter(id=existing_item.id).update(total=total_price)
                    existing_item.total = total_price
                except Exception:
                    existing_item.total_price = total_price

                existing_item.save()

            else:
                mi = MeasurementItem.objects.create(
                    measurement=m,
                    description=desc,
                    item_type=item_type,
                    unit=unit,
                    service=service,
                    rate=ppu
                )
                if custom_name:
                    mi.custom_item_name = custom_name
                    mi.save()

                total_price = Decimal('0')
                for sub in item.get('subs', []):
                    h_val = sub.get('height') if sub.get('height') not in (None, '') else None
                    w_val = sub.get('width') if sub.get('width') not in (None, '') else None
                    l_val = sub.get('length') if sub.get('length') not in (None, '') else None
                    qty_in = sub.get('quantity') or sub.get('qty') or 1

                    try:
                        qty_dec = to_decimal(qty_in).quantize(Decimal('0.001'))
                    except Exception:
                        try:
                            qty_dec = Decimal(int(qty_in))
                        except Exception:
                            qty_dec = Decimal('1')

                    try:
                        h_dec = to_decimal(h_val) if h_val is not None else None
                    except Exception:
                        h_dec = None
                    try:
                        w_dec = to_decimal(w_val) if w_val is not None else None
                    except Exception:
                        w_dec = None
                    try:
                        l_dec = to_decimal(l_val) if l_val is not None else None
                    except Exception:
                        l_dec = None

                    si = MeasurementSubItem.objects.create(
                        item=mi,
                        height=h_dec,
                        width=w_dec,
                        length=l_dec,
                        quantity=qty_dec
                    )

                    try:
                        if si.height is not None and si.width is not None:
                            area_val = si.height * si.width * si.quantity
                        elif si.length is not None:
                            area_val = si.length * si.quantity
                        else:
                            area_val = si.quantity
                    except Exception:
                        area_val = Decimal('0')

                    total_price += (area_val * ppu)

                try:
                    MeasurementItem.objects.filter(id=mi.id).update(total=total_price)
                    mi.total = total_price
                except Exception:
                    mi.total_price = total_price
                    mi.save()

    # BUG 3 FIX: items_out.append(...) was inside the subitems loop, causing the same
    # measurement item to be appended once per subitem. Moved outside the inner loop.
    items_out = []
    for mi in m.items.select_related('service').prefetch_related('subitems').all():
        subs = []
        for s in mi.subitems.all():
            subs.append({
                'height': str(s.height) if s.height is not None else None,
                'width': str(s.width) if s.width is not None else None,
                'length': str(s.length) if s.length is not None else None,
                'quantity': format_quantity(s.quantity) if s.quantity is not None else '0',
            })

        # Prefer service.description if available; otherwise strip dimension tokens.
        if mi.service and mi.service.description:
            item_description = mi.service.description
        else:
            item_description = strip_dimensions(getattr(mi, 'description', '') or '')

        # items_out.append is now correctly OUTSIDE the subitems loop.
        items_out.append({
            'measurement_item_id': mi.id,
            'service_id': mi.service.id if mi.service else None,
            'service_name': mi.service.name if mi.service else None,
            'service_code': mi.service.service_code if mi.service else None,
            'image_url': mi.service.image.url if mi.service and mi.service.image else '',
            'custom_item_name': getattr(mi, 'custom_item_name', ''),
            'description': item_description,
            'item_type': mi.item_type,
            'quantity': format_quantity(mi.total) if hasattr(mi, 'total') and mi.total else format_quantity(mi.quantity),
            'unit': mi.unit,
            'raw_quantity': format_quantity(mi.quantity),
            'price_per_unit': str(mi.price_per_unit or 0),
            'total_price': str(mi.total_price or 0),
            'subs': subs
        })

    return JsonResponse({
        'ok': True,
        'measurement_id': m.id,
        'measurement': {'id': m.id, 'items': items_out},
        'pdf_url': f'/measurement-pdf/{customer.id}/'
    })


@login_required(login_url='/login/')
def get_measurements_json(request, cust_id):
    customer = get_object_or_404(Customer, id=cust_id)
    # Return the single Measurement record for the customer (earliest created)
    m = Measurement.objects.filter(customer=customer).order_by('id').first()
    if not m:
        return JsonResponse({'items': []})

    out = []
    for mi in m.items.select_related('service').prefetch_related('subitems').all():
        subs_qs = list(mi.subitems.all())

        subs = []
        for s in subs_qs:
            subs.append({
                'height': str(s.height) if s.height is not None else None,
                'width': str(s.width) if s.width is not None else None,
                'length': str(s.length) if s.length is not None else None,
                'quantity': format_quantity(s.quantity) if s.quantity is not None else '0',
            })

        qty_val = Decimal('0')
        raw_qty = Decimal('0')
        for s in subs_qs:
            try:
                qd = to_decimal(s.quantity) if s.quantity is not None else Decimal('0')
                if mi.item_type == MeasurementItem.SIZE:
                    if s.height is None or s.width is None:
                        continue
                    h = to_decimal(s.height)
                    w = to_decimal(s.width)
                    qty_val += (h * w * qd)
                    raw_qty += qd
                elif mi.item_type == MeasurementItem.LENGTH:
                    if s.length is None:
                        continue
                    l = to_decimal(s.length)
                    qty_val += (l * qd)
                    raw_qty += qd
                else:
                    raw_qty += qd
                    qty_val += qd
            except Exception as e:
                logger.exception('Unhandled exception: %s', e)
                continue

        # Prefer the service.description if available; otherwise strip dimension tokens from the stored description
        if mi.service and mi.service.description:
            out_desc = mi.service.description
        else:
            out_desc = strip_dimensions(getattr(mi, 'description', '') or '')

        out.append({
            'measurement_item_id': mi.id,
            'service_id': mi.service.id if mi.service else None,
            'service_name': mi.service.name if mi.service else None,
            'service_code': mi.service.service_code if mi.service else None,
            'image_url': mi.service.image.url if mi.service and mi.service.image else '',
            'custom_item_name': getattr(mi, 'custom_item_name', ''),
            'description': out_desc,
            'item_type': mi.item_type,
            'quantity': format_quantity(qty_val),
            'unit': mi.unit,
            'raw_quantity': format_quantity(raw_qty),
            'price_per_unit': str(mi.price_per_unit or 0),
            'total_price': str(mi.total_price or 0),
            'subs': subs
        })

    return JsonResponse({'items': out})


@login_required(login_url='/login/')
@require_POST
def delete_measurement_item(request):
    """Delete a MeasurementItem by ID (AJAX POST JSON).

    Expects JSON: { "item_id": 123 }
    """
    try:
        import json
        data = {}
        if request.content_type and 'application/json' in (request.content_type or ''):
            data = json.loads(request.body.decode('utf-8') or '{}')
        else:
            data = request.POST.dict()
        item_id = data.get('item_id') or data.get('measurement_item_id')
        if not item_id:
            return JsonResponse({'success': False, 'error': 'item_id required'}, status=400)

        mi = get_object_or_404(MeasurementItem, id=item_id)
        mi.delete()
        return JsonResponse({'success': True})
    except Exception as e:
        logger.exception('delete_measurement_item error: %s', e)
        return JsonResponse({'success': False, 'error': 'Server error'}, status=500)


# ================= SERVICES =================
@login_required(login_url='/login/')
def services(request):
    return render(request, 'services.html')


def services_api(request):
    """Paginated JSON API for services with server-side search and filtering."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    search = request.GET.get('search', '').strip()

    queryset = Service.objects.all()

    if search:
        queryset = queryset.filter(
            service_name__icontains=search
        ).order_by('service_name')
    else:
        queryset = queryset.order_by('service_name')

    # pagination
    paginator = Paginator(queryset, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    data = []
    for service in page_obj.object_list:
        try:
            img = service.image.url if service.image else ''
        except Exception:
            img = ''
        data.append({
            'id': service.id,
            'service_code': service.service_code or '',
            'service_name': service.service_name or service.name,
            'description': service.description or service.service_name or service.name,
            'rate': str(getattr(service, 'price', service.default_rate)),
            'unit': service.unit or 'Sq Ft',
            'image': img,
        })

    return JsonResponse({
        'results': data,
        'total_pages': paginator.num_pages,
        'total_count': paginator.count,
        'current_page': page_obj.number,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
    })


@login_required(login_url='/login/')
def service_search_api(request):
    """Lightweight search endpoint for TomSelect AJAX. Returns a flat list (not paginated)."""
    if not request.user.is_authenticated:
        return JsonResponse([], safe=False)

    q = (request.GET.get('q') or request.GET.get('query') or '').strip()
    queryset = Service.objects.all()
    if q:
        queryset = queryset.filter(
            Q(service_name__icontains=q) | Q(service_code__icontains=q) | Q(description__icontains=q)
        )
    queryset = queryset.order_by('service_name')[:50]
    out = []
    for svc in queryset:
        try:
            img = svc.image.url if svc.image else ''
        except Exception:
            img = ''
        out.append({
            'id': svc.id,
            'service_name': svc.service_name or svc.name,
            'service_code': svc.service_code or '',
            'description': svc.description or svc.service_name or svc.name,
            'rate': str(getattr(svc, 'price', svc.default_rate)),
            'unit': svc.unit or 'Sq Ft',
            'image': img,
        })
    return JsonResponse(out, safe=False)


@login_required(login_url='/login/')
def create_service_api(request):
    """Create a Service via AJAX."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    data = {}
    try:
        import json
        from django.http.request import RawPostDataException
        # Prefer JSON when Content-Type indicates JSON, but avoid re-reading body if already consumed
        if request.content_type and 'application/json' in request.content_type:
            try:
                data = json.loads(request.body.decode('utf-8'))
            except RawPostDataException:
                data = request.POST.dict()
            except Exception as e:
                logger.exception('Unhandled exception reading JSON body: %s', e)
                data = request.POST.dict()
        else:
            data = request.POST.dict()
    except Exception as e:
        logger.exception('Unhandled exception: %s', e)
        data = request.POST.dict()

    service_name = (data.get('service_name') or data.get('name') or '')
    description = (data.get('description') or service_name)
    price_in = data.get('price') or data.get('price_per_unit') or data.get('default_rate') or '0'

    if not service_name:
        return JsonResponse({'error': 'Service name required'}, status=400)

    existing = Service.objects.filter(service_name__iexact=service_name).first() or Service.objects.filter(name__iexact=service_name).first()
    if existing:
        return JsonResponse({
            'id': existing.id,
            'service_name': existing.service_name or existing.name,
            'description': existing.description or existing.service_name or existing.name,
            'price': str(getattr(existing, 'price', existing.default_rate)),
            'image_url': existing.image.url if existing.image else ''
        })

    price = to_decimal(price_in or '0')

    # ensure service_code is unique-ish: auto-generate if missing
    svc_data = {'service_name': service_name, 'name': service_name, 'description': description, 'default_rate': price}
    if data.get('service_code'):
        svc_data['service_code'] = data.get('service_code')

    # If an image was uploaded via multipart/form-data, prefer that
    img = None
    try:
        if request.FILES:
            # accept either 'image' or 'file' or 'service_image'
            img = request.FILES.get('image') or request.FILES.get('file') or request.FILES.get('service_image')
    except Exception:
        img = None

    s = Service.objects.create(**svc_data)
    if img:
        try:
            fname = get_valid_filename(getattr(img, 'name', f'service_{s.id}'))
            s.image.save(fname, img, save=True)
        except Exception as e:
            logger.exception('Failed to save uploaded image for new service (api): %s', e)

    return JsonResponse({'id': s.id, 'name': s.service_name or s.name, 'service_name': s.service_name or s.name, 'description': s.description or s.service_name or s.name, 'price': str(getattr(s, 'price', s.default_rate)), 'image_url': s.image.url if s.image else ''})


@login_required(login_url='/login/')
def update_service_api(request, id):
    """Update service via AJAX (multipart/form-data accepted)."""
    try:
        svc = Service.objects.get(id=id)
    except Service.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    # Accept both JSON and form data
    data = {}
    try:
        import json
        data = json.loads(request.body.decode('utf-8')) if request.body else request.POST.dict()
    except Exception:
        data = request.POST.dict()

    svc_name = (data.get('service_name') or data.get('name') or svc.service_name or svc.name).strip()
    svc.description = data.get('description') or svc.description or svc_name
    price_in = data.get('price') or data.get('default_rate') or None
    if price_in is not None:
        try:
            svc.default_rate = to_decimal(price_in)
        except Exception:
            pass

    # image upload
    try:
        if request.FILES:
            img = request.FILES.get('image') or request.FILES.get('file') or request.FILES.get('service_image')
            if img:
                try:
                    fname = get_valid_filename(getattr(img, 'name', f'service_{svc.id}'))
                    svc.image.save(fname, img, save=False)
                except Exception as e:
                    logger.exception('Failed to attach uploaded image in update_service_api: %s', e)
    except Exception as e:
        logger.exception('Unexpected error in update_service_api image handling: %s', e)

    svc.service_name = svc_name
    svc.name = svc_name
    svc.save()
    return JsonResponse({'id': svc.id, 'service_name': svc.service_name or svc.name, 'description': svc.description or svc.service_name or svc.name, 'price': str(getattr(svc, 'price', svc.default_rate)), 'image_url': svc.image.url if svc.image else ''})


@login_required(login_url='/login/')
def service_details_api(request, id):
    try:
        svc = Service.objects.get(id=id)
    except Service.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
    return JsonResponse({
        'id': svc.id,
        'service_name': svc.service_name or svc.name,
        'description': svc.description or svc.service_name or svc.name,
        'price': str(getattr(svc, 'price', svc.default_rate)),
        'image_url': svc.image.url if svc.image else '',
        'unit': svc.unit or 'Sq Ft'
    })


@login_required(login_url='/login/')
def add_service(request):
    if request.method == "POST":
        service_name = request.POST.get('service_name') or request.POST.get('name')
        desc = request.POST.get('description') or service_name
        price_str = request.POST.get('price')

        if not service_name or not price_str:
            return render(request, 'add_service.html', {'error': 'Service name and Price are required'})

        # Parse price using Decimal(str(...)) to avoid float precision issues
        try:
            price = Decimal(str(price_str).strip().replace(',', '.'))
            price = price.quantize(Decimal('0.01'))
        except InvalidOperation:
            return render(request, 'add_service.html', {'error': 'Invalid price format'})

        # Prepare kwargs and create service record
        svc = Service.objects.create(service_name=service_name, name=service_name, description=desc, default_rate=price)

        # If an image was uploaded as part of the multipart/form-data POST, save it now
        try:
            if request.FILES:
                img = request.FILES.get('image') or request.FILES.get('file') or request.FILES.get('service_image')
                if img:
                    try:
                        fname = get_valid_filename(getattr(img, 'name', f'service_{svc.id}'))
                        svc.image.save(fname, img, save=True)
                    except Exception as e:
                        logger.exception('Failed to save uploaded image for new service (form): %s', e)
        except Exception as e:
            logger.exception('Unexpected error handling uploaded image in add_service: %s', e)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Service added successfully'})
        return redirect('services')
    return render(request, 'add_service.html')


@login_required(login_url='/login/')
def edit_service(request, id):
    service = get_object_or_404(Service, id=id)

    if request.method == "POST":
        service.service_name = request.POST.get('service_name') or request.POST.get('name') or service.service_name
        service.name = service.service_name
        service.description = request.POST.get('description') or service.service_name
        price_str = request.POST.get('price')

        try:
            service.default_rate = Decimal(str(price_str).strip().replace(',', '.')).quantize(Decimal('0.01'))
        except InvalidOperation:
            return render(request, 'edit_service.html', {
                'service': service, 'error': 'Invalid price format'
            })

        # handle uploaded image replacement
        img = request.FILES.get('image')
        if img:
            # remove old image if present
            try:
                if service.image:
                    service.image.delete(save=False)
            except Exception:
                pass
            # assign and let Service.save() optimize and persist
            service.image = img

        service.save()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Service updated successfully'})
        return redirect('services')
    return render(request, 'edit_service.html', {'service': service})


@login_required(login_url='/login/')
def delete_service_image(request, id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    svc = get_object_or_404(Service, id=id)
    try:
        if svc.image:
            svc.image.delete(save=True)
        return JsonResponse({'ok': True})
    except Exception as e:
        logger.exception('delete_service_image error: %s', e)
        return JsonResponse({'error': 'Could not delete image'}, status=500)


@login_required(login_url='/login/')
def delete_service(request, id):
    service = get_object_or_404(Service, id=id)

    if request.method == "POST":
        service.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Service deleted successfully'})
        return redirect('services')
    return render(request, 'confirm_delete.html', {'obj': service})


# ================= QUOTATIONS =================
@login_required(login_url='/login/')
def create_quotation(request):
    customers = Customer.objects.order_by('name')[:50]
    companies = Company.objects.order_by('name')
    quotations = Quotation.objects.all().order_by('-id')[:50]
    terms_qs = TermCondition.objects.order_by('id')[:20]
    default_terms_text = "\n\n".join((t.text for t in terms_qs)) if terms_qs.exists() else ''
    services_qs = Service.objects.order_by('name')

    if request.method == "POST":
        company_id = request.POST.get('company')
        customer_id = request.POST.get('customer')
        # Accept new `tax_type` values: 'none', 'gst', 'igst'
        tax_type = request.POST.get('tax_type', 'none')

        try:
            discount_in = to_decimal(request.POST.get('discount') or '0')
            discount_in = discount_in.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            discount_in = Decimal('0.00')
        if discount_in < 0:
            discount_in = Decimal('0.00')

        descriptions = request.POST.getlist('description')
        quantities = request.POST.getlist('quantity')
        units = request.POST.getlist('unit')
        prices = request.POST.getlist('price')
        service_names = request.POST.getlist('service_name')

        if not customer_id:
            return render(request, 'create_quotation.html', {
                'customers': customers, 'companies': companies, 'quotations': quotations,
                'terms': terms_qs, 'error': 'Select a customer',
                'payment_accounts': PaymentDetails.objects.filter(user=request.user),
                'services': services_qs,
            })

        customer = get_object_or_404(Customer, id=customer_id)
        # keep legacy `gst_type` in sync for older code paths
        legacy_gst = 'with_gst' if tax_type == 'gst' else 'without_gst'
        quotation = Quotation.objects.create(customer=customer, gst_type=legacy_gst, tax_type=tax_type)
        # attach company if provided
        if company_id:
            try:
                quotation.company = Company.objects.get(id=int(company_id))
                quotation.save()
            except Exception as e:
                logger.exception('Unhandled exception: %s', e)
        subtotal = Decimal('0')

        service_ids = request.POST.getlist('service_id')
        widths = request.POST.getlist('width')
        heights = request.POST.getlist('height')
        # collect uploaded row images (all inputs named 'row_image')
        try:
            uploaded_images = request.FILES.getlist('row_image') if request.FILES else []
        except Exception:
            uploaded_images = []

        # Persist rows exactly as posted (do NOT group/merge rows). Each table row
        # becomes one QuotationItem. This prevents accidental merging of windows
        # or measurement subitems and ensures manual quantities remain atomic.
        num_rows = max(len(descriptions), len(quantities), len(prices), len(service_ids), len(service_names))
        for idx in range(num_rows):
            desc = (descriptions[idx] if idx < len(descriptions) else '') or ''
            qty = (quantities[idx] if idx < len(quantities) else '')
            unit = (units[idx] if idx < len(units) else '') or 'Nos'
            price = (prices[idx] if idx < len(prices) else '')
            svc_id = (service_ids[idx] if idx < len(service_ids) else '')
            svc_name = (service_names[idx] if idx < len(service_names) else '') or ''
            width = (widths[idx] if idx < len(widths) else None)
            height = (heights[idx] if idx < len(heights) else None)

            # parse numeric values safely
            try:
                qty_dec = Decimal(str(qty).strip().replace(',', '.'))
            except Exception:
                qty_dec = Decimal('0')
            try:
                price_dec = Decimal(str(price).strip().replace(',', '.'))
            except Exception:
                price_dec = Decimal('0')

            try:
                qty_dec = qty_dec.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
            except Exception:
                pass
            try:
                price_dec = price_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            except Exception:
                pass

            # skip empty rows
            if qty_dec == 0 and price_dec == 0:
                continue

            # determine service object if available
            svc_obj = None
            if svc_id:
                try:
                    svc_obj = Service.objects.filter(id=int(svc_id)).first()
                except Exception:
                    svc_obj = None
            else:
                # if user typed a service name, try find or create service and attach uploaded image
                if svc_name:
                    svc_obj = Service.objects.filter(service_name__iexact=svc_name).first() or Service.objects.filter(name__iexact=svc_name).first()
                    if not svc_obj:
                        try:
                            svc_create_data = {
                                'service_name': svc_name,
                                'name': svc_name,
                                'description': (desc or svc_name),
                                'default_rate': price_dec if isinstance(price_dec, Decimal) else Decimal('0')
                            }
                            svc_obj = Service.objects.create(**svc_create_data)
                            # attach image if uploaded for this row (matching index)
                            try:
                                img = None
                                # Prefer indexed file field name (row_image_0, row_image_1, ...)
                                key = f'row_image_{idx}'
                                if request.FILES and key in request.FILES:
                                    img = request.FILES.get(key)
                                else:
                                    # fallback to legacy getlist('row_image') behaviour
                                    try:
                                        imgs = request.FILES.getlist('row_image') if request.FILES else []
                                    except Exception:
                                        imgs = []
                                    if idx < len(imgs):
                                        img = imgs[idx]

                                if img:
                                    try:
                                        fname = get_valid_filename(getattr(img, 'name', f'service_{svc_obj.id}'))
                                        svc_obj.image.save(fname, img, save=True)
                                    except Exception as e:
                                        logger.exception('Failed to save service image for new service %s: %s', svc_name, e)
                            except Exception as e:
                                logger.exception('Unexpected error while attaching image to service: %s', e)
                        except Exception:
                            svc_obj = None

            # pick description
            raw_desc = desc if desc else (svc_obj.description if svc_obj and svc_obj.description else (svc_name or (svc_obj.name if svc_obj else 'Item')))

            qty_v = qty_dec.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP) if qty_dec is not None else Decimal('0')
            rate_v = price_dec if price_dec and price_dec != Decimal('0') else (svc_obj.default_rate if svc_obj else Decimal('0'))
            try:
                rate_v = rate_v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            except Exception:
                pass
            total_v = (qty_v * rate_v).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            qi_kwargs = {
                'quotation': quotation,
                'description': raw_desc,
                'quantity': qty_v,
                'raw_quantity': qty_v,
                'manual_quantity': False,
                'unit': unit or (svc_obj.unit if svc_obj else 'Nos'),
                'rate': rate_v,
                'total': total_v,
            }
            if svc_obj:
                qi_kwargs['service'] = svc_obj
                qi_kwargs['service_code'] = svc_obj.service_code or ''
            if width not in (None, ''):
                try:
                    qi_kwargs['width'] = Decimal(str(width).replace(',', '.'))
                except Exception:
                    pass
            if height not in (None, ''):
                try:
                    qi_kwargs['height'] = Decimal(str(height).replace(',', '.'))
                except Exception:
                    pass

            QuotationItem.objects.create(**qi_kwargs)
            subtotal += total_v

        # Persist grouped rows (grouping may be empty)
        grouped = {}
        for g in grouped.values():
            # keep quantity precision to 3 decimals (do not force 2-decimal formatting)
            qty_v = g['quantity'].quantize(Decimal('0.001'), rounding=ROUND_HALF_UP) if g['quantity'] is not None else Decimal('0')
            total_v = g['total'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            rate_v = g['price'] if g['price'] and g['price'] != Decimal('0') else (g['service'].default_rate if g.get('service') else Decimal('0'))
            qi_kwargs = {
                'quotation': quotation,
                'description': g['description'],
                'quantity': qty_v,
                'unit': g.get('unit') or 'Nos',
                'rate': rate_v,
                'total': total_v,
            }
            if g.get('service'):
                qi_kwargs['service'] = g['service']
                qi_kwargs['service_code'] = g['service'].service_code or ''
            if g.get('width') is not None:
                qi_kwargs['width'] = g.get('width')
            if g.get('height') is not None:
                qi_kwargs['height'] = g.get('height')

            QuotationItem.objects.create(**qi_kwargs)
            subtotal += total_v

        quotation.subtotal = subtotal
        quotation.discount = discount_in

        # Apply tax based on selected tax_type
        if tax_type == 'gst':
            quotation.cgst = (subtotal * Decimal('0.09')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            quotation.sgst = (subtotal * Decimal('0.09')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total_calc = subtotal + quotation.cgst + quotation.sgst
        elif tax_type == 'igst':
            quotation.cgst = Decimal('0.00')
            quotation.sgst = Decimal('0.00')
            igst_amt = (subtotal * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total_calc = subtotal + igst_amt
        else:
            quotation.cgst = Decimal('0.00')
            quotation.sgst = Decimal('0.00')
            total_calc = subtotal
        total_calc = (total_calc - quotation.discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if total_calc < 0:
            total_calc = Decimal('0.00')
        quotation.total = total_calc

        selected_terms = request.POST.getlist('terms')
        print("DEBUG TERMS:", selected_terms)
        quotation.quotation_terms.all().delete()

        for term_id in selected_terms:
            try:
                order = request.POST.get(f'term_order_{term_id}', '').strip()
                order = int(order) if order else 0
                QuotationTerm.objects.create(
                    quotation=quotation,
                    term_id=int(term_id),
                    order=order
                )
            except Exception as e:
                print("ERROR:", e)

        quotation.custom_terms = request.POST.get('custom_terms') or ''
        tac = request.POST.get('terms_and_conditions', '').strip()
        # Do not store default/global terms text on the quotation record.
        # If user provided custom terms, save them; otherwise keep empty
        # and rely on `quotation.quotation_terms` as the single source of truth.
        quotation.terms_and_conditions = tac if tac else ''
        quotation.save()

        # --- Payment details handling ---
        try:
            include_payment = True if request.POST.get('include_payment_details') in ('on', 'true', '1') else False
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            include_payment = False

        payment_action = request.POST.get('payment_action')

        if include_payment:
            quotation.include_payment_details = True
            sel_id = request.POST.get('selected_payment_id')
            pd_obj = None
            if sel_id:
                try:
                    pd_obj = PaymentDetails.objects.get(id=int(sel_id), user=request.user)
                except Exception as e:
                    logger.exception('Unhandled exception: %s', e)
                    pd_obj = None

            # prepare form data for validation
            form_data = {
                'account_type': request.POST.get('payment_account_type'),
                'account_name': request.POST.get('payment_account_name'),
                'holder_name': request.POST.get('payment_holder_name'),
                'bank_name': request.POST.get('payment_bank_name'),
                'account_number': request.POST.get('payment_account_number'),
                'ifsc_code': request.POST.get('payment_ifsc_code'),
                'branch': request.POST.get('payment_branch'),
                'upi_id': request.POST.get('payment_upi_id'),
                'phone_number': request.POST.get('payment_phone_number'),
                'is_default': True if request.POST.get('make_default') == 'on' else False,
            }

            # Ensure UPI accounts get a sensible account name when none provided
            try:
                if (request.POST.get('payment_account_type') or '').lower() == 'upi':
                    if not (form_data.get('account_name') or '').strip():
                        form_data['account_name'] = request.POST.get('payment_holder_name') or ''
            except Exception:
                # be conservative: do not fail the request on unexpected input
                pass

            form = PaymentDetailsForm(form_data)

            # Update existing
            if payment_action == 'update' and pd_obj:
                if form.is_valid():
                    for k, v in form.cleaned_data.items():
                        setattr(pd_obj, k, v)
                    pd_obj.user = request.user
                    pd_obj.save()
                else:
                    return render(request, 'create_quotation.html', {
                        'customers': customers,
                        'companies': companies,
                        'quotations': quotations,
                        'terms': terms_qs,
                        'terms_default': default_terms_text,
                        'payment_accounts': PaymentDetails.objects.filter(user=request.user),
                        'services': services_qs,
                        'error': form.errors.as_text()
                    })

            # Save new or attach existing
            elif payment_action == 'save' or not pd_obj:
                if form.is_valid():
                    try:
                        new_pd = form.save(commit=False)
                        new_pd.user = request.user
                        new_pd.is_default = form.cleaned_data.get('is_default', False)
                        new_pd.save()
                        if new_pd.is_default:
                            PaymentDetails.objects.filter(user=request.user).exclude(id=new_pd.id).update(is_default=False)
                        pd_obj = new_pd
                    except Exception as e:
                        logger.exception('Unhandled exception: %s', e)
                        pd_obj = None
                else:
                    return render(request, 'create_quotation.html', {
                        'customers': customers,
                        'companies': companies,
                        'quotations': quotations,
                        'terms': terms_qs,
                        'terms_default': default_terms_text,
                        'payment_accounts': PaymentDetails.objects.filter(user=request.user),
                        'services': services_qs,
                        'error': form.errors.as_text()
                    })

            if pd_obj:
                quotation.payment_details = pd_obj
        else:
            quotation.include_payment_details = False

        quotation.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Quotation created', 'quotation_id': quotation.id})
        return redirect('view_quotation', id=quotation.id)

    return render(request, 'create_quotation.html', {
        'customers': customers,
        'companies': companies,
        'quotations': quotations,
        'terms': terms_qs,
        'terms_default': default_terms_text,
        'payment_accounts': PaymentDetails.objects.filter(user=request.user)
    ,
        'services': services_qs,
    })


# ================= VIEW QUOTATION =================
@login_required(login_url='/login/')
def view_quotation(request, id):
    q = get_object_or_404(
        Quotation.objects.select_related('customer').prefetch_related('items', 'quotation_terms__term'),
        id=id
    )
    items = list(q.items.all())
    ordered_terms = list(q.quotation_terms.all())
    # Compute tax breakup for display
    subtotal = getattr(q, 'subtotal', Decimal('0')) or Decimal('0')
    cgst = sgst = igst = Decimal('0')
    tt = _q_tax_type(q)
    if tt == 'gst':
        cgst = (subtotal * Decimal('0.09')).quantize(Decimal('0.01'))
        sgst = (subtotal * Decimal('0.09')).quantize(Decimal('0.01'))
        grand_total = subtotal + cgst + sgst - (getattr(q, 'discount', Decimal('0')) or Decimal('0'))
    elif tt == 'igst':
        igst = (subtotal * Decimal('0.18')).quantize(Decimal('0.01'))
        grand_total = subtotal + igst - (getattr(q, 'discount', Decimal('0')) or Decimal('0'))
    else:
        grand_total = subtotal - (getattr(q, 'discount', Decimal('0')) or Decimal('0'))

    grand_total = grand_total.quantize(Decimal('0.01')) if isinstance(grand_total, Decimal) else Decimal(str(grand_total)).quantize(Decimal('0.01'))

    return render(request, 'view_quotation.html', {
        'q': q,
        'items': items,
        'ordered_terms': ordered_terms,
        'subtotal': subtotal,
        'cgst': cgst,
        'sgst': sgst,
        'igst': igst,
        'grand_total': grand_total,
        'tax_type': tt,
    })


# ================= EDIT QUOTATION =================
@login_required(login_url='/login/')
def edit_quotation(request, id):
    q = get_object_or_404(Quotation.objects.select_related('customer').prefetch_related('items', 'quotation_terms__term'), id=id)
    items = list(q.items.all())
    terms_qs = TermCondition.objects.all()
    default_terms_text = "\n\n".join((t.text for t in terms_qs)) if terms_qs.exists() else ''
    companies = Company.objects.order_by('name')

    if request.method == "POST":
        customer_id = request.POST.get('customer')
        company_id = request.POST.get('company')
        # accept new `tax_type` (none/gst/igst); fall back to legacy `gst_type` if needed
        tax_type = request.POST.get('tax_type', None)
        if not tax_type:
            tax_type = ('gst' if getattr(q, 'gst_type', '') == 'with_gst' else 'none')

        try:
            discount_in = to_decimal(request.POST.get('discount') or '0')
            discount_in = discount_in.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            discount_in = Decimal('0.00')
        if discount_in < 0:
            discount_in = Decimal('0.00')

        descriptions = request.POST.getlist('description')
        quantities = request.POST.getlist('quantity')
        units = request.POST.getlist('unit')
        prices = request.POST.getlist('price')

        if customer_id:
            try:
                q.customer = get_object_or_404(Customer, id=customer_id)
            except Exception as e:
                logger.exception('Unhandled exception: %s', e)
        # update company if provided
        if company_id:
            try:
                q.company = Company.objects.get(id=int(company_id))
            except Exception as e:
                logger.exception('Unhandled exception: %s', e)

        # Delete existing items via queryset (items is a list, re-fetch queryset)
        q.items.all().delete()
        subtotal = Decimal('0')

        # Persist edited rows exactly as posted (do NOT group/merge rows). This preserves
        # per-row identity and prevents accidental aggregation of measurements.
        service_ids = request.POST.getlist('service_id')
        service_names = request.POST.getlist('service_name')
        num_rows = max(len(descriptions), len(quantities), len(units), len(prices), len(service_ids), len(service_names))
        for idx in range(num_rows):
            desc = (descriptions[idx] if idx < len(descriptions) else '') or ''
            qty = (quantities[idx] if idx < len(quantities) else '')
            unit = (units[idx] if idx < len(units) else '') or 'Nos'
            price = (prices[idx] if idx < len(prices) else '')
            svc_id = (service_ids[idx] if idx < len(service_ids) else '')
            svc_name = (service_names[idx] if idx < len(service_names) else '') or ''

            try:
                qty_dec = Decimal(str(qty).strip().replace(',', '.'))
            except Exception:
                qty_dec = Decimal('0')
            try:
                price_dec = Decimal(str(price).strip().replace(',', '.'))
            except Exception:
                price_dec = Decimal('0')

            try:
                qty_dec = qty_dec.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
            except Exception:
                pass
            try:
                price_dec = price_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            except Exception:
                pass

            if qty_dec == 0 and price_dec == 0:
                continue

            svc_obj = None
            if svc_id:
                try:
                    svc_obj = Service.objects.filter(id=int(svc_id)).first()
                except Exception:
                    svc_obj = None
            else:
                if svc_name:
                    svc_obj = Service.objects.filter(service_name__iexact=svc_name).first() or Service.objects.filter(name__iexact=svc_name).first()
                    if not svc_obj:
                        try:
                            svc_obj = Service.objects.create(name=svc_name, service_name=svc_name, default_rate=price_dec)
                            # attach image if uploaded for this row (matching index)
                            try:
                                img = None
                                key = f'row_image_{idx}'
                                if request.FILES and key in request.FILES:
                                    img = request.FILES.get(key)
                                else:
                                    try:
                                        imgs = request.FILES.getlist('row_image') if request.FILES else []
                                    except Exception:
                                        imgs = []
                                    if idx < len(imgs):
                                        img = imgs[idx]

                                if img:
                                    try:
                                        fname = get_valid_filename(getattr(img, 'name', f'service_{svc_obj.id}'))
                                        svc_obj.image.save(fname, img, save=True)
                                    except Exception as e:
                                        logger.exception('Failed to save service image for new service (edit flow) %s: %s', svc_name, e)
                            except Exception as e:
                                logger.exception('Unexpected error while attaching image to service (edit flow): %s', e)
                        except Exception:
                            svc_obj = None

            raw_desc = desc if desc else (svc_obj.description if svc_obj and svc_obj.description else (svc_name or (svc_obj.name if svc_obj else 'Item')))

            qty_v = qty_dec.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP) if qty_dec is not None else Decimal('0')
            rate_v = price_dec if price_dec and price_dec != Decimal('0') else (svc_obj.default_rate if svc_obj else Decimal('0'))
            try:
                rate_v = rate_v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            except Exception:
                pass
            total_v = (qty_v * rate_v).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            qi = QuotationItem.objects.create(quotation=q, description=raw_desc, quantity=qty_v, raw_quantity=qty_v, manual_quantity=False, unit=unit or 'Nos', rate=rate_v, total=total_v, service=svc_obj)
            subtotal += total_v

        q.subtotal = subtotal
        q.tax_type = tax_type
        q.gst_type = 'with_gst' if tax_type in ('gst', 'igst') else 'without_gst'
        q.discount = discount_in

        if tax_type == 'gst':
            q.cgst = (subtotal * Decimal('0.09')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            q.sgst = (subtotal * Decimal('0.09')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total_calc = subtotal + q.cgst + q.sgst
        elif tax_type == 'igst':
            q.cgst = Decimal('0.00')
            q.sgst = Decimal('0.00')
            igst_amt = (subtotal * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total_calc = subtotal + igst_amt
        else:
            q.cgst = Decimal('0.00')
            q.sgst = Decimal('0.00')
            total_calc = subtotal
        total_calc = (total_calc - q.discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if total_calc < 0:
            total_calc = Decimal('0.00')
        q.total = total_calc

        selected_terms = request.POST.getlist('terms')
        print("DEBUG TERMS:", selected_terms)
        q.quotation_terms.all().delete()

        for term_id in selected_terms:
            try:
                order = request.POST.get(f'term_order_{term_id}', '').strip()
                order = int(order) if order else 0
                QuotationTerm.objects.create(
                    quotation=q,
                    term_id=int(term_id),
                    order=order
                )
            except Exception as e:
                print("ERROR:", e)

        q.custom_terms = (request.POST.get('custom_terms') or '').strip()
        tac = request.POST.get('terms_and_conditions', '').strip()
        # Preserve explicit user-entered custom terms, but avoid populating
        # the quotation record with the global default terms. If the user
        # provided tac, update; otherwise clear default text while keeping
        # any previously saved custom text.
        if tac:
            q.terms_and_conditions = tac
        else:
            if not (q.terms_and_conditions and q.terms_and_conditions != default_terms_text):
                q.terms_and_conditions = ''
        q.save()

        # --- Payment details handling for edit ---
        try:
            include_payment = True if request.POST.get('include_payment_details') in ('on', 'true', '1') else False
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            include_payment = False

        if include_payment:
            q.include_payment_details = True
            sel_id = request.POST.get('selected_payment_id')
            pd_obj = None
            if sel_id:
                try:
                    pd_obj = PaymentDetails.objects.get(id=int(sel_id), user=request.user)
                except Exception as e:
                    logger.exception('Unhandled exception: %s', e)
                    pd_obj = None

            if not pd_obj:
                acct_type = request.POST.get('payment_account_type') or PaymentDetails.BUSINESS
                acct_name = (request.POST.get('payment_account_name') or '').strip()
                holder = (request.POST.get('payment_holder_name') or '').strip()
                bank = (request.POST.get('payment_bank_name') or '').strip()
                acc_no = (request.POST.get('payment_account_number') or '').strip()
                ifsc = (request.POST.get('payment_ifsc_code') or '').strip()
                branch = (request.POST.get('payment_branch') or '').strip()
                upi = (request.POST.get('payment_upi_id') or '').strip()
                phone = (request.POST.get('payment_phone_number') or '').strip()
                save_it = True if request.POST.get('payment_action') == 'save' or request.POST.get('save_payment') == 'on' else False
                if any([acct_name, holder, bank, acc_no, ifsc, branch, upi, phone]):
                    # validate based on account type
                    valid = True
                    if acct_type in (PaymentDetails.BUSINESS, PaymentDetails.PERSONAL):
                        if not acc_no or not ifsc:
                            valid = False
                    elif acct_type == PaymentDetails.UPI:
                        if not upi and not phone:
                            valid = False

                    if not valid:
                        # mark include flag off and re-render edit form with error
                        q.include_payment_details = False
                        q.save()
                        return render(request, 'create_quotation.html', {
                            'customers': Customer.objects.all(),
                            'companies': companies,
                            'items': items,
                            'edit': True,
                            'q': q,
                            'quotations': Quotation.objects.all().order_by('-id')[:50],
                            'terms': terms_qs,
                            'terms_default': default_terms_text,
                            'term_orders': {qt.term_id: qt.order for qt in q.quotation_terms.all()},
                            'selected_terms': [qt.term_id for qt in q.quotation_terms.all()],
                            'payment_accounts': PaymentDetails.objects.filter(user=request.user),
                            'error': 'Invalid payment details for selected Account Type. Please fill required fields.'
                        })

                    try:
                        pd_obj = PaymentDetails.objects.create(
                            user=request.user,
                            account_type=acct_type,
                            account_name=acct_name,
                            holder_name=holder,
                            bank_name=bank,
                            account_number=acc_no,
                            ifsc_code=ifsc,
                            branch=branch,
                            upi_id=upi,
                            phone_number=phone,
                            is_default=False,
                        )
                        if save_it and request.POST.get('make_default') == 'on':
                            PaymentDetails.objects.filter(user=request.user).exclude(id=pd_obj.id).update(is_default=False)
                            pd_obj.is_default = True
                            pd_obj.save()
                    except Exception as e:
                        logger.exception('Unhandled exception: %s', e)
                        pd_obj = None

            if pd_obj:
                q.payment_details = pd_obj
        else:
            q.include_payment_details = False

        q.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Quotation updated', 'quotation_id': q.id})
        return redirect('view_quotation', id=q.id)

    term_orders_map = {qt.term_id: qt.order for qt in q.quotation_terms.all()}
    for t in terms_qs:
        try:
            t.selected_order = term_orders_map.get(t.id, '')
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            t.selected_order = ''

    return render(request, 'create_quotation.html', {
        'customers': Customer.objects.all(),
        'items': items,
        'edit': True,
        'q': q,
        'quotations': Quotation.objects.all().order_by('-id')[:50],
        'terms': terms_qs,
        'terms_default': default_terms_text,
        'term_orders': term_orders_map,
        'selected_terms': [qt.term_id for qt in q.quotation_terms.all()],
        'payment_accounts': PaymentDetails.objects.filter(user=request.user),
        'companies': companies,
        'services': Service.objects.order_by('name'),
    })


@login_required(login_url='/login/')
def update_quotation_item(request):
    """AJAX endpoint to update a single QuotationItem's dimensions/pricing and
    recompute quotation totals. Expects JSON: { item_id, width, height, raw_quantity, quantity, price }
    """
    import json
    from .models import QuotationItem, Quotation
    from .utils import to_decimal

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else request.POST.dict()
    except Exception:
        data = request.POST.dict()

    item_id = data.get('item_id')
    if not item_id:
        return JsonResponse({'error': 'item_id required'}, status=400)

    try:
        item = QuotationItem.objects.select_related('quotation').get(id=int(item_id))
    except QuotationItem.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)

    try:
        w = to_decimal(data.get('width') or '0')
        h = to_decimal(data.get('height') or '0')
        raw_q = to_decimal(data.get('raw_quantity') or '1')
        qty_in = data.get('quantity')
        manual_flag = str(data.get('manual_quantity') or data.get('manual') or '').lower() in ('1', 'true', 'yes')
        price_in = data.get('price')

        # Normalize raw measurement and persist it (3 decimals)
        try:
            raw_q = raw_q.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
        except Exception:
            pass

        # BUSINESS RULE: if user provided quantity (manual entry) or explicit manual flag, preserve it exactly
        if manual_flag or (qty_in not in (None, '', [])):
            try:
                qty_dec = to_decimal(qty_in).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
            except Exception:
                qty_dec = Decimal('0')
        else:
            # calculate from measurements when no manual quantity provided
            if w and h:
                area = (w * h * raw_q)
            elif w and not h:
                area = (w * raw_q)
            else:
                area = raw_q
            try:
                qty_dec = area.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
            except Exception:
                qty_dec = area

        price = to_decimal(price_in or item.rate or '0')
        try:
            price_dec = price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            price_dec = price

        total = (qty_dec * price_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Save changes to item and persist raw/manual flags
        item.width = w if w != Decimal('0') else (None if data.get('width') in (None, '') else w)
        item.height = h if h != Decimal('0') else (None if data.get('height') in (None, '') else h)
        item.quantity = qty_dec
        item.raw_quantity = raw_q
        item.manual_quantity = bool(manual_flag)
        item.rate = price_dec
        item.total = total
        item.save()

        # Recompute quotation totals
        q = item.quotation
        subtotal = sum((to_decimal(i.total) for i in q.items.all()), Decimal('0'))
        q.subtotal = subtotal.quantize(Decimal('0.01'))
        tt = _q_tax_type(q)
        if tt == 'gst':
            q.cgst = (subtotal * Decimal('0.09')).quantize(Decimal('0.01'))
            q.sgst = (subtotal * Decimal('0.09')).quantize(Decimal('0.01'))
            total_calc = subtotal + q.cgst + q.sgst
        elif tt == 'igst':
            q.cgst = Decimal('0.00')
            q.sgst = Decimal('0.00')
            igst_amt = (subtotal * Decimal('0.18')).quantize(Decimal('0.01'))
            total_calc = subtotal + igst_amt
        else:
            q.cgst = Decimal('0.00')
            q.sgst = Decimal('0.00')
            total_calc = subtotal
        total_calc = (total_calc - (q.discount or Decimal('0'))).quantize(Decimal('0.01'))
        if total_calc < 0:
            total_calc = Decimal('0.00')
        q.total = total_calc
        q.save()

        return JsonResponse({
            'status': 'success',
            'item_total': str(item.total),
            'quotation_subtotal': str(q.subtotal),
            'quotation_cgst': str(q.cgst),
            'quotation_sgst': str(q.sgst),
            'quotation_total': str(q.total),
        })
    except Exception as e:
        logger.exception('update_quotation_item error: %s', e)
        return JsonResponse({'error': 'Could not update item'}, status=500)


@login_required(login_url='/login/')
def get_service_json(request, id):
    try:
        svc = Service.objects.get(id=int(id))
    except Service.DoesNotExist:
        return JsonResponse({'error': 'Service not found'}, status=404)
    return JsonResponse({
        'id': svc.id,
        'name': svc.name,
        'default_rate': str(svc.default_rate),
        'image_url': svc.image.url if svc.image else '',
        'thumbnail': svc.thumbnail or ''
    })


@login_required(login_url='/login/')
def save_quotation_draft(request):
    """Save entire quotation (draft) via AJAX JSON payload.
    Expects JSON: { quotation_id (optional), customer_id, company_id, gst_type, discount, items: [{service_id, description, width, height, quantity, unit, price}] }
    """
    import json
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else request.POST.dict()
    except Exception:
        data = request.POST.dict()

    qid = data.get('quotation_id')
    cust_id = data.get('customer_id')
    company_id = data.get('company_id')
    tax_type = data.get('tax_type', 'none')
    discount_in = to_decimal(data.get('discount') or '0')

    if not cust_id:
        return JsonResponse({'error': 'customer_id required'}, status=400)
    try:
        customer = Customer.objects.get(id=int(cust_id))
    except Exception:
        return JsonResponse({'error': 'Customer not found'}, status=404)

    if qid:
        q = Quotation.objects.filter(id=int(qid)).first()
        if not q:
            return JsonResponse({'error': 'Quotation not found'}, status=404)
    else:
        legacy_gst = 'with_gst' if tax_type == 'gst' else 'without_gst'
        q = Quotation.objects.create(customer=customer, gst_type=legacy_gst, tax_type=tax_type)

    # attach company
    if company_id:
        try:
            q.company = Company.objects.get(id=int(company_id))
        except Exception:
            q.company = None

    # replace items
    q.items.all().delete()
    subtotal = Decimal('0')
    items = data.get('items') or []
    for it in items:
        desc = it.get('description') or ''
        svc_id = it.get('service_id')
        svc_name = it.get('service_name')
        width = it.get('width')
        height = it.get('height')
        qty_in = it.get('quantity') or it.get('raw_quantity') or '0'
        unit = it.get('unit') or 'Nos'
        price_in = it.get('price') or '0'

        try:
            qty = to_decimal(qty_in)
            price = to_decimal(price_in)
        except Exception:
            qty = Decimal('0')
            price = Decimal('0')

        try:
            qty_q = qty.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
        except Exception:
            qty_q = qty
        try:
            price_q = price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            price_q = price

        total = (qty_q * price_q).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        subtotal += total

        manual_flag = str(it.get('manual_quantity') or it.get('manual') or '').lower() in ('1', 'true', 'yes')

        qi = QuotationItem.objects.create(
            quotation=q,
            description=desc,
            quantity=qty_q,
            raw_quantity=qty_q,
            manual_quantity=bool(manual_flag),
            unit=unit,
            rate=price_q,
            total=total
        )
        if svc_id:
            try:
                s = Service.objects.get(id=int(svc_id))
                qi.service = s
                qi.service_code = s.service_code or ''
            except Exception:
                pass
        elif svc_name:
            try:
                name_clean = str(svc_name).strip()
                if name_clean:
                    s, created = Service.objects.get_or_create(name=name_clean, defaults={'default_rate': price, 'unit': unit or 'Sq Ft'})
                    qi.service = s
                    qi.service_code = s.service_code or ''
            except Exception:
                pass
        try:
            if width not in (None, ''):
                qi.width = to_decimal(width)
        except Exception:
            pass
        try:
            if height not in (None, ''):
                qi.height = to_decimal(height)
        except Exception:
            pass
        qi.save()

    q.subtotal = subtotal.quantize(Decimal('0.01'))
    q.discount = discount_in.quantize(Decimal('0.01'))
    q.tax_type = tax_type
    q.gst_type = 'with_gst' if tax_type in ('gst', 'igst') else 'without_gst'
    if tax_type == 'gst':
        q.cgst = (q.subtotal * Decimal('0.09')).quantize(Decimal('0.01'))
        q.sgst = (q.subtotal * Decimal('0.09')).quantize(Decimal('0.01'))
        total_calc = q.subtotal + q.cgst + q.sgst
    elif tax_type == 'igst':
        q.cgst = Decimal('0.00')
        q.sgst = Decimal('0.00')
        igst_amt = (q.subtotal * Decimal('0.18')).quantize(Decimal('0.01'))
        total_calc = q.subtotal + igst_amt
    else:
        q.cgst = Decimal('0.00')
        q.sgst = Decimal('0.00')
        total_calc = q.subtotal
    total_calc = (total_calc - q.discount).quantize(Decimal('0.01'))
    if total_calc < 0:
        total_calc = Decimal('0.00')
    q.total = total_calc
    q.save()

    return JsonResponse({'status': 'success', 'quotation_id': q.id, 'subtotal': str(q.subtotal), 'total': str(q.total)})


@login_required(login_url='/login/')
def ajax_save_payment(request):
    """AJAX endpoint to create or update a PaymentDetails record.
    Expects POST fields matching PaymentDetailsForm. Returns JSON with new id and data.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=400)

    # accept form-encoded or JSON body
    if request.content_type and request.content_type.startswith('application/json'):
        try:
            import json as _json
            data = _json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            data = request.POST.dict() if request.POST else {}
    else:
        data = request.POST.dict() if request.POST else {}
    logger.debug('ajax_save_payment incoming data: %s', {k: (v if len(str(v))<200 else '<<long>>') for k,v in data.items()})
    pay_id = data.get('payment_id') or data.get('id')

    form_data = {
        'account_type': data.get('payment_account_type') or data.get('account_type'),
        'account_name': data.get('payment_account_name') or data.get('account_name'),
        'holder_name': data.get('payment_holder_name') or data.get('holder_name'),
        'bank_name': data.get('payment_bank_name') or data.get('bank_name'),
        'account_number': data.get('payment_account_number') or data.get('account_number'),
        'ifsc_code': data.get('payment_ifsc_code') or data.get('ifsc_code'),
        'branch': data.get('payment_branch') or data.get('branch'),
        'upi_id': data.get('payment_upi_id') or data.get('upi_id'),
        'phone_number': data.get('payment_phone_number') or data.get('phone_number'),
        'is_default': True if data.get('make_default') in ('on', 'true', '1') else False,
    }

    form = PaymentDetailsForm(form_data)
    # Debug: also print to stdout so devserver console shows payload/errors
    try:
        print('ajax_save_payment incoming data:', {k: (v if len(str(v))<200 else '<<long>>') for k,v in data.items()})
    except Exception:
        pass
    if not form.is_valid():
        logger.debug('ajax_save_payment form errors: %s', form.errors)
        try:
            print('ajax_save_payment form errors:', form.errors)
        except Exception:
            pass
        # serialize errors to plain lists
        errs = {k: [str(x) for x in v] for k, v in form.errors.items()}
        nonf = [str(x) for x in form.non_field_errors()]
        return JsonResponse({'status': 'error', 'errors': errs, 'non_field_errors': nonf}, status=400)

    try:
        if pay_id:
            pd = PaymentDetails.objects.filter(id=int(pay_id), user=request.user).first()
            if not pd:
                return JsonResponse({'status': 'error', 'message': 'Payment record not found'}, status=404)
            for k, v in form.cleaned_data.items():
                setattr(pd, k, v)
            pd.user = request.user
            pd.save()
            if pd.is_default:
                PaymentDetails.objects.filter(user=request.user).exclude(id=pd.id).update(is_default=False)
            saved = pd
            action = 'updated'
        else:
            new_pd = form.save(commit=False)
            new_pd.user = request.user
            new_pd.is_default = form.cleaned_data.get('is_default', False)
            new_pd.save()
            if new_pd.is_default:
                PaymentDetails.objects.filter(user=request.user).exclude(id=new_pd.id).update(is_default=False)
            saved = new_pd
            action = 'created'

        payload = {
            'status': 'success',
            'id': saved.id,
            'account_name': saved.account_name,
            'holder_name': saved.holder_name,
            'account_type': saved.account_type,
            'bank_name': saved.bank_name,
            'account_number': saved.account_number,
            'ifsc_code': saved.ifsc_code,
            'branch': saved.branch,
            'upi_id': saved.upi_id,
            'phone_number': saved.phone_number,
            'action': action,
        }
        return JsonResponse(payload)
    except Exception as e:
        logger.exception('ajax_save_payment error: %s', e)
        return JsonResponse({'status': 'error', 'message': 'Server error'}, status=500)


@login_required(login_url='/login/')
@require_POST
def delete_payment_account(request, id):
    try:
        account = PaymentDetails.objects.get(id=id, user=request.user)
        account.delete()
        return JsonResponse({"success": True})
    except PaymentDetails.DoesNotExist:
        return JsonResponse({"success": False, "message": "Account not found"}, status=404)


# ================= LIST PAGE =================
@login_required(login_url='/login/')
def quotations(request):
    data = Quotation.objects.select_related('customer').order_by('-id')[:50]
    return render(request, 'quotations.html', {'data': data})


@login_required(login_url='/login/')
def delete_quotation(request, id):
    try:
        q = Quotation.objects.get(id=id)
    except Quotation.DoesNotExist:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'Quotation not found'}, status=404)
        return redirect('quotations')

    if request.method == 'POST':
        q.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Quotation deleted'})
        return redirect('quotations')
    return render(request, 'confirm_delete.html', {'obj': q})


# ================= QUOTATION PDF =================

@login_required(login_url='/login/')
def quotation_pdf(request, id):
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph,
        Spacer, HRFlowable, Image, KeepTogether, PageBreak
    )
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from datetime import datetime as _dt
    import html as _html
    import io, os

    today_date = _dt.now().strftime("%d-%m-%Y")
    q          = get_object_or_404(Quotation, id=id)
    items      = QuotationItem.objects.filter(quotation=q).select_related('quotation', 'service')

    customer_name = re.sub(r'[^A-Za-z0-9]+', '_', q.customer.name)
    filename      = f"{customer_name}_{today_date}.pdf"

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    # ── Page setup ────────────────────────────────────────────────────────────
    PAGE_SIZE = landscape(A4)
    doc = SimpleDocTemplate(
        response,
        pagesize=PAGE_SIZE,
        leftMargin=24, rightMargin=24,
        topMargin=40, bottomMargin=40,   # extra bottom for footer
    )
    page_w     = doc.width
    page_full_w = PAGE_SIZE[0]           # real page width (including margins)
    page_full_h = PAGE_SIZE[1]

    # ── Premium font registration ─────────────────────────────────────────────
    _FONT_PATHS = {
        'Poppins-Bold':    '/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf',
        'Poppins-Medium':  '/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf',
        'Poppins':         '/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf',
        'Caladea':         '/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf',
        'Caladea-Bold':    '/usr/share/fonts/truetype/crosextra/Caladea-Bold.ttf',
        'LibSerif-Bold':   '/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf',
        'LibSerif':        '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf',
    }
    _registered = {}
    for fname, fpath in _FONT_PATHS.items():
        try:
            if os.path.exists(fpath) and fname not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(fname, fpath))
            _registered[fname] = fname if os.path.exists(fpath) else None
        except Exception:
            _registered[fname] = None

    def _f(preferred, fallback='Helvetica'):
        """Return font name if registered, else fallback."""
        return preferred if _registered.get(preferred) else fallback

    # Resolved font aliases
    F_COMPANY   = _f('LibSerif-Bold',  'Helvetica-Bold')   # company name
    F_HEADING   = _f('Poppins-Bold',   'Helvetica-Bold')   # section headings
    F_SUBHEAD   = _f('Poppins-Medium', 'Helvetica')        # sub-headings / pills
    F_BODY      = _f('Caladea',        'Helvetica')        # body text
    F_BODY_BOLD = _f('Caladea-Bold',   'Helvetica-Bold')   # body bold
    F_UNICODE   = _f('Caladea',        None) or (lambda: (lambda fn, _: fn)(*_load_unicode_font()))()

    # Also keep existing unicode font for item descriptions (guaranteed to render)
    unicode_font, _ = _load_unicode_font()

# Image download cache and PIL for thumbnails
    import requests
    from PIL import Image as PILImage
    from io import BytesIO
    image_cache = {}
    thumbnail_cache = {}
    buffers_to_close = []

    # ── Colour palette ────────────────────────────────────────────────────────
    BROWN       = colors.HexColor('#4A3428')
    BROWN_LIGHT = colors.HexColor('#6B4C38')
    ACCENT      = colors.HexColor('#A67C52')
    ACCENT_PALE = colors.HexColor('#C9A97A')
    BG          = colors.HexColor('#FAF7F2')
    CREAM_CARD  = colors.HexColor('#F3EDE4')
    CREAM_DEEP  = colors.HexColor('#EDE3D6')
    BORDER      = colors.HexColor('#DDD5CB')
    TEXT        = colors.HexColor('#1F1F1F')
    TEXT2       = colors.HexColor('#6B6B6B')
    TEXT3       = colors.HexColor('#9A8E84')
    _WHITE      = colors.HexColor('#FFFFFF')
    GREEN_OK    = colors.HexColor('#2D7A4F')
    RED_NO      = colors.HexColor('#B91C1C')

    # ── Style factory ─────────────────────────────────────────────────────────
    def ps(name, font=None, size=9, color=TEXT, align=TA_LEFT, leading=None, **kw):
        f = font or F_BODY
        return ParagraphStyle(
            name, fontName=f, fontSize=size, textColor=color,
            alignment=align, leading=leading or size * 1.55, **kw
        )

    # ── Try registering Times New Roman (existing helper) ─────────────────────
    try:
        tnr_font = _register_times_new_roman()
    except Exception as e:
        logger.exception('TNR registration: %s', e)
        tnr_font = None
    # Override with Liberation Serif Bold (cleaner)
    co_name_font = F_COMPANY if _registered.get('LibSerif-Bold') else (tnr_font or 'Helvetica-Bold')

    # ═══════════════════════════════════════════════════════════════════════════
    # PARAGRAPH STYLES
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Header ────────────────────────────────────────────────────────────────
    s_co_name   = ps('co_name',   co_name_font,  28, _WHITE, TA_LEFT,  33)
    s_tagline   = ps('tagline',   F_SUBHEAD,     9,  ACCENT_PALE, TA_LEFT, 13, spaceBefore=1)
    s_info_hdr  = ps('info_hdr',  F_BODY,        8.5, colors.HexColor('#C4B5A8'), TA_LEFT, 13)
    s_doc_title = ps('doc_title', F_HEADING,     24, _WHITE, TA_RIGHT, 28)
    s_doc_sub   = ps('doc_sub',   F_SUBHEAD,     9,  ACCENT_PALE, TA_RIGHT, 13)
    s_doc_meta  = ps('doc_meta',  F_BODY,        9,  _WHITE, TA_RIGHT, 14)

    # ── Client card ───────────────────────────────────────────────────────────
    s_sec_lbl   = ps('sec_lbl',   F_HEADING,  7.5, ACCENT, TA_LEFT, 11,
                     spaceAfter=3, letterSpacing=1.8)
    s_client_n  = ps('client_n',  F_BODY_BOLD, 14, TEXT,   TA_LEFT, 19)
    s_client_s  = ps('client_s',  F_BODY,      9.5, TEXT2, TA_LEFT, 14)
    s_pill_lbl  = ps('pill_lbl',  F_BODY,      7.5, TEXT2, TA_LEFT, 11)
    s_pill_val  = ps('pill_val',  F_BODY_BOLD, 10,  TEXT,  TA_LEFT, 14)

    # ── Items table ───────────────────────────────────────────────────────────
    s_th        = ps('th',        F_HEADING,  8.5, _WHITE, TA_CENTER, 12)
    s_th_r      = ps('th_r',      F_HEADING,  8.5, _WHITE, TA_RIGHT,  12)
    s_td        = ps('td',        unicode_font, 9, TEXT,   TA_LEFT,   13)
    s_td_c      = ps('td_c',      unicode_font, 9, TEXT,   TA_CENTER, 13)
    s_td_r      = ps('td_r',      unicode_font, 9, TEXT,   TA_RIGHT,  13)

    # ── Summary ───────────────────────────────────────────────────────────────
    s_sum_lbl   = ps('sum_lbl',   F_BODY,      9,  TEXT2,  TA_LEFT,  13)
    s_sum_val   = ps('sum_val',   unicode_font, 9, TEXT,   TA_RIGHT, 13)
    s_gtl       = ps('gtl',       F_HEADING,  11, _WHITE, TA_LEFT,   15)
    s_gtv       = ps('gtv',       unicode_font,12, _WHITE, TA_RIGHT, 16)

    # ── Terms / Why Choose ───────────────────────────────────────────────────
    s_terms     = ps('terms',     F_BODY, 8.5, TEXT2, TA_LEFT, 14,
                     leftIndent=14, spaceAfter=2)
    s_terms_num = ps('tn',        F_HEADING, 8.5, ACCENT, TA_LEFT, 13)
    s_wcu_item  = ps('wcu',       F_BODY, 9, TEXT, TA_LEFT, 14, spaceAfter=1)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def P(text, style):
        return Paragraph(str(text) if text is not None else '', style)

    def format_inr_local(n):
        try:
            s = f"{Decimal(str(n)):.2f}"
            integer, dec = s.split(".")
            if len(integer) > 3:
                last3  = integer[-3:]
                rest   = integer[:-3]
                chunks = ""
                while len(rest) > 2:
                    chunks = "," + rest[-2:] + chunks
                    rest   = rest[:-2]
                integer = rest + chunks + "," + last3
            return f"\u20b9\u00A0{integer}.{dec}"
        except Exception:
            return "\u20b9\u00A00.00"

    # ══════════════════════════════════════════════════════════════════════════
    # COMPANY DATA
    # ══════════════════════════════════════════════════════════════════════════
    comp = getattr(q, 'company', None)
    if comp:
        logo_name   = comp.logo_path or 'logo.png'
        co_name_txt = (comp.name or 'SATYAM ALUMINIUM').upper()
        tagline_txt = comp.tagline or ''
        address_txt = comp.address or ''
        contact_txt = comp.phone or ''
        email_txt   = comp.email or ''
        gst_txt     = comp.gstin or ''
    else:
        logo_name   = 'logo.png'
        co_name_txt = 'SATYAM ALUMINIUM'
        tagline_txt = ''
        address_txt = ("Shop No. 4, Ganesh Plaza, Beside Triveni Bakery, "
                       "Nehru Nagar, Gokul Road, Hubballi\u2013 580030")
        contact_txt = "+91 8073709478 | +91 9448442717 | +91 9591291155"
        email_txt   = 'satyamaluminiumhubli@gmail.com'
        gst_txt     = '29ADRPR1399D1ZX'

    logo_img = _load_logo_image(logo_name, width=1.0 * inch, height=1.0 * inch, circular=True)

    # ══════════════════════════════════════════════════════════════════════════
    # CUSTOM CANVAS — watermark & footer drawn AFTER page content (on top)
    # ══════════════════════════════════════════════════════════════════════════
    # ReportLab's onFirstPage/onLaterPages fire BEFORE flowables are painted.
    # To render the watermark on top of all content we override showPage() in
    # a Canvas subclass so our drawing code runs just before the page is
    # finalised — guaranteeing it sits above every flowable.

    _wm_font    = co_name_font
    _wm_text    = co_name_txt
    _wm_tagline = ''
    _wm_gst     = gst_txt
    # Capture closure variables for canvas drawing
    _BROWN      = BROWN
    _ACCENT     = ACCENT
    _ACCENT_PALE= ACCENT_PALE
    _WHITE_c    = _WHITE
    _F_HEADING  = F_HEADING
    _F_BODY     = F_BODY
    _pw         = page_full_w
    _ph         = page_full_h

    from reportlab.pdfgen.canvas import Canvas as _BaseCanvas

    class NumberedLuxuryCanvas(_BaseCanvas):
        """Single-pass canvas that records pages and paints watermark/footer
        after the document is generated so we can include total page count.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            # Save the state of the current page and start a new one
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            # Iterate saved pages, restore state and paint overlays with total
            num_pages = len(self._saved_page_states)
            for page_num, state in enumerate(self._saved_page_states, start=1):
                self.__dict__.update(state)
                try:
                    self._paint_watermark()
                    self._paint_footer(page_num, num_pages)
                except Exception:
                    logger.exception('Error painting overlays on page %s', page_num)
                _BaseCanvas.showPage(self)
            _BaseCanvas.save(self)

            # Release page state memory explicitly to avoid retention across requests
            try:
                self._saved_page_states.clear()
            except Exception:
                pass
            try:
                del self._saved_page_states[:]
            except Exception:
                pass

        def _paint_watermark(self):
            pw = _pw
            ph = _ph
            lm = 24
            self.saveState()
            wm_size = 68
            self.setFont(_wm_font, wm_size)
            self.setFillColor(_BROWN)
            try:
                self.setFillAlpha(0.07)
            except Exception:
                pass
            self.translate(pw / 2, ph / 2)
            self.rotate(30)
            tw = self.stringWidth(_wm_text, _wm_font, wm_size)
            self.drawString(-tw / 2, 0, _wm_text)
            self.rotate(-30)
            self.translate(-pw / 2, -ph / 2)
            self.restoreState()

        def _paint_footer(self, page_num, total_pages):
            pw = _pw
            lm = 24
            self.saveState()
            try:
                self.setFillAlpha(1.0)
            except Exception:
                pass
            foot_h = 26
            foot_y = 8
            self.setFillColor(_BROWN)
            try:
                self.roundRect(lm, foot_y, pw - lm * 2, foot_h, 3, fill=1, stroke=0)
            except Exception:
                # fallback if roundRect not supported
                self.rect(lm, foot_y, pw - lm * 2, foot_h, fill=1, stroke=0)

            self.setStrokeColor(_ACCENT)
            self.setLineWidth(1.5)
            self.line(lm, foot_y + foot_h, pw - lm, foot_y + foot_h)

            # Left: company name
            self.setFillColor(_WHITE_c)
            self.setFont(_F_HEADING, 7.5)
            self.drawString(lm + 10, foot_y + 10, _wm_text)

            tag_display = _wm_tagline.strip() if _wm_tagline else ""
            if tag_display:
                self.setFillColor(_ACCENT_PALE)
                self.setFont(_F_BODY, 6.5)
                self.drawString(lm + 10, foot_y + 3.5, tag_display)

            # Centre: system note
            self.setFillColor(colors.HexColor('#C4B5A8'))
            self.setFont(_F_BODY, 6.5)
            note = (f"System-generated quotation \u2014 no signature required"
                    f"  |  GSTIN: {_wm_gst}")
            note_w = self.stringWidth(note, _F_BODY, 6.5)
            self.drawString((pw - note_w) / 2, foot_y + 7, note)

            # Right: page number
            self.setFillColor(_ACCENT_PALE)
            self.setFont(_F_HEADING, 7.5)
            pg_txt = f"Page {page_num} of {total_pages}"
            pg_w = self.stringWidth(pg_txt, _F_HEADING, 7.5)
            self.drawString(pw - lm - pg_w - 10, foot_y + 10, pg_txt)

            self.restoreState()

    # ══════════════════════════════════════════════════════════════════════════
    # BUILD FLOWABLES  (defined as a function so we can call twice)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_elements():
        elems = []

        # ══════════════════════════════════════════════════════════════════════
        # 1. HEADER BAND
        # ══════════════════════════════════════════════════════════════════════

        # ── Left: logo + company info ─────────────────────────────────────────
        # (divider column removed) — kept layout without the vertical gold line

        company_text = Table([
            [P(co_name_txt, s_co_name)],
            [P(tagline_txt, s_tagline)] if tagline_txt else [Spacer(1, 2)],
            [Spacer(1, 6)],
            [P(f"<font size='8.5' color='#C4B5A8'>"
               f"\u00A0{address_txt}</font>", s_info_hdr)],
            [P(f"<font size='8.5' color='#C4B5A8'>"
               f"&#9990;\u00A0{contact_txt}"
               f"\u2002\u00B7\u2002"
               f"&#9993;\u00A0{email_txt}</font>", s_info_hdr)],
        ], colWidths=[page_w * 0.56])
        company_text.setStyle(TableStyle([
            ('LEFTPADDING',  (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING',   (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 1),
            ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ]))

        # ── Right: QUOTATION + meta box ───────────────────────────────────────
        meta_w = page_w * 0.33 - 1.05 * inch

        # Small info rows: Date and GSTIN rendered as two-cell mini table
        meta_rows = Table([
            [P("<font size='7.5' color='#C4B5A8'>DATE</font>",  s_doc_sub),
             P(f"<b>{today_date}</b>",
               ps('dv', F_BODY_BOLD, 9, _WHITE, TA_RIGHT, 13))],
            [P("<font size='7.5' color='#C4B5A8'>GSTIN</font>", s_doc_sub),
             P(f"<b>{gst_txt}</b>",
               ps('gv', F_BODY_BOLD, 8, _WHITE, TA_RIGHT, 12))],
        ], colWidths=[meta_w * 0.22, meta_w * 0.78])
        meta_rows.setStyle(TableStyle([
            ('LEFTPADDING',  (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING',   (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
            ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ]))

        right_doc = Table([
            [P("QUOTATION", s_doc_title)],
            [P(f"<font color='#A67C52'>&#9670;</font> #{q.id:04d}", s_doc_sub)],
            [Spacer(1, 8)],
            [meta_rows],
        ], colWidths=[meta_w])
        right_doc.setStyle(TableStyle([
            ('LEFTPADDING',  (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING',   (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
            ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
            ('ALIGN',        (0, 0), (-1, -1), 'RIGHT'),
        ]))

        # ── Assemble header inner: logo | divider | company text | right doc ──
        header_inner = Table(
            [[logo_img, Spacer(18, 1),
              company_text, right_doc]],
            colWidths=[1.05 * inch, 18,
                       page_w * 0.56, meta_w]
        )
        header_inner.setStyle(TableStyle([
            ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING',  (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING',   (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 0),
        ]))

        header_band = Table([[header_inner]], colWidths=[page_w])
        header_band.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), BROWN),
            ('LEFTPADDING',   (0, 0), (-1, -1), 18),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 18),
            ('TOPPADDING',    (0, 0), (-1, -1), 14),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
            ('ROUNDEDCORNERS', [8]),
            ('LINEBELOW',     (0, 0), (-1, -1), 3, ACCENT),
        ]))
        elems.append(header_band)
        elems.append(Spacer(1, 12))

        # ══════════════════════════════════════════════════════════════════════
        # 2. CLIENT / QUOTATION INFO CARD
        # ══════════════════════════════════════════════════════════════════════
        tt = _q_tax_type(q)
        if tt == 'gst':
            gst_label = "GST (18%)"
            gst_color = "#2D7A4F"
        elif tt == 'igst':
            gst_label = "IGST (18%)"
            gst_color = "#2D7A4F"
        else:
            gst_label = "Without Tax"
            gst_color = "#B91C1C"

        left_w  = page_w * 0.60
        right_w = page_w * 0.40

        bill_block = Table([
            [P("BILL TO", s_sec_lbl)],
            [P(q.customer.name, s_client_n)],
            [P(q.customer.address or "\u2014", s_client_s)],
        ], colWidths=[left_w - 32])
        bill_block.setStyle(TableStyle([
            ('LEFTPADDING',  (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING',   (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
            ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ]))

        pill_w = (right_w - 34) / 2
        details_inner = Table([
            [P("Quotation No.", s_pill_lbl), P("GST Type",  s_pill_lbl)],
            [P(f"Q-{q.id}",     s_pill_val),
             P(f'<font color="{gst_color}"><b>{gst_label}</b></font>', s_pill_val)],
        ], colWidths=[pill_w, pill_w])
        details_inner.setStyle(TableStyle([
            ('LEFTPADDING',  (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING',   (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
            ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ]))

        details_block = Table([
            [P("QUOTATION DETAILS", s_sec_lbl)],
            [details_inner],
        ], colWidths=[right_w - 32])
        details_block.setStyle(TableStyle([
            ('LEFTPADDING',  (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING',   (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
            ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ]))

        info_card = Table([[bill_block, details_block]], colWidths=[left_w, right_w])
        info_card.setStyle(TableStyle([
            ('BOX',          (0, 0), (-1, -1), 0.8,  BORDER),
            ('LINEAFTER',    (0, 0), (0, -1),  0.5,  BORDER),
            ('LINEABOVE',    (0, 0), (-1, 0),  2.5,  ACCENT),
            ('BACKGROUND',   (0, 0), (0, -1),  _WHITE),
            ('BACKGROUND',   (1, 0), (1, -1),  CREAM_CARD),
            ('LEFTPADDING',  (0, 0), (-1, -1), 16),
            ('RIGHTPADDING', (0, 0), (-1, -1), 16),
            ('TOPPADDING',   (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 12),
            ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
            ('ROUNDEDCORNERS', [4]),
        ]))
        elems.append(info_card)
        elems.append(Spacer(1, 14))

        # ══════════════════════════════════════════════════════════════════════
        # 3. ITEMS TABLE SECTION HEADING
        # ══════════════════════════════════════════════════════════════════════
        elems.append(Paragraph(
            "ITEMS &amp; SERVICES",
            ps('sh', F_HEADING, 10, ACCENT, TA_CENTER, 14,
               spaceBefore=2, spaceAfter=2, letterSpacing=2.5)
        ))
        elems.append(HRFlowable(width="100%", thickness=0.6, color=BORDER, spaceAfter=8))

        # ══════════════════════════════════════════════════════════════════════
        # 4. ITEMS TABLE
        # ══════════════════════════════════════════════════════════════════════
        col_sl   = 30
        col_img  = 150
        col_qty  = 72
        col_rate = 82
        col_tot  = 94
        col_desc = page_w - col_sl - col_img - col_qty - col_rate - col_tot

        tbl_data = [[
            P("NO",         s_th),
            P("IMAGE",       s_th),
            P("DESCRIPTION", s_th),
            P("QTY",         s_th),
            P("RATE",        s_th_r),
            P("AMOUNT",      s_th_r),
        ]]

        subtotal = Decimal("0")
        for i, item in enumerate(items, 1):
            try:
                subtotal += Decimal(str(item.total))
            except Exception:
                pass

            img_flowable = None

            try:
                svc = getattr(item, 'service', None)

                if svc and svc.image:
                    image_url = svc.image.url

                    # Cache image bytes so repeated builds don't re-download
                    if image_url not in image_cache:
                        try:
                            r = requests.get(image_url, timeout=10)
                            if r.status_code == 200:
                                image_cache[image_url] = r.content
                        except Exception:
                            image_cache[image_url] = None

                    image_bytes = image_cache.get(image_url)
                    if image_bytes:
                        src_buf = BytesIO(image_bytes)
                        try:
                            pil_img = PILImage.open(src_buf)
                            if pil_img.mode != 'RGB':
                                pil_img = pil_img.convert('RGB')

                            # Production-grade thumbnail: keep good quality and reasonable size
                            pil_img.thumbnail((700, 550))

                            # Get size after thumbnailing
                            img_w, img_h = pil_img.size
                            if img_w <= 0 or img_h <= 0:
                                raise ValueError('Invalid image dimensions')

                            buffer = BytesIO()
                            pil_img.save(buffer, format='JPEG', quality=80, optimize=True)
                            buffer.seek(0)

                            # Track buffer so we can close it after reportlab finishes
                            try:
                                buffers_to_close.append(buffer)
                            except Exception:
                                pass

                            # Auto-fit the image into the image cell while preserving aspect ratio
                            CELL_W = col_img - 12  # leave small padding inside column
                            CELL_H = 90 - 12       # row height (ROWHEIGHT) minus padding

                            ratio = min(CELL_W / img_w, CELL_H / img_h)
                            new_w = img_w * ratio
                            new_h = img_h * ratio

                            img_flowable = Image(buffer, width=new_w, height=new_h)

                            # Center the image inside the cell using a small one-cell table
                            img_table = Table([[img_flowable]], colWidths=[col_img])
                            img_table.setStyle(TableStyle([
                                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                                ('LEFTPADDING', (0,0), (-1,-1), 6),
                                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                                ('TOPPADDING', (0,0), (-1,-1), 6),
                                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                            ]))

                            img_flowable = img_table
                        except Exception:
                            logger.exception('Failed to process service image: %s', image_url)
                            img_flowable = None
                        finally:
                            try:
                                pil_img.close()
                            except Exception:
                                pass
                            try:
                                src_buf.close()
                            except Exception:
                                pass

            except Exception:
                logger.exception('IMAGE ERROR for item id %s', getattr(item, 'id', None))
                img_flowable = None

            if img_flowable is None:
                img_flowable = P(
                    '<font size="7.5" color="#C4B5A8">No Image</font>',
                    ps('ni', F_BODY, 7.5, TEXT3, TA_CENTER, 10)
                )

            desc_text    = item.description or ''
            desc_escaped = _html.escape(desc_text)
            desc_with_br = desc_escaped.replace('\n', '<br/>')

            tbl_data.append([
                P(str(i), s_td_c),
                img_flowable,
                P(desc_with_br, s_td),
                P(f"{format_quantity(item.quantity)}\u00A0{item.unit}", s_td_c),
                P(format_inr_local(item.price), s_td_r),
                P(format_inr_local(item.total), s_td_r),
            ])

        row_styles = [
            ('BACKGROUND',    (0, 0), (-1, 0),  BROWN),
            ('TEXTCOLOR',     (0, 0), (-1, 0),  _WHITE),
            ('ALIGN',         (0, 0), (-1, 0),  'CENTER'),
            ('TOPPADDING',    (0, 0), (-1, 0),  9),
            ('BOTTOMPADDING', (0, 0), (-1, 0),  9),
            ('LINEBELOW',     (0, 0), (-1, 0),  2.5,  ACCENT),
            ('FONTNAME',      (0, 1), (-1, -1), unicode_font),
            ('FONTSIZE',      (0, 1), (-1, -1), 9),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN',         (0, 1), (0, -1),  'CENTER'),
            ('ALIGN',         (1, 1), (1, -1),  'CENTER'),
            ('ALIGN',         (2, 1), (2, -1),  'LEFT'),
            ('ALIGN',         (3, 1), (5, -1),  'CENTER'),
            ('ALIGN',         (4, 1), (5, -1),  'RIGHT'),
            ('WORDWRAP',      (2, 1), (2, -1),  'CJK'),
            ('TOPPADDING',    (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
            ('ROWHEIGHT',     (0, 1), (-1, -1), 90),
            ('BOX',           (0, 0), (-1, -1), 0.75, BORDER),
            ('LINEBELOW',     (0, 1), (-1, -1), 0.35, BORDER),
            ('LINEAFTER',     (0, 0), (4, -1),  0.35, BORDER),
            ('ROUNDEDCORNERS', [4]),
        ]
        for row in range(1, len(tbl_data)):
            bg = CREAM_CARD if row % 2 == 0 else _WHITE
            row_styles.append(('BACKGROUND', (0, row), (-1, row), bg))

        items_tbl = Table(
            tbl_data,
            colWidths=[col_sl, col_img, col_desc, col_qty, col_rate, col_tot],
            repeatRows=1
        )
        items_tbl.setStyle(TableStyle(row_styles))
        elems.append(items_tbl)
        elems.append(Spacer(1, 16))

        # ══════════════════════════════════════════════════════════════════════
        # 5. SUMMARY
        # ══════════════════════════════════════════════════════════════════════
        try:
            cgst = sgst = igst = Decimal("0")
            tt2 = _q_tax_type(q)
            if tt2 == 'gst':
                cgst = (subtotal * Decimal("0.09")).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP)
                sgst = (subtotal * Decimal("0.09")).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP)
            elif tt2 == 'igst':
                igst = (subtotal * Decimal("0.18")).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP)

            discount = Decimal(str(getattr(q, 'discount', None) or 0))
            if tt2 == 'gst':
                grand_total = subtotal + cgst + sgst - discount
            elif tt2 == 'igst':
                grand_total = subtotal + igst - discount
            else:
                grand_total = subtotal - discount
            grand_total = max(grand_total, Decimal('0'))
            grand_total = Decimal(grand_total).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)

            sw = 155
            summary_rows = [
                [P("Subtotal", s_sum_lbl), P(format_inr_local(subtotal), s_sum_val)]
            ]
            if tt2 == 'gst':
                summary_rows += [
                    [P("CGST (9%)",  s_sum_lbl), P(format_inr_local(cgst), s_sum_val)],
                    [P("SGST (9%)",  s_sum_lbl), P(format_inr_local(sgst), s_sum_val)],
                ]
            elif tt2 == 'igst':
                summary_rows += [
                    [P("IGST (18%)", s_sum_lbl), P(format_inr_local(igst), s_sum_val)],
                ]
            if discount and discount > 0:
                summary_rows.append([
                    P("<font color='#A67C52'><b>Special Discount</b></font>", s_sum_lbl),
                    P(f"<font color='#A67C52'>\u2212\u00A0"
                      f"{format_inr_local(discount)}</font>", s_sum_val),
                ])
            summary_rows.append([P("", s_sum_lbl), P("", s_sum_val)])
            gt_idx = len(summary_rows)
            summary_rows.append([
                P("GRAND TOTAL", s_gtl),
                P(format_inr_local(grand_total), s_gtv),
            ])

            sum_tbl = Table(summary_rows, colWidths=[sw, sw])
            sum_tbl.setStyle(TableStyle([
                ('ALIGN',         (1, 0), (-1, -1), 'RIGHT'),
                ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING',    (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING',   (0, 0), (-1, -1), 14),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
                ('LINEBELOW',     (0, 0), (-1, gt_idx - 2), 0.35, BORDER),
                ('BACKGROUND',    (0, gt_idx), (-1, gt_idx), BROWN),
                ('LINEABOVE',     (0, gt_idx), (-1, gt_idx), 2.5, ACCENT),
                ('TOPPADDING',    (0, gt_idx), (-1, gt_idx), 10),
                ('BOTTOMPADDING', (0, gt_idx), (-1, gt_idx), 10),
                ('BOX',           (0, 0), (-1, -1), 0.75, BORDER),
                ('ROUNDEDCORNERS', [4]),
            ]))

            sum_wrapper = Table(
                [[Spacer(1, 1), sum_tbl]],
                colWidths=[page_w - sw * 2, sw * 2]
            )
            sum_wrapper.setStyle(TableStyle([
                ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING',   (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING',(0, 0), (-1, -1), 0),
                ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
            ]))

        except Exception as e:
            logger.exception('Summary block error: %s', e)
            sw = 155
            summary_rows = [
                [P("Subtotal", s_sum_lbl), P(format_inr_local(subtotal), s_sum_val)]
            ]
            sum_tbl = Table(summary_rows, colWidths=[sw, sw])
            sum_tbl.setStyle(TableStyle([
                ('ALIGN',        (1, 0), (-1, -1), 'RIGHT'),
                ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING',   (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
                ('LEFTPADDING',  (0, 0), (-1, -1), 14),
                ('RIGHTPADDING', (0, 0), (-1, -1), 14),
                ('BOX',          (0, 0), (-1, -1), 0.75, BORDER),
            ]))
            sum_wrapper = Table(
                [[Spacer(1, 1), sum_tbl]],
                colWidths=[page_w - sw * 2, sw * 2]
            )
            sum_wrapper.setStyle(TableStyle([
                ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING',   (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING',(0, 0), (-1, -1), 0),
                ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
            ]))

        elems.append(sum_wrapper)
        elems.append(Spacer(1, 12))

        # ══════════════════════════════════════════════════════════════════════
        # 6. WHY CHOOSE US  (inserted before Terms & Conditions)
        # ══════════════════════════════════════════════════════════════════════
        wcu_items = [
            ("\u2713 Premium Grade Materials",       "\u2713 Expert Installation Team"),
            ("\u2713 Warranty Support",              "\u2713 On-Time Project Completion"),
            ("\u2713 Quality Assurance",             "\u2713 Professional Workmanship"),
            ("\u2713 Transparent Pricing",           "\u2713 Customer Satisfaction Focused"),
        ]

        wcu_heading_style = ps('wcu_h', F_HEADING, 10, BROWN, TA_CENTER, 14,
                               spaceAfter=8, letterSpacing=2)
        wcu_block = []

        # Heading row
        wcu_block.append(HRFlowable(width="100%", thickness=1.2, color=ACCENT, spaceAfter=8))
        wcu_block.append(Paragraph(
            f"WHY CHOOSE {co_name_txt}?",
            wcu_heading_style
        ))

        # Two-column grid of checkpoints
        wcu_col_w = (page_w - 24) / 2
        wcu_rows = []
        for left_item, right_item in wcu_items:
            wcu_rows.append([
                P(f"<font color='#A67C52'><b>&#10003;</b></font>"
                  f"\u00A0\u00A0{left_item.replace(chr(10003), '').strip()}",
                  s_wcu_item),
                P(f"<font color='#A67C52'><b>&#10003;</b></font>"
                  f"\u00A0\u00A0{right_item.replace(chr(10003), '').strip()}",
                  s_wcu_item),
            ])

        wcu_grid = Table(wcu_rows, colWidths=[wcu_col_w, wcu_col_w])
        wcu_grid.setStyle(TableStyle([
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING',   (0, 0), (-1, -1), 14),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LINEAFTER',     (0, 0), (0, -1),  0.4, BORDER),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [CREAM_CARD, _WHITE]),
        ]))

        wcu_card = Table([[wcu_grid]], colWidths=[page_w])
        wcu_card.setStyle(TableStyle([
            ('BOX',           (0, 0), (-1, -1), 0.8,  BORDER),
            ('LINEABOVE',     (0, 0), (-1, 0),  2.5,  ACCENT),
            ('BACKGROUND',    (0, 0), (-1, -1), CREAM_CARD),
            ('LEFTPADDING',   (0, 0), (-1, -1), 0),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
            ('TOPPADDING',    (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('ROUNDEDCORNERS', [4]),
        ]))

        wcu_block.append(wcu_card)
        wcu_block.append(Spacer(1, 6))

        # ══════════════════════════════════════════════════════════════════════
        # 7. TERMS & PAYMENT
        # ══════════════════════════════════════════════════════════════════════
        try:
            qt_qs = q.quotation_terms.select_related('term').order_by('order', 'id')

            terms_block = []

            terms_block.append(HRFlowable(
                width="100%", thickness=1.2, color=ACCENT, spaceAfter=8
            ))
            terms_block.append(Paragraph(
                "TERMS &amp; CONDITIONS",
                ps('tc_h', F_HEADING, 10, BROWN, TA_LEFT, 14,
                   spaceAfter=6, letterSpacing=2)
            ))

            def _add_terms_lines(lines_iter, start_idx=0):
                last = start_idx
                for j, line in enumerate(lines_iter, start_idx + 1):
                    if isinstance(line, str):
                        line = line.strip()
                    if not line:
                        continue
                    row_tbl = Table([[
                        P(f"{j}.", s_terms_num),
                        P(line, s_terms),
                    ]], colWidths=[20, page_w - 20])
                    row_tbl.setStyle(TableStyle([
                        ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING',   (0, 0), (-1, -1), 1),
                        ('BOTTOMPADDING',(0, 0), (-1, -1), 1),
                        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
                    ]))
                    terms_block.append(row_tbl)
                    last = j
                return last

            if q.terms_and_conditions:
                _add_terms_lines(q.terms_and_conditions.split("\n"))
            else:
                end_idx = 0
                if qt_qs.exists():
                    for i, qt in enumerate(qt_qs, 1):
                        row_tbl = Table([[
                            P(f"{i}.", s_terms_num),
                            P(qt.term.text, s_terms),
                        ]], colWidths=[20, page_w - 20])
                        row_tbl.setStyle(TableStyle([
                            ('LEFTPADDING',  (0, 0), (-1, -1), 0),
                            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                            ('TOPPADDING',   (0, 0), (-1, -1), 1),
                            ('BOTTOMPADDING',(0, 0), (-1, -1), 1),
                            ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
                        ]))
                        terms_block.append(row_tbl)
                        end_idx = i

                if q.custom_terms:
                    _add_terms_lines(q.custom_terms.split("\n"), start_idx=end_idx)

                if (not qt_qs.exists() and not q.custom_terms) \
                        and getattr(q, 'company', None) and q.company.terms:
                    _add_terms_lines(q.company.terms.split("\n"))

            # ── Payment details (quotation-level) ─────────────────────────
            payment_block = []
            try:
                if getattr(q, 'include_payment_details', False) \
                        and getattr(q, 'payment_details', None):
                    pd = q.payment_details

                    payment_block.append(Spacer(1, 10))
                    payment_block.append(HRFlowable(
                        width="100%", thickness=1, color=ACCENT, spaceAfter=6
                    ))
                    payment_block.append(Paragraph(
                        "PAYMENT DETAILS",
                        ps('pd_h', F_HEADING, 10, BROWN, TA_LEFT, 14,
                           spaceAfter=6, letterSpacing=2)
                    ))

                    rows = []
                    if pd.account_type == PaymentDetails.UPI:
                        if pd.upi_id:
                            rows.append([P("UPI ID", s_pill_lbl),
                                         P(pd.upi_id,      s_pill_val)])
                        if pd.phone_number:
                            rows.append([P("Phone",  s_pill_lbl),
                                         P(pd.phone_number, s_pill_val)])
                    else:
                        field_map = [
                            ("Account Name",   pd.account_name),
                            ("Account Holder", pd.holder_name),
                            ("Bank Name",      pd.bank_name),
                            ("A/C Number",     pd.account_number),
                            ("IFSC Code",      pd.ifsc_code),
                            ("Branch",         pd.branch),
                        ]
                        for label, value in field_map:
                            if value:
                                rows.append([P(label, s_pill_lbl), P(value, s_pill_val)])

                    if rows:
                        pay_tbl = Table(
                            rows,
                            colWidths=[page_w * 0.26, page_w * 0.74]
                        )
                        pay_tbl.setStyle(TableStyle([
                            ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
                            ('LEFTPADDING',    (0, 0), (-1, -1), 6),
                            ('RIGHTPADDING',   (0, 0), (-1, -1), 6),
                            ('TOPPADDING',     (0, 0), (-1, -1), 4),
                            ('BOTTOMPADDING',  (0, 0), (-1, -1), 4),
                            ('LINEBELOW',      (0, 0), (-1, -2), 0.35, BORDER),
                            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [_WHITE, CREAM_CARD]),
                        ]))
                        # Prevent the payment table from splitting across pages
                        payment_block.append(KeepTogether([pay_tbl]))
            except Exception as e:
                logger.exception('Payment details block error: %s', e)

            # ── Company bank details ───────────────────────────────────────
            bank_block = []
            try:
                if getattr(q, 'company', None) \
                        and getattr(q.company, 'bank_details', None):
                    bank_block.append(HRFlowable(
                        width="100%", thickness=1, color=ACCENT, spaceAfter=6
                    ))
                    bank_block.append(Paragraph(
                        "BANK / PAYMENT DETAILS",
                        ps('bd_h', F_HEADING, 10, BROWN, TA_LEFT, 14,
                           spaceAfter=6, letterSpacing=2)
                    ))
                    for line in q.company.bank_details.split("\n"):
                        if line.strip():
                            bank_block.append(Paragraph(line.strip(), s_pill_val))
            except Exception as e:
                logger.exception('Company bank details block error: %s', e)

            # Append WCU and footer sub-blocks; keep each heading + content together
            elems.append(KeepTogether(wcu_block))
            if terms_block:
                elems.append(KeepTogether(terms_block))
            if payment_block:
                elems.append(KeepTogether(payment_block))
            if bank_block:
                elems.append(KeepTogether(bank_block))

        except Exception as e:
            logger.exception('Terms & Payment wrapper error: %s', e)
            # If building footer_block failed, at least include the WCU block
            try:
                elems.extend(wcu_block)
            except Exception:
                pass

        return elems

    # ══════════════════════════════════════════════════════════════════════════
    # Single-pass build using NumberedLuxuryCanvas (records page states
    # and paints watermark/footer with total page count at save time)
    try:
        # Prepare elements once so we can explicitly release them after build
        elements = _build_elements()

        # Start tracemalloc to capture memory allocation hotspots
        try:
            import tracemalloc
            tracemalloc.start()
        except Exception:
            tracemalloc = None

        # Log memory before PDF generation
        try:
            import os, psutil
            process = psutil.Process(os.getpid())
            logger.info(f"RAM BEFORE PDF: {process.memory_info().rss / 1024 / 1024:.2f} MB")
        except Exception:
            process = None

        # Safety: refuse to start PDF if process is already using too much RAM
        try:
            import os, psutil
            check_proc = psutil.Process(os.getpid())
            ram_mb = check_proc.memory_info().rss / 1024 / 1024
            if ram_mb > 420:
                logger.warning('Refusing to start PDF build: high memory %.2f MB', ram_mb)
                try:
                    elements.clear()
                except Exception:
                    pass
                try:
                    del elements
                except Exception:
                    pass
                return HttpResponse(
                    "Server is currently busy generating quotations. Please try again in 1 minute.",
                    status=503
                )
        except Exception:
            pass

        # Build inside a try/finally so cleanup always runs even on errors
        try:
            doc.build(elements, canvasmaker=NumberedLuxuryCanvas)

            # Log memory after PDF generation
            try:
                if process is None:
                    import os, psutil
                    process = psutil.Process(os.getpid())
                logger.info(f"RAM AFTER PDF: {process.memory_info().rss / 1024 / 1024:.2f} MB")
            except Exception:
                pass

        finally:
            # RAM before/after GC diagnostics
            try:
                import gc, os, psutil
                process = psutil.Process(os.getpid())
                logger.info(f"RAM BEFORE GC: {process.memory_info().rss / 1024 / 1024:.2f} MB")
                gc.collect()
                logger.info(f"RAM AFTER GC: {process.memory_info().rss / 1024 / 1024:.2f} MB")
            except Exception:
                pass

            # Close tracked per-request buffers
            try:
                for b in buffers_to_close:
                    try:
                        b.close()
                    except Exception:
                        pass
                buffers_to_close.clear()
            except Exception:
                pass

            # Close any buffers created by helpers (logo, etc.)
            try:
                for b in list(_OPEN_BUFFERS):
                    try:
                        b.close()
                    except Exception:
                        pass
                _OPEN_BUFFERS.clear()
            except Exception:
                pass

            # Clear image caches
            try:
                image_cache.clear()
            except Exception:
                pass
            try:
                thumbnail_cache.clear()
            except Exception:
                pass

            # Tracemalloc snapshot (top consumers)
            try:
                if tracemalloc:
                    snapshot = tracemalloc.take_snapshot()
                    top_stats = snapshot.statistics('lineno')
                    logger.info('Top tracemalloc allocations:')
                    for stat in top_stats[:20]:
                        try:
                            logger.info(stat)
                        except Exception:
                            pass
                    try:
                        tracemalloc.stop()
                    except Exception:
                        pass
            except Exception:
                pass

            # Explicitly release large objects and force a GC pass
            try:
                try:
                    elements.clear()
                except Exception:
                    pass
                try:
                    del elements
                except Exception:
                    pass
                import gc
                gc.collect()
            except Exception:
                pass

        return response
    except Exception as e:
        logger.exception('PDF build failed: %s', e)
        raise


# ──────────────────────────────────────────────
# Small paragraph helpers (used by salary_pdf)
# ──────────────────────────────────────────────
def _plain(text, align=TA_LEFT, size=10, color=colors.black):
    """Plain text cell using DejaVuSans (supports all Unicode)."""
    return Paragraph(str(text), _ps(f'plain_{str(text)}', 'DejaVuSans', size, align, color))


def _header(text):
    """White bold header cell."""
    return Paragraph(str(text), _ps(f'hdr_{str(text)}', 'DejaVuSans-Bold', 10, TA_LEFT, colors.white))


def _rupee(amount, align=TA_RIGHT, size=10, color=colors.black):
    """
    ₹ amount cell. Uses HTML entity &#8377; (= ₹ U+20B9).
    DejaVuSans contains this glyph — guaranteed visible.
    """
    style = _ps(f'rp_{str(amount)}', 'DejaVuSans', size, align, color)
    try:
        val = to_decimal(amount).quantize(Decimal('0.01'))
        return Paragraph(f'&#8377; {val:,.2f}', style)
    except Exception as e:
        logger.exception('Unhandled exception: %s', e)
        return Paragraph(f'&#8377; {amount}', style)


# ================= ORDERS =================
@login_required(login_url='/login/')
def orders(request):
    query = request.GET.get('q', '').strip()
    qs = Order.objects.select_related('customer').order_by('-id')
    if query:
        from django.db.models import Q as DQ
        qs = qs.filter(
            DQ(customer__name__icontains=query) | DQ(id__icontains=query)
        ).order_by('-id')

    paginator = Paginator(qs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'orders.html', {
        'data': page_obj.object_list,
        'page_obj': page_obj,
        'q': query
    })


@login_required(login_url='/login/')
def delete_order(request, id):
    order = get_object_or_404(Order, id=id)
    if request.method == 'POST':
        order.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Order deleted successfully'})
        return redirect('orders')
    return render(request, 'confirm_delete.html', {'obj': order})


# ================= PAYMENT REMINDER PDF =================
@login_required(login_url='/login/')
def generate_reminder_pdf(request, order_id):
    from reportlab.lib.units import mm
    from reportlab.platypus.flowables import Flowable

    order    = get_object_or_404(Order, id=order_id)
    customer = order.customer
    payments = OrderPayment.objects.filter(order=order).order_by('payment_date', 'date')

    payments_sum = sum((p.amount for p in payments), Decimal('0'))
    total_paid   = order.advance_paid + payments_sum
    remaining    = order.total_amount - total_paid

    # ── Palette: clean light blue theme ──────────────────────────────────────
    C_HDR_DARK   = colors.HexColor("#1A5FA8")   # deep blue  — top header band
    C_HDR_MID    = colors.HexColor("#2B7FD4")   # medium blue — header accent
    C_BLUE_LIGHT = colors.HexColor("#E8F4FD")   # very light blue — title banner / info bg
    C_BLUE_MID   = colors.HexColor("#BBDAF7")   # soft blue — table header bg
    C_BLUE_PALE  = colors.HexColor("#F0F8FF")   # almost white blue — alternating rows
    C_ACCENT     = colors.HexColor("#1A5FA8")   # same deep blue for labels/accents
    C_BORDER     = colors.HexColor("#B3D4F0")   # light blue-grey border
    C_PAGE_BG    = colors.white                 # pure white page
    C_TEXT       = colors.HexColor("#0A0A0A")   # near-black text
    C_MUTED      = colors.HexColor("#3A3A3A")   # dark grey muted text
    C_LABEL      = colors.HexColor("#1A5FA8")   # blue for section labels
    C_WHITE      = colors.white
    C_DUE_BG     = colors.HexColor("#EBF5FF")   # light blue due block bg
    C_DUE_BORDER = colors.HexColor("#1A5FA8")   # deep blue due block border
    C_DUE_AMT    = colors.HexColor("#0D3E7A")   # darkest blue for due amount
    C_PAID_GRN   = colors.HexColor("#1A7A3A")   # green for paid entries
    C_HDR_TXT    = colors.HexColor("#FFFFFF")   # white header text
    C_TBL_HDR    = colors.HexColor("#1A5FA8")   # deep blue table header

    # ── Fonts ─────────────────────────────────────────────────────────────────
    # Use DejaVuSans for Unicode-safe rendering (bullets, ₹, dashes, local scripts)
    TNR       = "DejaVuSans"
    TNR_BOLD  = "Helvetica-Bold"
    TNR_ITAL  = "DejaVuSans"
    SANS      = "DejaVuSans"
    SANS_BOLD = "DejaVuSans"

    font_name, rupee_symbol = _load_unicode_font()

    def fmt(amount):
        try:
            rs = f"<font name='{font_name}'>{rupee_symbol}</font>"
            return f"{rs} {format_inr(amount)}"
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            rs = f"<font name='{font_name}'>{rupee_symbol}</font>"
            return f"{rs} {Decimal(amount).quantize(Decimal('0.01'))}"

    # ── Thin rule flowable ────────────────────────────────────────────────────
    class ThinRule(Flowable):
        def __init__(self, width, color=C_BORDER, thickness=0.7,
                     space_before=3, space_after=3):
            super().__init__()
            self.width        = width
            self.color        = color
            self.thickness    = thickness
            self.space_before = space_before
            self.space_after  = space_after

        def draw(self):
            self.canv.setStrokeColor(self.color)
            self.canv.setLineWidth(self.thickness)
            self.canv.line(0, self.space_after, self.width, self.space_after)

        def wrap(self, *args):
            return self.width, self.space_before + self.space_after + self.thickness

    def PS(name, **kw):
        return ParagraphStyle(name, **kw)

    # ── Page geometry ─────────────────────────────────────────────────────────
    PAGE_W, PAGE_H = A4
    MARGIN_H  = 36
    CONTENT_W = PAGE_W - 2 * MARGIN_H
    HDR_H     = 100  # canvas-drawn header height

    # ── Company info ──────────────────────────────────────────────────────────
    comp      = getattr(order, 'quotation', None)
    comp      = getattr(comp,  'company',   None) if comp else None
    comp_name = getattr(comp, 'name', '').upper()

    def _sanitize_header_text(txt):
        """Preserve Unicode; normalize whitespace and common non-breaking spaces/dashes.

        DejaVuSans is registered for rendering so we must NOT strip non-ASCII characters.
        """
        if not txt:
            return ''
        s = str(txt)
        s = s.replace('\u2013', '–')
        s = s.replace('\u2014', '—')
        s = s.replace('\u00A0', ' ')
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    # ── Canvas callback: header + background on every page ───────────────────
    def draw_page(canv, doc):
        canv.saveState()

        # White page background
        canv.setFillColor(C_PAGE_BG)
        canv.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

        # ── Header: two-tone blue band ────────────────────────────────────────
        # Main header band
        canv.setFillColor(C_HDR_DARK)
        canv.rect(0, PAGE_H - HDR_H, PAGE_W, HDR_H, fill=1, stroke=0)

        # Lighter blue diagonal accent (right portion of header)
        p = canv.beginPath()
        p.moveTo(PAGE_W * 0.55, PAGE_H - HDR_H)
        p.lineTo(PAGE_W,        PAGE_H - HDR_H)
        p.lineTo(PAGE_W,        PAGE_H)
        p.lineTo(PAGE_W * 0.70, PAGE_H)
        p.close()
        canv.setFillColor(C_HDR_MID)
        canv.drawPath(p, fill=1, stroke=0)

        # Thin sky-blue bottom stripe on header
        canv.setFillColor(colors.HexColor("#5BB3F0"))
        canv.rect(0, PAGE_H - HDR_H - 3, PAGE_W, 3, fill=1, stroke=0)

        # Very thin white rule 8px above that stripe
        canv.setFillColor(colors.HexColor("#FFFFFF"))
        canv.rect(0, PAGE_H - HDR_H - 5, PAGE_W, 1.2, fill=1, stroke=0)

        # ── Logo ──────────────────────────────────────────────────────────────
        logo_img = _load_logo_image(
            getattr(comp, 'logo_path', 'logo.png'),
            width=0.72 * inch, height=0.72 * inch, circular=False
        )
        logo_y = PAGE_H - HDR_H + (HDR_H - 0.72 * inch) / 2
        if logo_img:
            logo_img.drawOn(canv, MARGIN_H, logo_y)
            text_x = MARGIN_H + 0.72 * inch + 14
        else:
            text_x = MARGIN_H

        # Company name
        canv.setFont(TNR_BOLD, 27)
        canv.setFillColor(C_HDR_TXT)
        canv.drawString(text_x, PAGE_H - 36, comp_name)

        # Tagline
        tagline = getattr(comp, 'tagline', 'PRECISION  •  QUALITY  •  EXCELLENCE')
        canv.setFont(TNR_ITAL, 9.5)
        canv.setFillColor(colors.HexColor("#A8D8F8"))
        canv.drawString(text_x, PAGE_H - 52, tagline)

        # Thin white divider inside header
        canv.setStrokeColor(colors.HexColor("#4A9FD8"))
        canv.setLineWidth(0.5)
        canv.line(text_x, PAGE_H - 60, PAGE_W - MARGIN_H, PAGE_H - 60)

        # Contact line
        contact_parts = []
        addr = _sanitize_header_text(getattr(comp, 'address', None))
        if addr: contact_parts.append(addr)
        phone = _sanitize_header_text(getattr(comp, 'phone', None))
        if phone: contact_parts.append(phone)
        email = _sanitize_header_text(getattr(comp, 'email', None))
        if email: contact_parts.append(email)
        if contact_parts:
            contact_str = '   |   '.join(contact_parts)
            canv.setFont(SANS, 7.5)
            canv.setFillColor(colors.HexColor("#C8E8FA"))
            max_w = PAGE_W - text_x - MARGIN_H - 4
            while (canv.stringWidth(contact_str, SANS, 7.5) > max_w
                   and len(contact_parts) > 1):
                contact_parts = contact_parts[:-1]
                contact_str = '   |   '.join(contact_parts)
            canv.drawString(text_x, PAGE_H - 77, contact_str)

        # Thin outer page border
        canv.setStrokeColor(C_BORDER)
        canv.setLineWidth(0.8)
        canv.rect(6, 6, PAGE_W - 12, PAGE_H - 12, fill=0, stroke=1)

        # Thin blue left accent bar (content area only)
        canv.setFillColor(C_HDR_DARK)
        canv.rect(6, 6, 3.5, PAGE_H - HDR_H - 9, fill=1, stroke=0)

        canv.restoreState()

    # ── Paragraph styles ─────────────────────────────────────────────────────
    s_doc_title = PS("DocTitle", fontName=TNR_BOLD,  fontSize=15,
                     alignment=TA_CENTER, textColor=C_HDR_DARK, leading=20)
    s_doc_sub   = PS("DocSub",   fontName=SANS,       fontSize=8.5,
                     alignment=TA_CENTER, textColor=C_MUTED,    leading=13)

    s_label   = PS("Label",  fontName=SANS_BOLD, fontSize=7,
                   alignment=TA_LEFT,  textColor=C_LABEL, leading=10, spaceAfter=3)
    s_label_r = PS("LabelR", fontName=SANS_BOLD, fontSize=7,
                   alignment=TA_RIGHT, textColor=C_LABEL, leading=10, spaceAfter=3)
    s_val_l   = PS("ValL",   fontName=SANS, fontSize=9,
                   alignment=TA_LEFT,  textColor=C_TEXT,  leading=13)
    s_val_r   = PS("ValR",   fontName=SANS, fontSize=9,
                   alignment=TA_RIGHT, textColor=C_TEXT,  leading=13)
    s_name    = PS("CName",  fontName=TNR_BOLD, fontSize=12,
                   alignment=TA_LEFT,  textColor=C_TEXT,  leading=15)

    s_sec  = PS("Sec",  fontName=SANS_BOLD, fontSize=8.5, alignment=TA_LEFT,
                textColor=C_HDR_DARK, leading=12, spaceBefore=2)
    s_body = PS("Body", fontName=TNR, fontSize=10, alignment=TA_JUSTIFY,
                textColor=C_TEXT, leading=15)
    s_footer = PS("Footer", fontName=SANS, fontSize=7, alignment=TA_CENTER,
                  textColor=C_MUTED, leading=11)

    # ── Build document ────────────────────────────────────────────────────────
    cust_name_safe = re.sub(r'[^A-Za-z0-9]+', '_', (customer.name or 'customer')).strip('_')
    filename = f"{cust_name_safe}_reminder.pdf"
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    doc = SimpleDocTemplate(
        response, pagesize=A4,
        rightMargin=MARGIN_H,
        leftMargin=MARGIN_H + 4,   # clear the left accent bar
        topMargin=HDR_H + 14,
        bottomMargin=34,
    )

    elems = []

    # ── TITLE BANNER ──────────────────────────────────────────────────────────
    title_banner = Table(
        [[Paragraph("PAYMENT REMINDER", s_doc_title)],
         [Paragraph(
             f"Order No.&nbsp; <b>#{order.id}</b>"
             f"&nbsp;&nbsp;|&nbsp;&nbsp;"
             f"Issued:&nbsp; <b>{datetime.now().strftime('%d %B, %Y')}</b>",
             s_doc_sub,
         )]],
        colWidths=[CONTENT_W],
    )
    title_banner.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE_LIGHT),
        ("BOX",           (0, 0), (-1, -1), 1.2, C_HDR_DARK),
        ("LINEABOVE",     (0, 0), (-1, 0),  4,   C_HDR_DARK),
        ("TOPPADDING",    (0, 0), (-1, 0),  9),
        ("BOTTOMPADDING", (0,-1), (-1,-1),  9),
        ("TOPPADDING",    (0, 1), (-1, 1),  2),
        ("LEFTPADDING",   (0, 0), (-1,-1),  14),
        ("RIGHTPADDING",  (0, 0), (-1,-1),  14),
    ]))
    elems.append(title_banner)
    elems.append(Spacer(1, 10))

    # ── BILLED TO / ORDER DETAILS ─────────────────────────────────────────────
    info_tbl = Table(
        [[
            [
                Paragraph("BILLED TO", s_label),
                Paragraph(clean_text(customer.name), s_name),
                Paragraph(clean_text(customer.phone) or "\u2014", s_val_l),
                Paragraph(clean_text(customer.address) or "\u2014", s_val_l),
            ],
            [
                Paragraph("ORDER DETAILS", s_label_r),
                Paragraph(f"<b>Order ID:</b>&nbsp; #{order.id}", s_val_r),
                Paragraph(f"<b>Date:</b>&nbsp; {datetime.now().strftime('%d %B, %Y')}", s_val_r),
                Paragraph(
                    f"<b>Status:</b>&nbsp; "
                    f"<font color='#C0392B'><b>Outstanding</b></font>",
                    s_val_r,
                ),
            ],
        ]],
        colWidths=[CONTENT_W * 0.52, CONTENT_W * 0.48],
    )
    info_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1,-1), "TOP"),
        ("BOX",           (0, 0), (-1,-1), 0.8, C_BORDER),
        ("INNERGRID",     (0, 0), (-1,-1), 0.8, C_BORDER),
        ("BACKGROUND",    (0, 0), (0, -1), C_WHITE),
        ("BACKGROUND",    (1, 0), (1, -1), C_BLUE_LIGHT),
        ("TOPPADDING",    (0, 0), (-1,-1), 10),
        ("BOTTOMPADDING", (0, 0), (-1,-1), 10),
        ("LEFTPADDING",   (0, 0), (0, -1), 12),
        ("LEFTPADDING",   (1, 0), (1, -1), 10),
        ("RIGHTPADDING",  (1, 0), (1, -1), 12),
    ]))
    elems.append(info_tbl)
    elems.append(Spacer(1, 10))

    # ── Table cell helpers ────────────────────────────────────────────────────
    def _th(txt, align=TA_LEFT):
        return Paragraph(
            f"<font name='{SANS_BOLD}' size='8.5' color='#FFFFFF'>{txt}</font>",
            PS("TH", alignment=align, leading=12),
        )

    def _td_l(txt):
        return Paragraph(
            f"<font name='{SANS}' size='9' color='#0A0A0A'>{txt}</font>",
            PS("TDL", alignment=TA_LEFT, leading=13),
        )

    def _td_r(txt, color="#0A0A0A"):
        return Paragraph(
            f"<font name='{font_name}' size='9' color='{color}'>{txt}</font>",
            PS("TDR", alignment=TA_RIGHT, leading=13),
        )

    # ── FINANCIAL SUMMARY ─────────────────────────────────────────────────────
    elems.append(Paragraph("FINANCIAL SUMMARY", s_sec))
    elems.append(ThinRule(CONTENT_W, color=C_HDR_DARK, thickness=1.4,
                          space_before=2, space_after=4))

    col_d = CONTENT_W - 135
    col_a = 135
    fin_data = [
        [_th("Description"), _th("Amount", TA_RIGHT)],
        [_td_l("Total Order Amount"),  _td_r(fmt(order.total_amount))],
        [_td_l("Advance Paid"),        _td_r(f"\u2212 {fmt(order.advance_paid)}", "#1A7A3A")],
        [_td_l("Additional Payments"), _td_r(f"\u2212 {fmt(payments_sum)}",       "#1A7A3A")],
    ]
    fin_tbl = Table(fin_data, colWidths=[col_d, col_a])
    fin_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  C_TBL_HDR),
        ("TOPPADDING",    (0, 0), (-1, 0),  7),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  7),
        ("BACKGROUND",    (0, 1), (-1, 1),  C_WHITE),
        ("BACKGROUND",    (0, 2), (-1, 2),  C_BLUE_PALE),
        ("BACKGROUND",    (0, 3), (-1, 3),  C_WHITE),
        ("ALIGN",         (1, 0), (1, -1),  "RIGHT"),
        ("TOPPADDING",    (0, 1), (-1,-1),  6),
        ("BOTTOMPADDING", (0, 1), (-1,-1),  6),
        ("LEFTPADDING",   (0, 0), (-1,-1),  10),
        ("RIGHTPADDING",  (0, 0), (-1,-1),  10),
        ("LINEBELOW",     (0, 0), (-1,-2),  0.5, C_BORDER),
        ("BOX",           (0, 0), (-1,-1),  0.8, C_BORDER),
    ]))
    elems.append(fin_tbl)
    elems.append(Spacer(1, 8))

    # ── PAYMENT HISTORY ───────────────────────────────────────────────────────
    if payments.exists():
        elems.append(Paragraph("PAYMENT HISTORY", s_sec))
        elems.append(ThinRule(CONTENT_W, color=C_HDR_DARK, thickness=1.4,
                              space_before=2, space_after=4))

        ph_rows = [[_th("Date"), _th("Amount", TA_RIGHT), _th("Remarks")]]
        for p in payments:
            dt     = p.payment_date or getattr(p, 'date', None)
            dt_str = dt.strftime('%d-%m-%Y') if dt else '\u2014'
            remarks = clean_text(getattr(p, 'remarks', '') or '\u2014')
            ph_rows.append([
                Paragraph(dt_str, PS("PHl", fontName=SANS, fontSize=8.5,
                                     alignment=TA_LEFT,  textColor=C_TEXT,     leading=12)),
                Paragraph(fmt(p.amount), PS("PHr", fontName=font_name, fontSize=8.5,
                                            alignment=TA_RIGHT, textColor=C_PAID_GRN, leading=12)),
                Paragraph(remarks, PS("PHm", fontName=SANS, fontSize=8.5,
                                      alignment=TA_LEFT,  textColor=C_MUTED,   leading=12)),
            ])

        ph_tbl = Table(ph_rows, colWidths=[100, 125, CONTENT_W - 225])
        ph_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  C_TBL_HDR),
            ("TOPPADDING",    (0, 0), (-1, 0),  6),
            ("BOTTOMPADDING", (0, 0), (-1, 0),  6),
            ("ROWBACKGROUNDS",(0, 1), (-1,-1),  [C_WHITE, C_BLUE_PALE]),
            ("ALIGN",         (1, 0), (1, -1),  "RIGHT"),
            ("TOPPADDING",    (0, 1), (-1,-1),  5),
            ("BOTTOMPADDING", (0, 1), (-1,-1),  5),
            ("LEFTPADDING",   (0, 0), (-1,-1),  10),
            ("RIGHTPADDING",  (0, 0), (-1,-1),  10),
            ("LINEBELOW",     (0, 0), (-1,-2),  0.4, C_BORDER),
            ("BOX",           (0, 0), (-1,-1),  0.8, C_BORDER),
        ]))
        elems.append(ph_tbl)
        elems.append(Spacer(1, 8))

    # ── AMOUNT DUE BLOCK ──────────────────────────────────────────────────────
    due_lbl = Paragraph(
        f"<font name='{TNR_BOLD}' size='12' color='#0D3E7A'>TOTAL AMOUNT DUE</font>"
        f"<br/><font name='{SANS}' size='8' color='#3A3A3A'>"
        f"Kindly settle at your earliest convenience.</font>",
        PS("DueL", alignment=TA_LEFT, leading=17),
    )
    due_amt = Paragraph(
        f"<font name='{font_name}' size='22' color='#0D3E7A'><b>{fmt(remaining)}</b></font>",
        PS("DueR", fontName=font_name, fontSize=22,
           alignment=TA_RIGHT, textColor=C_DUE_AMT, leading=26),
    )
    due_tbl = Table(
        [[due_lbl, due_amt]],
        colWidths=[CONTENT_W * 0.55, CONTENT_W * 0.45],
    )
    due_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1,-1), C_DUE_BG),
        ("BOX",           (0, 0), (-1,-1), 1.5, C_DUE_BORDER),
        ("LINEAFTER",     (0, 0), (0,  0), 0.8, C_BORDER),
        ("TOPPADDING",    (0, 0), (-1,-1), 12),
        ("BOTTOMPADDING", (0, 0), (-1,-1), 12),
        ("LEFTPADDING",   (0, 0), (0,  0), 14),
        ("RIGHTPADDING",  (1, 0), (1,  0), 14),
        ("VALIGN",        (0, 0), (-1,-1), "MIDDLE"),
    ]))
    elems.append(due_tbl)
    elems.append(Spacer(1, 8))

    # ── NOTE MESSAGE ─────────────────────────────────────────────────────────
    elems.append(ThinRule(CONTENT_W, color=C_BORDER, thickness=0.6,
                          space_before=2, space_after=5))
    msg = (
        f"Dear <b>{clean_text(customer.name)}</b>, this is a gentle reminder that "
        f"<font name='{font_name}' color='#0D3E7A'><b>{fmt(remaining)}</b></font>"
        f" remains outstanding for Order <b>#{order.id}</b>. "
        f"Please make the payment at your earliest convenience. "
        f"For any queries, feel free to contact us. "
        f"Thank you for choosing <b>{comp_name}</b> — we value your trust."
    )
    elems.append(Paragraph(msg, s_body))

    # ── BANK DETAILS (if present) ─────────────────────────────────────────────
    if getattr(comp, 'bank_details', None):
        elems.append(Spacer(1, 5))
        elems.append(Paragraph("BANK / PAYMENT DETAILS", s_sec))
        elems.append(ThinRule(CONTENT_W, color=C_HDR_DARK, thickness=0.8,
                              space_before=2, space_after=3))
        for line in comp.bank_details.split('\n'):
            if line.strip():
                elems.append(Paragraph(line.strip(), s_body))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    elems.append(Spacer(1, 5))
    elems.append(ThinRule(CONTENT_W, color=C_BORDER, thickness=0.5,
                          space_before=0, space_after=4))
    contact_lines = []
    if getattr(comp, 'address', None): contact_lines.append(comp.address)
    phones = []
    if getattr(comp, 'phone',  None): phones.append(comp.phone)
    if getattr(comp, 'email',  None): phones.append(comp.email)
    if phones: contact_lines.append('  |  '.join(phones))

    footer_txt = (' &nbsp;|&nbsp; '.join(contact_lines) + '<br/>' if contact_lines else '')
    footer_txt += (
        f"<font color='#1A5FA8'>This document is system-generated "
        f"and does not require a physical signature.</font>"
    )
    elems.append(Paragraph(footer_txt, s_footer))

    doc.build(elems, onFirstPage=draw_page, onLaterPages=draw_page)
    return response


@login_required(login_url='/login/')
def convert_to_order(request, q_id):
    q = get_object_or_404(Quotation, id=q_id)

    if request.method == "POST":
        advance_str = request.POST.get('advance')
        try:
            advance = Decimal(advance_str or '0')
        except InvalidOperation:
            return render(request, 'convert_order.html', {
                'q': q, 'error': 'Invalid amount format'
            })

        total = q.total

        if advance < 0:
            return render(request, 'convert_order.html', {'q': q, 'error': 'Advance cannot be negative'})
        if advance > Decimal(total):
            return render(request, 'convert_order.html', {'q': q, 'error': 'Advance cannot exceed total quotation amount'})

        order = Order.objects.create(
            customer=q.customer,
            quotation=q,
            total_amount=total,
            advance_paid=advance
        )
        return generate_advance_acknowledgement_pdf(order, q, advance)
    return render(request, 'convert_order.html', {'q': q})


@login_required(login_url='/login/')
def add_order_payment(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    if request.method == "POST":
        amount_str = request.POST.get('amount')
        payment_date_str = request.POST.get('payment_date')
        remarks = (request.POST.get('remarks') or '').strip()
        try:
            amount = Decimal(amount_str or '0')
        except InvalidOperation:
            return render(request, 'add_payment.html', {
                'order': order, 'error': 'Invalid amount format'
            })

        # Validate amount
        if amount <= 0:
            return render(request, 'add_payment.html', {'order': order, 'error': 'Payment must be greater than zero'})

        remaining_amt = order.remaining()
        if amount > remaining_amt:
            return render(request, 'add_payment.html', {'order': order, 'error': 'Payment cannot exceed remaining balance'})

        # Parse payment date (allow backdating)
        try:
            if payment_date_str:
                payment_date = datetime.strptime(payment_date_str, '%Y-%m-%d').date()
            else:
                payment_date = timezone.now().date()
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            payment_date = timezone.now().date()

        OrderPayment.objects.create(order=order, amount=amount, payment_date=payment_date, remarks=remarks)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Payment added successfully'})
        return redirect('orders')
    return render(request, 'add_payment.html', {'order': order})


# ================= EMPLOYEES =================
@login_required(login_url='/login/')
def employees(request):
    return render(request, 'employees.html', {'data': Employee.objects.all()})


@login_required(login_url='/login/')
def add_employee(request):
    if request.method == "POST":
        name         = request.POST.get('name')
        phone        = request.POST.get('phone')
        role         = request.POST.get('role')
        salary_str   = request.POST.get('salary')
        half_str     = request.POST.get('half_salary')
        overtime_str = request.POST.get('overtime_salary')

        if not name or not salary_str or not half_str:
            return render(request, 'add_employee.html', {
                'error': 'Name, Daily Salary and Half Day Salary are required'
            })

        try:
            daily_salary    = Decimal(salary_str)
            half_day_salary = Decimal(half_str)
            overtime_salary = Decimal(overtime_str) if (overtime_str not in (None, '', 'None')) else None
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            return render(request, 'add_employee.html', {'error': 'Invalid salary format'})

        if daily_salary < 0 or half_day_salary < 0 or (overtime_salary is not None and overtime_salary < 0):
            return render(request, 'add_employee.html', {'error': 'Salary values must be non-negative'})

        Employee.objects.create(
            name=name, phone=phone, role=role,
            daily_salary=daily_salary,
            half_day_salary=half_day_salary,
            overtime_salary=overtime_salary
        )
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Employee added successfully'})
        return redirect('employees')
    return render(request, 'add_employee.html')


@login_required(login_url='/login/')
def edit_employee(request, emp_id):
    emp = get_object_or_404(Employee, id=emp_id)

    if request.method == "POST":
        emp.name  = request.POST.get('name')
        emp.phone = request.POST.get('phone')
        emp.role  = request.POST.get('role')
        salary_str   = request.POST.get('salary')
        half_str     = request.POST.get('half_salary')
        overtime_str = request.POST.get('overtime_salary')

        try:
            emp.daily_salary    = Decimal(salary_str)
            emp.half_day_salary = Decimal(half_str)
            emp.overtime_salary = Decimal(overtime_str) if (overtime_str not in (None, '', 'None')) else None
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            return render(request, 'edit_employee.html', {'emp': emp, 'error': 'Invalid salary format'})

        if emp.daily_salary < 0 or emp.half_day_salary < 0 or \
                (emp.overtime_salary is not None and emp.overtime_salary < 0):
            return render(request, 'edit_employee.html', {'emp': emp, 'error': 'Salary values must be non-negative'})

        emp.save()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Employee updated successfully'})
        return redirect('employees')
    return render(request, 'edit_employee.html', {'emp': emp})


@login_required(login_url='/login/')
def delete_employee(request, emp_id):
    emp = get_object_or_404(Employee, id=emp_id)

    if request.method == "POST":
        emp.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Employee deleted successfully'})
        return redirect('employees')
    return render(request, 'confirm_delete.html', {'obj': emp})


@login_required(login_url='/login/')
def mark_attendance(request, emp_id):
    from datetime import date as _date

    emp = get_object_or_404(Employee, id=emp_id)
    already_marked = Attendance.objects.filter(employee=emp, date=_date.today()).exists()

    if request.method == "POST":
        selected_date_str = request.POST.get('date')
        status = request.POST.get('status')

        # parse overtime checkbox safely
        overtime_bool = bool(request.POST.get('overtime'))

        # validate date
        try:
            selected_date = _date.fromisoformat(selected_date_str)
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            return render(request, 'mark_attendance.html', {
                'emp': emp, 'error': 'Invalid date format', 'already_marked': already_marked
            })

        # validate status against model choices
        allowed_statuses = [c[0] for c in Attendance.STATUS_CHOICES]
        if status not in allowed_statuses:
            return render(request, 'mark_attendance.html', {
                'emp': emp, 'error': 'Invalid status selected', 'already_marked': already_marked
            })

        if Attendance.objects.filter(employee=emp, date=selected_date).exists():
            return render(request, 'mark_attendance.html', {
                'emp': emp, 'error': 'Attendance already marked for this date', 'already_marked': True
            })

        Attendance.objects.create(
            employee=emp,
            date=selected_date,
            status=status,
            overtime=overtime_bool
        )
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Attendance marked'})
        return redirect('employees')

    return render(request, 'mark_attendance.html', {'emp': emp, 'already_marked': already_marked})





@login_required(login_url='/login/')
def salary(request, emp_id):
    emp = get_object_or_404(Employee, id=emp_id)
    result = calculate_salary(emp)
    return render(request, 'salary.html', {
        'emp': emp,
        'full_total': result['full_total'],
        'half_total': result['half_total'],
        'overtime_total': result['overtime_total'],
        'total_earned': result['earned'],
        'total_paid': result['paid'],
        'remaining': result['remaining'],
        'payments': result['payments'],
    })


@login_required(login_url='/login/')
def pay_salary(request, emp_id):
    emp = get_object_or_404(Employee, id=emp_id)
    # Use centralized calculation — no duplicate logic
    result    = calculate_salary(emp)
    total_earned = result['earned']
    total_paid   = result['paid']
    remaining    = result['remaining']

    if request.method == "POST":
        amount_str = request.POST.get('amount')
        try:
            amount = Decimal(amount_str)
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)
            return render(request, 'pay_salary.html', {
                'emp': emp, 'error': 'Invalid amount format',
                'total_earned': total_earned, 'total_paid': total_paid, 'remaining': remaining
            })

        if amount > remaining:
            return render(request, 'pay_salary.html', {
                'emp': emp, 'error': 'Amount exceeds remaining salary',
                'total_earned': total_earned, 'total_paid': total_paid, 'remaining': remaining
            })

        Payment.objects.create(employee=emp, amount_paid=amount)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Salary paid successfully'})
        return redirect('salary', emp_id=emp.id)

    return render(request, 'pay_salary.html', {
        'emp': emp, 'total_earned': total_earned,
        'total_paid': total_paid, 'remaining': remaining
    })


@login_required(login_url='/login/')
def payment_history(request, emp_id):
    emp = get_object_or_404(Employee, id=emp_id)
    return render(request, 'payment_history.html', {
        'emp': emp,
        'payments': Payment.objects.filter(employee=emp).order_by('-date')
    })


@login_required(login_url='/login/')
def reset_salary(request, emp_id):
    emp = get_object_or_404(Employee, id=emp_id)
    Attendance.objects.filter(employee=emp).delete()
    Payment.objects.filter(employee=emp).delete()
    return redirect('employees')


@login_required(login_url='/login/')
def view_attendance(request, emp_id):
    emp     = get_object_or_404(Employee, id=emp_id)
    records = Attendance.objects.filter(employee=emp).select_related('employee')

    start = request.GET.get('start_date')
    end   = request.GET.get('end_date')
    if start and end:
        records = records.filter(date__range=[start, end])

    return render(request, 'view_attendance.html', {'emp': emp, 'records': records})


# ================= ATTENDANCE REPORT PDF =================
@login_required(login_url='/login/')
def attendance_report_pdf(request, emp_id):
    emp = get_object_or_404(Employee, id=emp_id)

    start   = request.GET.get('start')
    end     = request.GET.get('end')
    records = Attendance.objects.filter(employee=emp).order_by('date')
    if start and end:
        try:
            records = records.filter(date__range=[start, end])
        except Exception as e:
            logger.exception('Unhandled exception: %s', e)

    records = list(records)

    total_days    = len(records)
    present_days  = sum(1 for r in records if r.status == 'full')
    half_days     = sum(1 for r in records if r.status == 'half')
    # Overtime count
    overtime_days = sum(1 for r in records if getattr(r, 'overtime', False))
    absent_days   = total_days - present_days - half_days

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="attendance_{emp.name}.pdf"'

    font_name, rupee_symbol = _load_unicode_font()

    doc    = SimpleDocTemplate(response, pagesize=A4, leftMargin=40, rightMargin=40,
                                topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    title_style    = ParagraphStyle('Title',    parent=styles['Heading1'], alignment=1,
                                    fontSize=18, leading=22, fontName=font_name)
    subtitle_style = ParagraphStyle('Sub',      parent=styles['Normal'],   alignment=1,
                                    fontSize=10, fontName=font_name)
    sect_style     = ParagraphStyle('Sect',     parent=styles['Heading3'], fontSize=12,
                                    fontName=font_name)

    elements = []

    elements.append(Paragraph('Satyam Aluminium', title_style))
    elements.append(Spacer(1, 6))

    hr = Table([['']], colWidths=[doc.width])
    hr.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.black),
                             ('ROWHEIGHT', (0, 0), (-1, -1), 1)]))
    elements.append(hr)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph('Attendance Report',
        ParagraphStyle('RepTitle', parent=styles['Heading2'], alignment=1,
                       fontSize=14, fontName=font_name)))
    elements.append(Paragraph(f'<b>{emp.name}</b>',
        ParagraphStyle('EmpName', parent=styles['Normal'], alignment=1,
                       fontSize=11, fontName=font_name)))
    elements.append(Spacer(1, 12))

    date_range_text = f"{start} to {end}" if start and end else 'All Dates'
    emp_details = [
        ['Employee Name:', emp.name],
        ['Employee ID:', str(emp.id)],
        ['Date Range:', date_range_text],
        ['Total Days:', str(total_days)],
        ['Present Days:', str(present_days)],
        ['Absent Days:', str(absent_days)],
        ['Half Days:', str(half_days)],
        ['Overtime Days:', str(overtime_days)],
    ]
    det_table = Table(emp_details, colWidths=[120, doc.width - 120])
    det_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), font_name),
    ]))
    elements.append(det_table)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph('Attendance Details', sect_style))
    table_data = [['Date', 'Day', 'Status', 'Overtime']]
    for r in records:
        date_str = r.date.strftime('%d-%m-%Y') if hasattr(r.date, 'strftime') else str(r.date)
        day      = r.date.strftime('%A') if hasattr(r.date, 'strftime') else ''
        status   = 'Full' if r.status == 'full' else ('Half' if r.status == 'half' else 'Absent')
        overtime_text = "Yes" if getattr(r, 'overtime', False) else "No"
        table_data.append([date_str, day, status, overtime_text])

    att_table = Table(table_data, colWidths=[90, 150, 100, doc.width - 340])
    tbl_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.white),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('FONTNAME', (0, 0), (-1, -1), font_name),
    ])
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            tbl_style.add('BACKGROUND', (0, i), (-1, i), colors.whitesmoke)
    att_table.setStyle(tbl_style)
    elements.append(att_table)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph('Summary', sect_style))
    summary = [
        ['Total Working Days', str(total_days)],
        ['Total Present', str(present_days)],
        ['Total Absent', str(absent_days)],
        ['Total Half Days', str(half_days)],
        ['Overtime Days', str(overtime_days)],
    ]
    sum_table = Table(summary, colWidths=[200, doc.width - 200])
    sum_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    elements.append(sum_table)
    elements.append(Spacer(1, 18))

    elements.append(Paragraph('This is a system-generated report',
        ParagraphStyle('Foot', parent=styles['Normal'], alignment=1,
                       fontSize=9, fontName=font_name)))
    elements.append(Spacer(1, 24))
    sig_table = Table([['', 'Signature: ____________________']],
                      colWidths=[doc.width - 200, 200])
    sig_table.setStyle(TableStyle([('ALIGN', (1, 0), (1, 0), 'RIGHT')]))
    elements.append(sig_table)

    doc.build(elements)
    return response


# ================= SALARY PDF =================
@login_required(login_url='/login/')
def salary_pdf(request, emp_id):
    emp = get_object_or_404(Employee, id=emp_id)

    # Single source of truth for salary calculation
    result = calculate_salary(emp)

    total_earned = result['earned']
    total_paid   = result['paid']
    remaining    = result['remaining']
    attendance   = result['attendance'].order_by('date')
    payments     = result['payments'].order_by('date')

    # Ensure fonts are available and get rupee char (fallback handled by _get_fonts)
    DATA, BOLD, RUPEE = _get_fonts()

    PAGE_W, _ = A4
    USABLE_W  = PAGE_W - 80

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="salary_{emp.name}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=40, rightMargin=40,
        topMargin=36, bottomMargin=36,
    )

    elements = []

    # HEADER
    elements.append(Paragraph(
        'SATYAM ALUMINIUM',
        _ps('co', 'Times-Bold', 26, TA_CENTER, DARK, 32)
    ))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        'Shop No. 4, Ganesh Plaza, Gokul Road, Hubballi',
        _ps('tag', 'Times-Roman', 10, TA_CENTER, colors.HexColor('#555555'))
    ))
    elements.append(Paragraph(
        '+91-8073709478 | satyamaluminiumhubli@gmail.com',
        _ps('ct', DATA, 8, TA_CENTER, GREY)
    ))
    elements.append(Spacer(1, 20))

    # TITLE
    elements.append(Paragraph(
        "<font name='Times-Bold' size='15'>EMPLOYEE SALARY REPORT</font>",
        _ps('title', 'Times-Bold', 15, TA_CENTER)
    ))
    elements.append(Spacer(1, 20))

    # EMPLOYEE INFO
    gen_date = datetime.now().strftime('%d %B, %Y')

    info_data = [
        [_plain('Employee Name'), _plain(emp.name)],
        [_plain('Employee ID'),   _plain(f'#EMP-{emp.id}')],
        [_plain('Role'),          _plain(getattr(emp, 'role', 'N/A'))],
        [_plain('Daily Salary'),  _rupee(emp.daily_salary)],
        [_plain('Report Date'),   _plain(gen_date)],
    ]

    info_tbl = Table(info_data, colWidths=[150, USABLE_W - 150])
    info_tbl.setStyle(TableStyle([
        ('GRID',       (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (0,  -1), colors.whitesmoke),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
    ]))

    elements.append(info_tbl)
    elements.append(Spacer(1, 20))

    # LEDGER
    elements.append(Paragraph(
        'ATTENDANCE & PAYMENT LEDGER',
        _ps('sec', 'Times-Bold', 12, TA_LEFT)
    ))
    elements.append(Spacer(1, 10))

    ledger = [[
        _header('Date'), _header('Day'), _header('Type'), _header('Description'), _header('Amount')
    ]]

    for att in attendance:
        date_str = att.date.strftime('%d %b %Y')
        day_str  = att.date.strftime('%A')

        if att.status == 'full':
            ledger.append([_plain(date_str), _plain(day_str), _plain('Earned'), _plain('Full Day'), _rupee(emp.daily_salary)])

        elif att.status == 'half':
            ledger.append([_plain(date_str), _plain(day_str), _plain('Earned'), _plain('Half Day'), _rupee(emp.half_day_salary)])

        if getattr(att, 'overtime', False):
            ledger.append([_plain(date_str), _plain(day_str), _plain('Earned'), _plain('Overtime'), _rupee(emp.overtime_salary)])

    for p in payments:
        date_str = p.date.strftime('%d %b %Y')
        day_str  = p.date.strftime('%A')
        ledger.append([_plain(date_str), _plain(day_str), _plain('Paid'), _plain('Salary Paid'), _rupee(p.amount_paid)])

    col_w = [80, 80, 70, USABLE_W - 330, 80]
    ledger_tbl = Table(ledger, colWidths=col_w)
    ledger_tbl.setStyle(TableStyle([
        ('GRID',            (0, 0), (-1, -1), 0.3, colors.grey),
        ('BACKGROUND',      (0, 0), (-1,  0), colors.black),
        ('TEXTCOLOR',       (0, 0), (-1,  0), colors.white),
        ('VALIGN',          (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',      (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING',   (0, 0), (-1, -1), 6),
        ('LEFTPADDING',     (0, 0), (-1, -1), 6),
    ]))

    elements.append(ledger_tbl)
    elements.append(Spacer(1, 20))

    # SUMMARY
    elements.append(Paragraph('FINANCIAL SUMMARY', _ps('sec2', 'Times-Bold', 12)))
    elements.append(Spacer(1, 6))

    summary_data = [
        [_plain('Total Earned'), _rupee(total_earned)],
        [_plain('Total Paid'),   _rupee(total_paid)],
        [_plain('Remaining'),    _rupee(remaining)],
    ]

    summary = Table(summary_data, colWidths=[USABLE_W - 150, 150])
    summary.setStyle(TableStyle([
        ('GRID',            (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND',      (0, 2), (-1,  2), colors.red),
        ('TOPPADDING',      (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING',   (0, 0), (-1, -1), 8),
        ('LEFTPADDING',     (0, 0), (-1, -1), 8),
        ('VALIGN',          (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    elements.append(summary)

    doc.build(elements)
    return response

@login_required(login_url='/login/')
def export_excel(request, emp_id):
    emp     = get_object_or_404(Employee, id=emp_id)
    records = Attendance.objects.filter(employee=emp)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Attendance"
    ws.append(['Date', 'Status'])

    for r in records:
        ws.append([r.date.strftime('%Y-%m-%d'), r.status])

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{emp.name}_attendance.xlsx"'
    wb.save(response)
    return response


# ================= TERMS & CONDITIONS =================
@login_required(login_url='/login/')
def add_term(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    text = request.POST.get('text')
    if not text or not text.strip():
        return JsonResponse({'error': 'Text required'}, status=400)

    term = TermCondition.objects.create(text=text.strip())
    return JsonResponse({'id': term.id, 'text': term.text})


@login_required(login_url='/login/')
def edit_term(request, id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    term = get_object_or_404(TermCondition, id=id)
    text = request.POST.get('text', '').strip()
    if not text:
        return JsonResponse({'error': 'Text required'}, status=400)

    term.text = text
    term.save()
    return JsonResponse({'id': term.id, 'text': term.text})