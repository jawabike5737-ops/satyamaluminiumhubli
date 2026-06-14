from django.http import HttpResponse
from django.conf import settings
from django.contrib.staticfiles import finders   # ← ADD THIS
import os
import psutil
import re
from decimal import Decimal
from datetime import datetime
import logging

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image as PILImage
import io
from django.core.files.base import ContentFile


def compress_image_file(file_obj, max_width=1200, quality=22, target_kb=None):
    """
    Compress an image file-like object and return bytes of a JPEG image.

    - Converts RGBA/PNG to RGB JPEG
    - Resizes to max_width preserving aspect ratio
    - Saves with optimize=True and adjustable quality
    - If target_kb provided, will lower quality in a loop until size <= target_kb
    """
    try:
        # Attempt to determine original size (bytes) for debugging
        original_bytes = None
        try:
            if hasattr(file_obj, 'size') and isinstance(getattr(file_obj, 'size'), (int, float)):
                original_bytes = int(file_obj.size)
            elif hasattr(file_obj, 'tell') and hasattr(file_obj, 'seek'):
                cur = file_obj.tell()
                file_obj.seek(0, io.SEEK_END)
                original_bytes = file_obj.tell()
                try:
                    file_obj.seek(cur)
                except Exception:
                    pass
        except Exception:
            original_bytes = None

        # Load image from file-like (supports InMemoryUploadedFile and file paths)
        if hasattr(file_obj, 'read'):
            try:
                file_obj.seek(0)
            except Exception:
                pass
            img = PILImage.open(file_obj)
        else:
            img = PILImage.open(file_obj)

        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'LA'):
            bg = PILImage.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Resize if wider than max_width
        try:
            w, h = img.size
            if w > max_width:
                new_h = int((max_width / float(w)) * h)
                img = img.resize((int(max_width), new_h), PILImage.LANCZOS)
        except Exception:
            pass

        buf = io.BytesIO()
        q = int(max(10, min(quality, 95)))
        img.save(buf, format='JPEG', quality=q, optimize=True)
        data = buf.getvalue()

        # If target size requested, reduce quality until achieved (min quality 10)
        if target_kb and len(data) > (target_kb * 1024):
            for q2 in range(q - 2, 9, -2):
                buf = io.BytesIO()
                try:
                    img.save(buf, format='JPEG', quality=q2, optimize=True)
                    data = buf.getvalue()
                    if len(data) <= (target_kb * 1024):
                        break
                except Exception:
                    continue

        # Print / log original and compressed sizes (KB) for professional debugging
        try:
            compressed_kb = (len(data) / 1024.0) if data is not None else None
            if original_bytes:
                original_kb = (original_bytes / 1024.0)
                msg = f"\nOriginal: {original_kb:.2f} KB\nCompressed: {compressed_kb:.2f} KB\n"
            else:
                msg = f"\nCompressed: {compressed_kb:.2f} KB\n"
            # Print to stdout for immediate terminal debugging and also log at debug level
            try:
                print(msg)
            except Exception:
                pass
            try:
                logging.getLogger(__name__).debug(msg)
            except Exception:
                pass
        except Exception:
            pass

        return data
    except Exception:
        return None


def optimize_image(file_obj, max_width=1920, quality=85, fmt='WEBP', method=6):
    """
    Optimize an uploaded image and return a Django ContentFile with WEBP bytes.

    - Converts RGBA/P/PNG to RGB
    - Resizes only if width > max_width preserving aspect ratio
    - Saves as WEBP with given quality and method
    - Returns ContentFile(byte_data)
    """
    try:
        # Ensure we can read from the file-like object
        try:
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
        except Exception:
            pass

        img = PILImage.open(file_obj)

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        w, h = img.size
        if w > max_width:
            ratio = float(max_width) / float(w)
            new_h = int(h * ratio)
            img = img.resize((int(max_width), new_h), PILImage.LANCZOS)

        output = io.BytesIO()
        save_kwargs = {}
        # PIL expects format names like 'WEBP'
        save_kwargs['format'] = fmt
        save_kwargs['quality'] = int(quality)
        # method is supported by Pillow for WEBP
        try:
            save_kwargs['method'] = int(method)
        except Exception:
            pass
        save_kwargs['optimize'] = True

        img.save(output, **save_kwargs)
        output.seek(0)
        return ContentFile(output.read())
    except Exception:
        return None


def to_decimal(value):
    """Safely convert a value to Decimal.

    - Converts None/'' to Decimal('0').
    - Uses Decimal(str(value)) to avoid float artifacts.
    - Catches InvalidOperation/TypeError and returns Decimal('0').
    """
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(str(value)) if value is not None and value != '' else Decimal('0')
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def format_quantity(value):
    """Format a Decimal quantity for display without unnecessary trailing zeros.

    Examples:
      Decimal('49.000') -> '49'
      Decimal('49.200') -> '49.2'
      Decimal('49.257') -> '49.257'
    """
    from decimal import Decimal
    try:
        d = Decimal(str(value))
    except Exception:
        try:
            return str(value)
        except Exception:
            return ''
    try:
        n = d.normalize()
        s = format(n, 'f')
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
        return s
    except Exception:
        return str(d)


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

    logger = logging.getLogger(__name__)
    try:
        if os.path.exists(times_regular) and os.path.exists(times_bold):
            if 'TNR' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('TNR',      times_regular))
                pdfmetrics.registerFont(TTFont('TNR-Bold', times_bold))
                if os.path.exists(times_italic):
                    pdfmetrics.registerFont(TTFont('TNR-Italic', times_italic))
            return 'TNR', 'TNR-Bold', 'TNR-Italic'
    except Exception as e:
        logger.exception('Failed to register Times fonts: %s', e)

    # Use the project's static fonts directory to locate DejaVuSans
    dejavu = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'DejaVuSans.ttf')
    try:
        if os.path.exists(dejavu):
            if 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('DejaVu', dejavu))
            return 'DejaVu', 'DejaVu', 'DejaVu'
    except Exception as e:
        logger.exception('Failed to register DejaVu font: %s', e)

    return 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'


# ─────────────────────────────────────────────
# INR FORMATTER  (Indian comma style)
# ─────────────────────────────────────────────
def format_inr(number):
    from decimal import Decimal, InvalidOperation
    try:
        num = Decimal(str(number))
    except (InvalidOperation, ValueError):
        num = Decimal('0')
    s = f"{num:.2f}"
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

# ADVANCE PAYMENT ACKNOWLEDGEMENT PDF

def generate_advance_acknowledgement_pdf(order, quotation, advance_amount):
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph,
        Spacer, HRFlowable, KeepTogether
    )
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas as _BaseCanvas
    from datetime import datetime
    import io as _io
    import os

    # ── Luxury Palette ────────────────────────────────────────────────────────
    # Premium Beige + Dark Brown + Gold — Luxury Interior / Architectural feel
    BROWN        = colors.HexColor('#4A3428')   # Header, footer bar, table headers
    ACCENT       = colors.HexColor('#A67C52')   # Gold accent lines, section labels
    ACCENT_PALE  = colors.HexColor('#C9A97A')   # Pale gold for header sub-text
    CREAM_BG     = colors.HexColor('#FAF7F2')   # Page background tint
    CREAM_CARD   = colors.HexColor('#F3EDE4')   # Alternating row / card fill
    CREAM_DEEP   = colors.HexColor('#EDE3D6')   # Section header background
    BORDER       = colors.HexColor('#DDD5CB')   # Table borders, HR lines
    TEXT         = colors.HexColor('#1F1F1F')   # Primary text
    TEXT2        = colors.HexColor('#6B6B6B')   # Secondary text
    TEXT3        = colors.HexColor('#9A8E84')   # Footer note text
    WHITE        = colors.HexColor('#FFFFFF')
    DANGER_TXT   = colors.HexColor('#8B2020')   # Balance remaining (red-brown)
    SUCCESS_TXT  = colors.HexColor('#2D6A2D')   # Received ✓ (green)

    # ── Font Registration ─────────────────────────────────────────────────────
    _FONT_PATHS = {
        'Poppins-Bold':    '/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf',
        'Poppins-Medium':  '/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf',
        'Poppins-Regular': '/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf',
        'Caladea':         '/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf',
        'Caladea-Bold':    '/usr/share/fonts/truetype/crosextra/Caladea-Bold.ttf',
        'Caladea-Italic':  '/usr/share/fonts/truetype/crosextra/Caladea-Italic.ttf',
        'LibSerif-Bold':   '/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf',
        'LibSerif':        '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf',
    }
    _reg = {}
    for fname, fpath in _FONT_PATHS.items():
        try:
            if os.path.exists(fpath) and fname not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(fname, fpath))
            _reg[fname] = os.path.exists(fpath)
        except Exception:
            _reg[fname] = False

    # Ensure DejaVu (contains INR glyph) is available as a fallback
    dejavu_path = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'DejaVuSans.ttf')
    try:
        if os.path.exists(dejavu_path) and 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('DejaVu', dejavu_path))
            _reg['DejaVu'] = True
        else:
            _reg.setdefault('DejaVu', os.path.exists(dejavu_path))
    except Exception:
        _reg.setdefault('DejaVu', False)

    def _f(preferred, fallback='Helvetica'):
        return preferred if _reg.get(preferred) else fallback

    # Font aliases
    F_HEADING  = _f('Poppins-Bold',    'Helvetica-Bold')
    F_SUBHEAD  = _f('Poppins-Medium',  'Helvetica')
    F_REGULAR  = _f('Poppins-Regular', 'Helvetica')
    F_COMPANY  = _f('LibSerif-Bold',   'Helvetica-Bold')
    # Prefer DejaVu for body text (supports INR symbol). Fall back to Caladea/Helvetica.
    F_BODY     = 'DejaVu' if _reg.get('DejaVu') else _f('Caladea', 'Helvetica')
    F_BOLD     = _f('Caladea-Bold',    'Helvetica-Bold')
    F_ITALIC   = _f('Caladea-Italic',  'Helvetica-Oblique')

    # ── Style factory ─────────────────────────────────────────────────────────
    def ps(name, fn, fs, color=TEXT, align=TA_LEFT, leading=None, **kw):
        return ParagraphStyle(
            name, fontName=fn, fontSize=fs, textColor=color,
            alignment=align, leading=leading or fs * 1.45, **kw
        )

    def P(txt, style):
        return Paragraph(str(txt) if txt is not None else '', style)

    # ── Data extraction ───────────────────────────────────────────────────────
    from decimal import Decimal
    rupee     = '\u20b9'
    # helper to ensure rupee uses DejaVu glyph in Paragraphs
    def money(amount):
        try:
            return f"<font name='DejaVu'>{rupee}</font> {format_inr(amount)}"
        except Exception:
            return f"{rupee} {format_inr(amount)}"
    today     = datetime.now().strftime('%d-%m-%Y')
    cust      = quotation.customer
    remaining = Decimal(str(quotation.total)) - Decimal(str(advance_amount))

    # COMPANY DATA
    comp = getattr(quotation, 'company', None)
    if comp:
        logo_name   = getattr(comp, 'logo_path', None) or 'logo.png'
        comp_display = (getattr(comp, 'name', '') or 'SATYAM ALUMINIUM')
        comp_tagline = getattr(comp, 'tagline', '')
        comp_addr    = getattr(comp, 'address', '')
        comp_contact = getattr(comp, 'phone', '')
        comp_email   = getattr(comp, 'email', '')
        comp_gstin   = getattr(comp, 'gstin', '')
    else:
        logo_name   = 'logo.png'
        comp_display = 'SATYAM ALUMINIUM'
        comp_tagline = ''
        comp_addr    = ("Shop No. 4, Ganesh Plaza, Ganesh Plaza, Gokul Road, Hubballi 580030")
        comp_contact = "+91 8073709478 | +91 9448442717 | +91 9591291155"
        comp_email   = 'satyamaluminiumhubli@gmail.com'
        comp_gstin   = '29ADRPR1399D1ZX'

    filename = f"Acknowledgement_{cust.name}_{today}.pdf"
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    # ── Page setup — Portrait A4 ──────────────────────────────────────────────
    PAGE_SIZE = A4                         # 595.3 × 841.9 pt  — PORTRAIT
    PAGE_FULL = A4[0]                      # 595.3 pt
    PAGE_H    = A4[1]                      # 841.9 pt
    L_MARGIN  = 36
    R_MARGIN  = 36
    PAGE_W    = PAGE_FULL - L_MARGIN - R_MARGIN   # ~523.3 pt usable

    doc = SimpleDocTemplate(
        response,
        pagesize=PAGE_SIZE,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=36, bottomMargin=44,
    )

    # ── Logo resolution ───────────────────────────────────────────────────────
    # Resolve logo using the configured logo_name (falls back to static/logo.png)
    logo_path = None
    try:
        logo_path = finders.find(logo_name) if logo_name else None
    except Exception as e:
        logger.exception('Logo load error: %s', e)
    if not logo_path:
        try:
            logo_path = finders.find('logo.png')
        except Exception:
            logo_path = None
    if not logo_path:
        fb = os.path.join(settings.BASE_DIR, 'static', 'logo.png')
        if os.path.exists(fb):
            logo_path = fb

    # ══════════════════════════════════════════════════════════════════════════
    # CUSTOM CANVAS — cream page tint + diagonal watermark + footer bar
    # Painted AFTER page content so they always overlay correctly.
    # ══════════════════════════════════════════════════════════════════════════
    _total_holder = [1]
    _wm_text      = comp_display.upper()

    class _LuxuryCanvas(_BaseCanvas):
        def showPage(self):
            self._overlays()
            super().showPage()
        def save(self):
            self._overlays()
            super().save()

        def _overlays(self):
            pw, ph = PAGE_FULL, PAGE_H
            lm = L_MARGIN
            self.saveState()

            # Subtle cream page-background tint
            self.setFillColor(CREAM_BG)
            self.setFillAlpha(0.18)
            self.rect(0, 0, pw, ph, fill=1, stroke=0)

            # Diagonal watermark
            self.setFillColor(BROWN)
            self.setFillAlpha(0.04)
            self.setFont(F_COMPANY, 56)
            self.translate(pw / 2, ph / 2)
            self.rotate(35)
            tw = self.stringWidth(_wm_text, F_COMPANY, 56)
            self.drawString(-tw / 2, 0, _wm_text)
            self.rotate(-35)
            self.translate(-pw / 2, -ph / 2)

            # Footer bar
            self.setFillAlpha(1.0)
            fy, fh = 8, 22
            bar_w  = pw - lm * 2

            self.setFillColor(BROWN)
            self.roundRect(lm, fy, bar_w, fh, 3, fill=1, stroke=0)

            # Gold separator line atop footer bar
            self.setStrokeColor(ACCENT)
            self.setLineWidth(1.2)
            self.line(lm, fy + fh, lm + bar_w, fy + fh)

            pg  = self.getPageNumber()
            tot = _total_holder[0]

            # Left — company name
            self.setFillColor(WHITE)
            self.setFont(F_HEADING, 6.5)
            self.drawString(lm + 8, fy + 8, _wm_text)

            # Centre — system note + GSTIN
            self.setFillColor(colors.HexColor('#B8A898'))
            self.setFont(F_BODY, 5.5)
            note = (f"Computer-generated acknowledgement  \u00B7  "
                    f"No signature required  \u00B7  GSTIN: {comp_gstin}")
            nw = self.stringWidth(note, F_BODY, 5.5)
            self.drawString((pw - nw) / 2, fy + 8, note)

            # Right — page number
            self.setFillColor(ACCENT_PALE)
            self.setFont(F_HEADING, 6.5)
            pg_txt = f"Page {pg} of {tot}"
            pgw    = self.stringWidth(pg_txt, F_HEADING, 6.5)
            self.drawString(pw - lm - pgw - 8, fy + 8, pg_txt)

            self.restoreState()

    class _CountCanvas(_LuxuryCanvas):
        """Silent pass — skip painting during page-count phase."""
        def _overlays(self):
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # BUILD FLOWABLES
    # ══════════════════════════════════════════════════════════════════════════
    def _build_elements():
        elems = []

        # ── Paragraph Styles ─────────────────────────────────────────────────
        s_co_name   = ps('cn',  F_COMPANY,  20,  WHITE,         TA_LEFT,  24)
        s_tagline   = ps('tl',  F_BODY,      8,  ACCENT_PALE,   TA_LEFT,  12)
        s_info_hdr  = ps('ih',  F_BODY,      7.5,colors.HexColor('#B8A898'), TA_LEFT, 11)
        s_doc_title = ps('dt',  F_HEADING,  11,  WHITE,         TA_RIGHT, 14)
        s_doc_sub   = ps('ds',  F_BODY,      8,  ACCENT_PALE,   TA_RIGHT, 12)
        s_meta_lbl = ps(
            'ml',
            F_BODY,
            8,
            WHITE,
            TA_RIGHT,
            11
        )
        s_meta_val  = ps('mv',  F_BOLD,      8.5, WHITE,         TA_LEFT, 12)
        s_meta_val_sm = ps('mvs', F_BOLD,    7.5, WHITE,        TA_LEFT, 11)
        s_label     = ps('lb',  F_BOLD,      9,  TEXT,          TA_LEFT,  13)
        s_value     = ps('vl',  F_BODY,      9,  TEXT,          TA_LEFT,  13)
        s_value_r   = ps('vr',  F_BODY,      9,  TEXT,          TA_RIGHT, 13)
        s_value2    = ps('v2',  F_BODY,      8.5,TEXT2,         TA_CENTER,  12)
        s_th        = ps('th',  F_HEADING,   8,  WHITE,         TA_LEFT,  12)
        s_th_r      = ps('thr', F_HEADING,   8,  WHITE,         TA_RIGHT, 12)
        s_th_c      = ps('thc', F_HEADING,   8,  WHITE,         TA_CENTER,12)
        s_ok_val    = ps('ok',  F_BOLD,      9,  SUCCESS_TXT,   TA_CENTER,13)
        s_bal_lbl   = ps('bll', F_BOLD,      9,  DANGER_TXT,    TA_LEFT,  13)
        s_bal_val   = ps('bv',  F_BOLD,     10,  DANGER_TXT,    TA_RIGHT, 14)
        s_due_val   = ps('dv',  F_BODY,      8.5,TEXT2,         TA_CENTER,12)
        s_gt_lbl    = ps('gl',  F_HEADING,  10,  WHITE,         TA_LEFT,  14)
        s_gt_val    = ps('gv',  F_BOLD,     11,  WHITE,         TA_RIGHT, 15)
        s_cfm_h     = ps('ch',  F_HEADING,  11,  BROWN,         TA_CENTER,15, spaceAfter=4)
        s_cfm_b     = ps('cb',  F_BODY,      9,  TEXT,          TA_LEFT,14)
        s_footer    = ps('ft',  F_ITALIC,    7,  TEXT3,         TA_CENTER,11)
        s_bank_h    = ps('bkh', F_HEADING,   8,  BROWN,         TA_LEFT,  12, letterSpacing=1.5)
        s_bank      = ps('bk',  F_BODY,      9,  TEXT2,         TA_LEFT,  13)
        s_sec_lbl   = ps('sl',  F_HEADING,   8,  ACCENT,        TA_LEFT,  12,
                         letterSpacing=2.5, spaceAfter=0)

        # ════════════════════════════════════════════════════════════════════
        # 1. HEADER BAND
        #    Portrait layout (PAGE_W ≈ 523 pt):
        #    [LOGO 56] [gap 6] [divider 1] [gap 6] [COMPANY comp_w] [RIGHT right_w]
        #    right_w = 150 pt  — "ACKNOWLEDGEMENT" @ 13pt Poppins-Bold fits ✓
        # ════════════════════════════════════════════════════════════════════
        LOGO_W  = 56
        GAP_L   = 6
        DIV_W   = 1
        GAP_R   = 6
        RIGHT_W = 220
        COMP_W  = PAGE_W - LOGO_W - GAP_L - DIV_W - GAP_R - RIGHT_W

        # Gold vertical divider
        div_cell = Table([[Spacer(1, 1)]], colWidths=[DIV_W])
        div_cell.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(-1,-1), ACCENT),
            ('LEFTPADDING',   (0,0),(-1,-1), 0),
            ('RIGHTPADDING',  (0,0),(-1,-1), 0),
            ('TOPPADDING',    (0,0),(-1,-1), 0),
            ('BOTTOMPADDING', (0,0),(-1,-1), 0),
        ]))

        # Logo: use image if available, else dark-brown monogram box
        if logo_path:
            from reportlab.platypus import Image as _Img
            logo_elem = _Img(logo_path, width=LOGO_W, height=LOGO_W)
        else:
            _initials = ''.join(w[0].upper() for w in comp_display.split()[:2])
            logo_elem = Table(
                [[P(f"<b>{_initials}</b>",
                    ps('li', F_HEADING, 20, ACCENT_PALE, TA_CENTER, 24))]],
                colWidths=[LOGO_W]
            )
            logo_elem.setStyle(TableStyle([
                ('BACKGROUND',    (0,0),(-1,-1), colors.HexColor('#3A2418')),
                ('TOPPADDING',    (0,0),(-1,-1), 14),
                ('BOTTOMPADDING', (0,0),(-1,-1), 14),
                ('LEFTPADDING',   (0,0),(-1,-1), 0),
                ('RIGHTPADDING',  (0,0),(-1,-1), 0),
                ('ROUNDEDCORNERS',[4]),
            ]))

        # Company info block (left/centre of header)
        comp_block = Table([
            [P(f"<b>{comp_display.upper()}</b>", s_co_name)],
            [Spacer(1, 3)],
            [P(comp_tagline, s_tagline)],
            [Spacer(1, 8)],
                [P(f"<font size='7.5' color='#B8A898'>{comp_addr}</font>", s_info_hdr)],
                [P(f"<font size='7.5' color='#B8A898'>{comp_contact}</font>", s_info_hdr)],
                [P(f"<font size='7.5' color='#B8A898'>{comp_email}</font>", s_info_hdr)],
        ], colWidths=[COMP_W])
        comp_block.setStyle(TableStyle([
            ('LEFTPADDING',  (0,0),(-1,-1), 0),
            ('RIGHTPADDING', (0,0),(-1,-1), 0),
            ('TOPPADDING',   (0,0),(-1,-1), 0),
            ('BOTTOMPADDING',(0,0),(-1,-1), 0),
            ('VALIGN',       (0,0),(-1,-1), 'TOP'),
        ]))

        # Meta grid: single-column DATE / GSTIN / ORDER aligned under title
        meta_grid = Table([
            [P(f"DATE:<b>{today}</b>", s_meta_lbl)],
            [P(f"GSTIN:<b>{comp_gstin}</b>", s_meta_lbl)],
            [P(f"ORDER:<b>O-{order.id}</b>", s_meta_lbl)],
        ], colWidths=[RIGHT_W])

        meta_grid.setStyle(TableStyle([
            ('LEFTPADDING',(0,0),(-1,-1),0),
            ('RIGHTPADDING',(0,0),(-1,-1),0),
            ('TOPPADDING',(0,0),(-1,-1),0),
            ('BOTTOMPADDING',(0,0),(-1,-1),0),
            ('ALIGN',(0,0),(-1,-1),'RIGHT'),
        ]))

        # Right block: document title + meta
        right_block = Table([
            [P("ACKNOWLEDGEMENT",                           s_doc_title)],
            [P(f"Advance Receipt  \u00B7  Q-{quotation.id}", s_doc_sub)],
            [Spacer(1, 10)],
            [meta_grid],
        ], colWidths=[RIGHT_W])
        right_block.setStyle(TableStyle([
            ('LEFTPADDING',  (0,0),(-1,-1), 0),
            ('RIGHTPADDING', (0,0),(-1,-1), 0),
            ('TOPPADDING',   (0,0),(-1,-1), 0),
            ('BOTTOMPADDING',(0,0),(-1,-1), 0),
            ('VALIGN',       (0,0),(-1,-1), 'TOP'),
            ('ALIGN',        (0,0),(-1,-1), 'RIGHT'),
        ]))
        # Assemble header row — account for header band horizontal padding
        HEADER_PAD_LR = 14 * 2  # left+right padding applied on header_band
        INNER_W = PAGE_W - HEADER_PAD_LR
        # recompute column widths to fit inner available width exactly
        COMP_W = INNER_W - (LOGO_W + GAP_L + DIV_W + GAP_R + RIGHT_W)

        header_inner = Table(
            [[logo_elem, Spacer(GAP_L,1), div_cell, Spacer(GAP_R,1),
              comp_block, right_block]],
            colWidths=[LOGO_W, GAP_L, DIV_W, GAP_R, COMP_W, RIGHT_W]
        )
        header_inner.setStyle(TableStyle([
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('LEFTPADDING',   (0,0),(-1,-1), 0),
            ('RIGHTPADDING',  (0,0),(-1,-1), 0),
            ('TOPPADDING',    (0,0),(-1,-1), 0),
            ('BOTTOMPADDING', (0,0),(-1,-1), 0),
            ('ALIGN', (-1,0), (-1,0), 'RIGHT'),
        ]))

        header_band = Table([[header_inner]], colWidths=[PAGE_W])
        header_band.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(-1,-1), BROWN),
            ('LEFTPADDING',   (0,0),(-1,-1), 14),
            ('RIGHTPADDING',  (0,0),(-1,-1), 14),
            ('TOPPADDING',    (0,0),(-1,-1), 14),
            ('BOTTOMPADDING', (0,0),(-1,-1), 14),
            ('LINEBELOW',     (0,0),(-1,-1), 2.5, ACCENT),
            ('ROUNDEDCORNERS',[6]),
        ]))
        elems.append(header_band)
        elems.append(Spacer(1, 10))

        # ════════════════════════════════════════════════════════════════════
        # 2. CUSTOMER & ORDER DETAIL CARDS — equal two-column layout
        # ════════════════════════════════════════════════════════════════════
        GAP_CARDS = 10
        CARD_W    = (PAGE_W - GAP_CARDS) / 2

        def _card_header(title, cw):
            h = Table([[
                P(title, ps(f'sh_{title}', F_HEADING, 7, ACCENT, TA_LEFT, 10,
                            letterSpacing=1.5))
            ]], colWidths=[cw])
            h.setStyle(TableStyle([
                ('BACKGROUND',    (0,0),(-1,-1), CREAM_DEEP),
                ('LINEBELOW',     (0,0),(-1,-1), 1.5, ACCENT),
                ('TOPPADDING',    (0,0),(-1,-1), 7),
                ('BOTTOMPADDING', (0,0),(-1,-1), 7),
                ('LEFTPADDING',   (0,0),(-1,-1), 12),
                ('RIGHTPADDING',  (0,0),(-1,-1), 12),
            ]))
            return h

        def _info_card(title, rows_data, cw):
            LW = cw * 0.40
            VW = cw * 0.60
            hdr = _card_header(title, cw)
            tbl_rows = [[P(lbl, s_label), P(str(val), s_value)]
                        for lbl, val in rows_data]
            body_styles = [
                ('VALIGN',        (0,0),(-1,-1), 'TOP'),
                ('TOPPADDING',    (0,0),(-1,-1), 7),
                ('BOTTOMPADDING', (0,0),(-1,-1), 7),
                ('LEFTPADDING',   (0,0),(-1,-1), 12),
                ('RIGHTPADDING',  (0,0),(-1,-1), 12),
                ('LINEBELOW',     (0,0),(-1,-2), 0.4, BORDER),
            ]
            for i in range(len(tbl_rows)):
                body_styles.append(('BACKGROUND', (0,i),(-1,i),
                                     CREAM_CARD if i%2==0 else WHITE))
            body = Table(tbl_rows, colWidths=[LW, VW])
            body.setStyle(TableStyle(body_styles))
            card = Table([[hdr],[body]], colWidths=[cw])
            card.setStyle(TableStyle([
                ('BOX',           (0,0),(-1,-1), 0.75, BORDER),
                ('LEFTPADDING',   (0,0),(-1,-1), 0),
                ('RIGHTPADDING',  (0,0),(-1,-1), 0),
                ('TOPPADDING',    (0,0),(-1,-1), 0),
                ('BOTTOMPADDING', (0,0),(-1,-1), 0),
                ('ROUNDEDCORNERS',[4]),
            ]))
            return card

        cust_card  = _info_card("CUSTOMER DETAILS", [
            ("Name",    getattr(cust, 'name',    '\u2014')),
            ("Phone",   getattr(cust, 'phone',   '\u2014')),
            ("Address", getattr(cust, 'address', '\u2014')),
        ], CARD_W)

        order_card = _info_card("ORDER DETAILS", [
            ("Quotation No.", f"Q-{quotation.id}"),
            ("Order No.",     f"O-{order.id}"),
            ("Date",          today),
            ("Order Total",   money(quotation.total)),
        ], CARD_W)

        cards_row = Table([[cust_card, order_card]],
                          colWidths=[CARD_W, CARD_W])
        cards_row.setStyle(TableStyle([
            ('LEFTPADDING',  (0,0),(-1,-1), 0),
            ('RIGHTPADDING', (0,0),(-1,-1), 0),
            ('TOPPADDING',   (0,0),(-1,-1), 0),
            ('BOTTOMPADDING',(0,0),(-1,-1), 0),
            ('VALIGN',       (0,0),(-1,-1), 'TOP'),
            ('RIGHTPADDING', (0,0),(0,-1),  GAP_CARDS),
        ]))
        elems.append(cards_row)
        elems.append(Spacer(1, 12))

        # ════════════════════════════════════════════════════════════════════
        # 3. PAYMENT SUMMARY — section label + gold rule
        # ════════════════════════════════════════════════════════════════════
        elems.append(P("PAYMENT SUMMARY", s_sec_lbl))
        elems.append(HRFlowable(
            width="100%", thickness=1.5, color=ACCENT,
            spaceBefore=4, spaceAfter=8
        ))

        # ════════════════════════════════════════════════════════════════════
        # 4. PAYMENT TABLE
        #    Columns: Description (44%) | Amount (30%) | Status (26%)
        # ════════════════════════════════════════════════════════════════════
        C1 = PAGE_W * 0.44
        C2 = PAGE_W * 0.30
        C3 = PAGE_W - C1 - C2

        pay_rows = [
            # ── Header row ──
            [P("DESCRIPTION",             s_th),
             P("AMOUNT",                  s_th_r),
             P("STATUS",                  s_th_c)],
            # ── Row 1: Order Total ──
            [P("Order Total",             s_value),
             P(money(quotation.total), s_value_r),
             P("\u2014",                  s_value2)],
            # ── Row 2: Advance Received ──
                        [P("Advance Payment Received", s_label),
                         P(money(advance_amount), s_value_r),
                         P("Received ✓", s_ok_val)],
            # ── Row 3: Balance Remaining ──
            [P("Balance Remaining",        s_bal_lbl),
             P(money(remaining), s_bal_val),
             P("Due on Delivery",          s_due_val)],
        ]

        pay_tbl = Table(pay_rows, colWidths=[C1, C2, C3])
        pay_tbl.setStyle(TableStyle([
            # Header row styling
            ('BACKGROUND',    (0,0),(-1,0),  BROWN),
            ('LINEBELOW',     (0,0),(-1,0),  2, ACCENT),
            ('TOPPADDING',    (0,0),(-1,0),  9),
            ('BOTTOMPADDING', (0,0),(-1,0),  9),
            # All data rows
            ('TOPPADDING',    (0,1),(-1,-1), 9),
            ('BOTTOMPADDING', (0,1),(-1,-1), 9),
            ('LEFTPADDING',   (0,0),(-1,-1), 11),
            ('RIGHTPADDING',  (0,0),(-1,-1), 11),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            # Column alignments
            ('ALIGN',         (1,0),(1,-1),  'RIGHT'),   # Amount — right
            ('ALIGN',         (2,0),(2,-1),  'CENTER'),  # Status — centre
            # Row dividers
            ('LINEBELOW',     (0,1),(-1,-2), 0.4, BORDER),
            # Row backgrounds
            ('BACKGROUND',    (0,1),(-1,1),  WHITE),
            ('BACKGROUND',    (0,2),(-1,2),  CREAM_CARD),
            ('BACKGROUND',    (0,3),(-1,3),  colors.HexColor('#FDF6F6')),
            # Outer border
            ('BOX',           (0,0),(-1,-1), 0.75, BORDER),
            ('ROUNDEDCORNERS',[4]),
        ]))
        elems.append(pay_tbl)
        elems.append(Spacer(1, 8))

        # ════════════════════════════════════════════════════════════════════
        # 5. ADVANCE PAID GRAND TOTAL STRIP — flush right, 52% width
        # ════════════════════════════════════════════════════════════════════
        GT_W     = PAGE_W * 0.52
        SPACE_W  = PAGE_W - GT_W

        gt_inner = Table(
            [[P("ADVANCE PAID",                              s_gt_lbl),
              P(money(advance_amount),    s_gt_val)]],
            colWidths=[GT_W * 0.46, GT_W * 0.54]
        )
        gt_inner.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(-1,-1), BROWN),
            ('LINEABOVE',     (0,0),(-1,-1), 2, ACCENT),
            ('TOPPADDING',    (0,0),(-1,-1), 10),
            ('BOTTOMPADDING', (0,0),(-1,-1), 10),
            ('LEFTPADDING',   (0,0),(-1,-1), 14),
            ('RIGHTPADDING',  (0,0),(-1,-1), 14),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('ALIGN',         (1,0),(1,0),   'RIGHT'),
            ('ROUNDEDCORNERS',[4]),
        ]))
        gt_wrap = Table([[Spacer(1,1), gt_inner]], colWidths=[SPACE_W, GT_W])
        gt_wrap.setStyle(TableStyle([
            ('LEFTPADDING',  (0,0),(-1,-1), 0),
            ('RIGHTPADDING', (0,0),(-1,-1), 0),
            ('TOPPADDING',   (0,0),(-1,-1), 0),
            ('BOTTOMPADDING',(0,0),(-1,-1), 0),
            ('VALIGN',       (0,0),(-1,-1), 'TOP'),
        ]))
        elems.append(gt_wrap)
        elems.append(Spacer(1, 12))

        # ════════════════════════════════════════════════════════════════════
        # 6. CONFIRMATION CARD
        #    Cream background with gold top-accent line and brown border.
        # ════════════════════════════════════════════════════════════════════
        confirm_message = f"""
    • Advance payment of <b>{money(advance_amount)}</b> has been successfully received.<br/><br/>

    • Your order has been confirmed and work is currently in progress.<br/><br/>

    • Remaining balance payable: <b>{money(remaining)}</b>.<br/><br/>

    • Balance amount shall be paid as per agreed terms and conditions.
    """

        confirm_tbl = Table([
            [P(f"Thank you for choosing {comp_display}!", s_cfm_h)],
            [P(confirm_message, s_cfm_b)],
        ], colWidths=[PAGE_W])
        confirm_tbl.setStyle(TableStyle([
            ('BOX',           (0,0),(-1,-1), 1, BORDER),
            ('LINEABOVE',     (0,0),(-1,0),  3, ACCENT),
            ('BACKGROUND',    (0,0),(-1,-1), CREAM_CARD),
            ('TOPPADDING',    (0,0),(-1,-1), 14),
            ('BOTTOMPADDING', (0,0),(-1,-1), 14),
            ('LEFTPADDING',   (0,0),(-1,-1), 20),
            ('RIGHTPADDING',  (0,0),(-1,-1), 20),
            ('ROUNDEDCORNERS',[4]),
        ]))
        elems.append(confirm_tbl)
        elems.append(Spacer(1, 12))

        # ════════════════════════════════════════════════════════════════════
        # 8. FOOTER NOTE  (sits above the canvas footer bar)
        # ════════════════════════════════════════════════════════════════════
        elems.append(HRFlowable(
            width='100%', thickness=0.5, color=BORDER,
            spaceBefore=0, spaceAfter=6
        ))
        elems.append(P(
            'This is a computer-generated acknowledgement and does not '
            'require a physical signature.',
            s_footer
        ))
        elems.append(P(
            f'Generated on {today}  \u00B7  {comp_display}  \u00B7  {comp_email}',
            s_footer
        ))
        return elems

    # ══════════════════════════════════════════════════════════════════════════
    # TWO-PASS BUILD  — pass 1 counts pages, pass 2 renders with overlays
    # ══════════════════════════════════════════════════════════════════════════
    _buf = _io.BytesIO()
    _doc_count = SimpleDocTemplate(
        _buf, pagesize=PAGE_SIZE,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=36, bottomMargin=44,
    )
    _doc_count.build(_build_elements(), canvasmaker=_CountCanvas)
    try:
        _total_holder[0] = max(1, _buf.getvalue().count(b'/Type /Page'))
    except Exception:
        _total_holder[0] = 1

    # Build final PDF into memory buffer so we can trim extra pages if needed
    out_buf = _io.BytesIO()
    _doc_out = SimpleDocTemplate(
        out_buf, pagesize=PAGE_SIZE,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=36, bottomMargin=44,
    )
    _doc_out.build(_build_elements(), canvasmaker=_LuxuryCanvas)
    pdf_bytes = out_buf.getvalue()

    # If pypdf / PyPDF2 is available, trim to first page to avoid useless blank pages
    try:
        try:
            from pypdf import PdfReader, PdfWriter
        except Exception:
            from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(_io.BytesIO(pdf_bytes))
        if len(reader.pages) > 1:
            writer = PdfWriter()
            writer.add_page(reader.pages[0])
            trimmed = _io.BytesIO()
            writer.write(trimmed)
            pdf_bytes = trimmed.getvalue()
    except Exception:
        # If trimming not possible, return full PDF as-is
        pass

    response.write(pdf_bytes)
    return response

def get_ram_usage():
    """Return simple RAM usage info (MB) and percent for quick dashboard display."""
    logger = logging.getLogger(__name__)
    try:
        process = psutil.Process(os.getpid())
        ram_used = process.memory_info().rss / 1024 / 1024  # MB
    except (psutil.Error, OSError, AttributeError) as e:
        logger.exception('Could not get RAM usage: %s', e)
        ram_used = 0.0

    total_ram = 512  # default / approximate for Render free plan
    percent = (ram_used / total_ram) * 100 if total_ram else 0

    return {
        "used": round(ram_used, 2),
        "total": total_ram,
        "percent": round(percent, 2),
        "is_high": ram_used > 300,
    }