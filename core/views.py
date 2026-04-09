from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from decimal import Decimal, InvalidOperation
import re
import os
from datetime import datetime

import openpyxl
from django.conf import settings
from django.contrib.staticfiles import finders
from io import BytesIO
from django.db import transaction

from .utils import generate_advance_acknowledgement_pdf
from .models import (
    Customer, Order, Employee, Attendance, Payment,
    Service, Quotation, QuotationItem, OrderPayment, TermCondition,
    QuotationTerm, Measurement, MeasurementItem, MeasurementSubItem,
)

# ReportLab imports (used across multiple views)
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
    number = float(number)
    s = f"{number:.2f}"
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


# ================= FONT / LOGO HELPERS =================
def _load_unicode_font():
    """Register and return DejaVuSans font for rupee rendering.

    Uses settings.BASE_DIR to locate the font at <BASE_DIR>/fonts/DejaVuSans.ttf.
    Raises FileNotFoundError with a helpful message if the font file is missing.
    Ensures the font is registered only once.
    Returns (font_name, '₹').
    """
    font_name = 'DejaVuSans'
    # try project-local fonts folder first
    candidates = []
    try:
        candidates.append(os.path.join(settings.BASE_DIR, 'fonts', 'DejaVuSans.ttf'))
    except Exception:
        pass
    # common linux locations
    candidates += [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    ]
    # windows fonts folder
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
        except Exception:
            pass

    # fallback to built-in Helvetica if DejaVu is not available
    return 'Helvetica', 'Rs.'


def _register_times_new_roman():
    """Attempt to register Times New Roman cross-platform.

    Returns the registered font name on success, or None if not available.
    Falls back silently to DejaVuSans when not found.
    """
    candidates = []
    # Windows
    windir = os.environ.get('WINDIR')
    if windir:
        candidates += [os.path.join(windir, 'Fonts', x) for x in (
            'Times New Roman.ttf', 'TimesNewRoman.ttf', 'times.ttf', 'timesbd.ttf')]
    # macOS
    candidates += [
        '/Library/Fonts/Times New Roman.ttf',
        '/System/Library/Fonts/Supplemental/Times New Roman.ttf'
    ]
    # Common Linux locations
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
        except Exception:
            continue
    return None


def _load_logo_image(width=100, height=100, circular=False):
    """Locate logo.png using staticfiles finders or fallback to <BASE_DIR>/static/logo.png.

    Returns a ReportLab Image object sized to (width, height) or a Spacer if not found.
    If circular=True, tries to apply a circular crop using Pillow; if Pillow unavailable or
    fails, returns the rectangular image gracefully.
    """
    from reportlab.platypus import Image as RLImage, Spacer as RLSpacer

    logo_name = 'logo.png'
    logo_path = finders.find(logo_name) if finders else None
    if not logo_path:
        candidate = settings.BASE_DIR / 'static' / logo_name
        if candidate.exists():
            logo_path = str(candidate)

    if not logo_path or not os.path.exists(logo_path):
        return RLSpacer(width, height)

    if circular:
        try:
            from PIL import Image as PILImage, ImageDraw
            img = PILImage.open(logo_path).convert('RGBA')
            size = max(img.size)
            square = PILImage.new('RGBA', (size, size), (255, 255, 255, 0))
            offset = ((size - img.width) // 2, (size - img.height) // 2)
            square.paste(img, offset)
            mask = PILImage.new('L', (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            square.putalpha(mask)
            buf = BytesIO()
            square.save(buf, format='PNG')
            buf.seek(0)
            return RLImage(buf, width=width, height=height)
        except Exception:
            pass

    try:
        return RLImage(str(logo_path), width=width, height=height)
    except Exception:
        return RLSpacer(width, height)


def clean_text(text):
    if not text:
        return ''
    return re.sub(r'[^\w\s,.\-]', '', text)


# ================= SALARY PDF HELPERS (module-level) =================
GOLD   = colors.HexColor('#B8962E')
DARK   = colors.HexColor('#0D1B2A')
CREAM  = colors.HexColor('#F7F4EF')
RULE   = colors.HexColor('#D4C5A0')
RED    = colors.HexColor('#8B1A1A')
GREEN  = colors.HexColor('#1A6B2B')
GREY   = colors.HexColor('#777777')
LGREY  = colors.HexColor('#888888')
WHITE  = colors.white

_FONTS_REGISTERED = False


def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    try:
        pdfmetrics.registerFont(
            TTFont('DejaVuSans',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(
            TTFont('DejaVuSans-Bold',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
    except Exception:
        pass
    _FONTS_REGISTERED = True


def _get_fonts():
    """Return (data_font, data_bold, rupee_char) after registering TTFs."""
    _register_fonts()
    try:
        pdfmetrics.getFont('DejaVuSans')
        return 'DejaVuSans', 'DejaVuSans-Bold', '₹'
    except Exception:
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
        f"<font name='Times-Bold' size='12' color='#0D1B2A'>{text}</font>",
        _ps('_sh', 'Times-Bold', 12, TA_LEFT, DARK),
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
        val = Decimal(str(amount)).quantize(Decimal('0.01'))
        s = f"{val:,.2f}"
        return f"{rupee} {s}"
    except Exception:
        return f"{rupee} {amount}"


# ================= DASHBOARD =================
def dashboard(request):
    return render(request, 'dashboard.html', {
        'customers': Customer.objects.count(),
        'orders': Order.objects.count(),
        'employees': Employee.objects.count()
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


def register_user(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        username = request.POST.get('username')
        if User.objects.filter(username=username).exists():
            return render(request, 'register.html', {
                'error': 'User already exists'
            })
        User.objects.create_user(
            username=username,
            password=request.POST.get('password')
        )
        return redirect('login')
    return render(request, 'register.html')


def logout_user(request):
    logout(request)
    return redirect('login')


# ================= CUSTOMERS =================
@login_required(login_url='/login/')
def customers(request):
    return render(request, 'customers.html', {
        'data': Customer.objects.all().order_by('-id')
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
            return JsonResponse({
                'status': 'success',
                'message': 'Customer added successfully',
                'customer': {'id': customer.id, 'name': customer.name, 'phone': customer.phone}
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
        'customers': Customer.objects.all().order_by('-id')
    })


@login_required(login_url='/login/')
def take_measurements(request, cust_id):
    customer = get_object_or_404(Customer, id=cust_id)
    return render(request, 'take_measurements.html', {'customer': customer})


@login_required(login_url='/login/')
def save_measurements(request, cust_id):
    """Save measurement data. Expects JSON body with structure:
    { items: [ {description, item_type, unit, subs: [{height, width, quantity}] } ] }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    import json
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    customer = get_object_or_404(Customer, id=cust_id)

    with transaction.atomic():
        existing_qs = Measurement.objects.filter(customer=customer).order_by('-id')
        if existing_qs.exists():
            m = existing_qs.first()
            try:
                existing_qs.exclude(id=m.id).delete()
            except Exception:
                pass
        else:
            m = Measurement.objects.create(customer=customer)

        m.items.all().delete()

        for item in payload.get('items', []):
            desc = item.get('description') or 'Item'
            item_type = item.get('item_type') or MeasurementItem.SIZE
            unit = item.get('unit') or 'Sq Ft'

            service = None
            service_id = item.get('service_id')
            if service_id:
                try:
                    service = Service.objects.get(id=int(service_id))
                except Exception:
                    service = None

            custom_name = item.get('custom_item_name') or None

            try:
                ppu = Decimal(str(item.get('price_per_unit') or '0'))
            except Exception:
                ppu = Decimal('0')

            mi = MeasurementItem.objects.create(
                measurement=m,
                description=desc,
                item_type=item_type,
                unit=unit,
                service=service,
                custom_item_name=custom_name,
                price_per_unit=ppu
            )

            total_price = Decimal('0')

            for sub in item.get('subs', []):
                try:
                    h_val = float(sub.get('height')) if sub.get('height') not in (None, '') else None
                except Exception:
                    h_val = None
                try:
                    w_val = float(sub.get('width')) if sub.get('width') not in (None, '') else None
                except Exception:
                    w_val = None
                try:
                    l_val = float(sub.get('length')) if sub.get('length') not in (None, '') else None
                except Exception:
                    l_val = None
                try:
                    qty = int(sub.get('quantity') or sub.get('qty') or 1)
                except Exception:
                    qty = 1

                try:
                    h_dec = Decimal(str(h_val)) if h_val is not None else None
                except Exception:
                    h_dec = None
                try:
                    w_dec = Decimal(str(w_val)) if w_val is not None else None
                except Exception:
                    w_dec = None
                try:
                    l_dec = Decimal(str(l_val)) if l_val is not None else None
                except Exception:
                    l_dec = None

                si = MeasurementSubItem.objects.create(
                    item=mi, height=h_dec, width=w_dec, length=l_dec, quantity=qty
                )

                try:
                    if si.height is not None and si.width is not None:
                        area_val = si.height * si.width * Decimal(si.quantity)
                    elif si.length is not None:
                        area_val = si.length * Decimal(si.quantity)
                    else:
                        area_val = Decimal(si.quantity)
                except Exception:
                    area_val = Decimal('0')

                total_price += (area_val * ppu)

            mi.total_price = total_price
            mi.save()

    return JsonResponse({'ok': True, 'measurement_id': m.id})


@login_required(login_url='/login/')
def get_measurements_json(request, cust_id):
    customer = get_object_or_404(Customer, id=cust_id)
    m = Measurement.objects.filter(customer=customer).order_by('-id').first()
    if not m:
        return JsonResponse({'items': []})

    out = []
    for mi in m.items.all():
        subs = []
        for s in mi.subitems.all():
            subs.append({
                'height': float(s.height) if s.height is not None else None,
                'width': float(s.width) if s.width is not None else None,
                'length': float(s.length) if s.length is not None else None,
                'quantity': int(s.quantity)
            })

        qty_val = 0.0
        raw_qty = 0
        for s in mi.subitems.all():
            try:
                if mi.item_type == MeasurementItem.SIZE:
                    if s.height is None or s.width is None:
                        continue
                    qty_val += float(s.height) * float(s.width) * int(s.quantity)
                    raw_qty += int(s.quantity)
                elif mi.item_type == MeasurementItem.LENGTH:
                    if s.length is None:
                        continue
                    qty_val += float(s.length) * int(s.quantity)
                    raw_qty += int(s.quantity)
                else:
                    raw_qty += int(s.quantity)
                    qty_val += int(s.quantity)
            except Exception:
                continue

        out.append({
            'measurement_item_id': mi.id,
            'service_id': mi.service.id if mi.service else None,
            'service_name': mi.service.name if mi.service else None,
            'custom_item_name': mi.custom_item_name,
            'description': mi.description,
            'quantity': round(qty_val, 3) if isinstance(qty_val, float) else qty_val,
            'unit': mi.unit,
            'raw_quantity': raw_qty,
            'price_per_unit': float(mi.price_per_unit or 0),
            'total_price': float(mi.total_price or 0),
            'subs': subs
        })

    return JsonResponse({'items': out})


# ================= SERVICES =================
@login_required(login_url='/login/')
def services(request):
    return render(request, 'services.html', {
        'data': Service.objects.all().order_by('-id')
    })


def services_api(request):
    """Return JSON list of services for AJAX dropdowns."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    qs = Service.objects.all().order_by('name')
    out = [{'id': s.id, 'name': s.name, 'description': s.name, 'price': float(s.price)}
           for s in qs]
    return JsonResponse(out, safe=False)


@login_required(login_url='/login/')
def create_service_api(request):
    """Create a Service via AJAX. Expects JSON or form POST with 'name', optional 'price'."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    data = {}
    try:
        import json
        data = json.loads(request.body.decode('utf-8')) if request.body else request.POST.dict()
    except Exception:
        data = request.POST.dict()

    name = (data.get('name') or '').strip()
    description = (data.get('description') or name).strip()
    price_in = data.get('price') or data.get('price_per_unit') or '0'

    if not name:
        return JsonResponse({'error': 'Name required'}, status=400)

    existing = Service.objects.filter(name__iexact=name).first()
    if existing:
        return JsonResponse({
            'id': existing.id, 'name': existing.name,
            'description': existing.name, 'price': float(existing.price)
        })

    try:
        price = Decimal(str(price_in or '0'))
    except Exception:
        price = Decimal('0')

    s = Service.objects.create(name=name, description=description, price=price)
    return JsonResponse({'id': s.id, 'name': s.name, 'description': s.name, 'price': float(s.price)})


@login_required(login_url='/login/')
def add_service(request):
    if request.method == "POST":
        name = request.POST.get('name')
        desc = name
        price_str = request.POST.get('price')

        if not name or not price_str:
            return render(request, 'add_service.html', {'error': 'Name and Price are required'})

        try:
            price = Decimal(price_str)
        except InvalidOperation:
            return render(request, 'add_service.html', {'error': 'Invalid price format'})

        Service.objects.create(name=name, description=desc, price=price)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Service added successfully'})
        return redirect('services')
    return render(request, 'add_service.html')


@login_required(login_url='/login/')
def edit_service(request, id):
    service = get_object_or_404(Service, id=id)

    if request.method == "POST":
        service.name = request.POST.get('name')
        service.description = service.name
        price_str = request.POST.get('price')

        try:
            service.price = Decimal(price_str)
        except InvalidOperation:
            return render(request, 'edit_service.html', {
                'service': service, 'error': 'Invalid price format'
            })

        service.save()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Service updated successfully'})
        return redirect('services')
    return render(request, 'edit_service.html', {'service': service})


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
    customers = Customer.objects.all()
    quotations = Quotation.objects.all().order_by('-id')
    terms_qs = TermCondition.objects.all()
    default_terms_text = "\n\n".join((t.text for t in terms_qs)) if terms_qs.exists() else ''

    if request.method == "POST":
        customer_id = request.POST.get('customer')
        gst_type = request.POST.get('gst_type', 'with_gst')

        try:
            discount_in = Decimal(request.POST.get('discount') or '0')
        except Exception:
            discount_in = Decimal('0')
        if discount_in < 0:
            discount_in = Decimal('0')

        descriptions = request.POST.getlist('description')
        quantities = request.POST.getlist('quantity')
        units = request.POST.getlist('unit')
        prices = request.POST.getlist('price')

        if not customer_id:
            return render(request, 'create_quotation.html', {
                'customers': customers, 'quotations': quotations,
                'terms': terms_qs, 'error': 'Select a customer'
            })

        customer = get_object_or_404(Customer, id=customer_id)
        quotation = Quotation.objects.create(customer=customer, gst_type=gst_type)
        subtotal = Decimal('0')

        for desc, qty, unit, price in zip(descriptions, quantities, units, prices):
            if not desc or not qty or not price:
                continue
            try:
                qty = Decimal(qty)
                price = Decimal(price)
            except Exception:
                continue

            total = qty * price
            subtotal += total
            QuotationItem.objects.create(
                quotation=quotation, description=desc,
                quantity=int(qty), unit=unit, price=price, total=total
            )

        quotation.subtotal = subtotal
        quotation.discount = discount_in

        if gst_type == "with_gst":
            quotation.cgst = subtotal * Decimal('0.09')
            quotation.sgst = subtotal * Decimal('0.09')
        else:
            quotation.cgst = Decimal('0.00')
            quotation.sgst = Decimal('0.00')

        total_calc = subtotal + quotation.cgst + quotation.sgst if gst_type == 'with_gst' else subtotal
        total_calc = total_calc - quotation.discount
        if total_calc < 0:
            total_calc = Decimal('0.00')
        quotation.total = total_calc

        selected_terms = request.POST.getlist('terms')

        print("DEBUG TERMS:", selected_terms)

        # delete old terms (VERY IMPORTANT)
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

        quotation.custom_terms = request.POST.get('custom_terms')
        tac = request.POST.get('terms_and_conditions', '').strip()
        quotation.terms_and_conditions = tac if tac else default_terms_text
        quotation.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Quotation created', 'quotation_id': quotation.id})
        return redirect('view_quotation', id=quotation.id)

    return render(request, 'create_quotation.html', {
        'customers': customers,
        'quotations': quotations,
        'terms': terms_qs,
        'terms_default': default_terms_text
    })


# ================= VIEW QUOTATION =================
@login_required(login_url='/login/')
def view_quotation(request, id):
    q = get_object_or_404(Quotation, id=id)
    items = QuotationItem.objects.filter(quotation=q)
    # Pass QuotationTerm queryset so template/PDF can access `qt.term` and `qt.order`
    ordered_terms = q.quotation_terms.select_related('term').order_by('order', 'id')

    return render(request, 'view_quotation.html', {
        'q': q,
        'items': items,
        'ordered_terms': ordered_terms,
    })


# ================= EDIT QUOTATION =================
@login_required(login_url='/login/')
def edit_quotation(request, id):
    q = get_object_or_404(Quotation, id=id)
    items = QuotationItem.objects.filter(quotation=q)
    terms_qs = TermCondition.objects.all()
    default_terms_text = "\n\n".join((t.text for t in terms_qs)) if terms_qs.exists() else ''

    if request.method == "POST":
        customer_id = request.POST.get('customer')
        gst_type = request.POST.get('gst_type', q.gst_type)

        try:
            discount_in = Decimal(request.POST.get('discount') or '0')
        except Exception:
            discount_in = Decimal('0')
        if discount_in < 0:
            discount_in = Decimal('0')

        descriptions = request.POST.getlist('description')
        quantities = request.POST.getlist('quantity')
        units = request.POST.getlist('unit')
        prices = request.POST.getlist('price')

        if customer_id:
            try:
                q.customer = get_object_or_404(Customer, id=customer_id)
            except Exception:
                pass

        items.delete()
        subtotal = Decimal('0')

        for desc, qty, unit, price in zip(descriptions, quantities, units, prices):
            if not desc and not qty and not price:
                continue
            try:
                qty_dec = Decimal(qty)
                price_dec = Decimal(price)
            except (InvalidOperation, TypeError):
                continue

            total = qty_dec * price_dec
            subtotal += total
            QuotationItem.objects.create(
                quotation=q, description=desc,
                quantity=int(qty_dec), unit=unit, price=price_dec, total=total
            )

        q.subtotal = subtotal
        q.gst_type = gst_type
        q.discount = discount_in

        if gst_type == "with_gst":
            q.cgst = subtotal * Decimal('0.09')
            q.sgst = subtotal * Decimal('0.09')
        else:
            q.cgst = Decimal('0.00')
            q.sgst = Decimal('0.00')

        total_calc = subtotal + q.cgst + q.sgst if gst_type == 'with_gst' else subtotal
        total_calc = total_calc - q.discount
        if total_calc < 0:
            total_calc = Decimal('0.00')
        q.total = total_calc

        selected_terms = request.POST.getlist('terms')

        print("DEBUG TERMS:", selected_terms)

        # delete old terms (VERY IMPORTANT)
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

        q.custom_terms = request.POST.get('custom_terms')
        tac = request.POST.get('terms_and_conditions', '').strip()
        q.terms_and_conditions = tac if tac else (q.terms_and_conditions or default_terms_text)
        q.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Quotation updated', 'quotation_id': q.id})
        return redirect('create_quotation')

    # Attach selected_order attribute to TermCondition objects for template prefill
    term_orders_map = {qt.term_id: qt.order for qt in q.quotation_terms.all()}
    for t in terms_qs:
        try:
            t.selected_order = term_orders_map.get(t.id, '')
        except Exception:
            t.selected_order = ''

    return render(request, 'create_quotation.html', {
        'customers': Customer.objects.all(),
        'items': items,
        'edit': True,
        'q': q,
        'quotations': Quotation.objects.all().order_by('-id'),
        'terms': terms_qs,
        'terms_default': default_terms_text,
        'term_orders': term_orders_map,
    })


# ================= LIST PAGE =================
@login_required(login_url='/login/')
def quotations(request):
    data = Quotation.objects.all().order_by('-id')
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
        Spacer, HRFlowable, Image, KeepTogether
    )
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
    from reportlab.lib.units import inch
    from datetime import datetime as _dt
    import io

    today_date = _dt.now().strftime("%d-%m-%Y")
    q = get_object_or_404(Quotation, id=id)
    items = QuotationItem.objects.filter(quotation=q)

    customer_name = re.sub(r'[^A-Za-z0-9]+', '_', q.customer.name)
    filename = f"{customer_name}_{today_date}.pdf"

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=40, rightMargin=40,
        topMargin=32, bottomMargin=32,
    )
    page_w = doc.width

    font_name, _ = _load_unicode_font()

    # Palette
    NAVY        = colors.HexColor('#0F2044')
    ACCENT      = colors.HexColor('#2563EB')
    SLATE_LIGHT = colors.HexColor('#F1F5F9')
    BORDER      = colors.HexColor('#CBD5E1')
    _WHITE      = colors.HexColor('#FFFFFF')
    TEXT        = colors.HexColor('#0F172A')
    TEXT2       = colors.HexColor('#334155')
    TEXT3       = colors.HexColor('#64748B')

    def ps(name, font=None, size=9, color=TEXT, align=TA_LEFT, leading=None, **kw):
        f = font or font_name
        return ParagraphStyle(name, fontName=f, fontSize=size, textColor=color,
                              alignment=align, leading=leading or size * 1.45, **kw)

    try:
        tnr_font = _register_times_new_roman()
    except Exception:
        tnr_font = None

    s_co_name  = ps('co_name',  tnr_font or font_name, 22, _WHITE,  TA_LEFT, 26)
    s_tagline  = ps('tagline',  'Helvetica',  9, colors.HexColor('#93C5FD'), TA_LEFT, 12, spaceBefore=2)
    s_info_hdr = ps('info_hdr', 'Helvetica',  8, colors.HexColor('#94A3B8'), TA_LEFT, 11)
    s_doc_title = ps('doc_title', 'Helvetica-Bold', 18, _WHITE, TA_RIGHT, 22)
    s_doc_sub  = ps('doc_sub',  'Helvetica',  9, colors.HexColor('#93C5FD'), TA_RIGHT, 12)
    s_pill_lbl = ps('pill_lbl', 'Helvetica',  7.5, TEXT3, TA_LEFT, 10)
    s_pill_val = ps('pill_val', 'Helvetica-Bold', 10, TEXT, TA_LEFT, 14)
    s_sec_lbl  = ps('sec_lbl',  'Helvetica-Bold', 7.5, ACCENT, TA_LEFT, 10,
                    spaceAfter=2, letterSpacing=1.2)
    s_client_n = ps('client_n', 'Helvetica-Bold', 12, TEXT, TA_LEFT, 16)
    s_client_s = ps('client_s', 'Helvetica', 9, TEXT2, TA_LEFT, 13)
    s_th       = ps('th',  'Helvetica-Bold', 9, _WHITE, TA_CENTER, 11)
    s_th_r     = ps('th_r', 'Helvetica-Bold', 9, _WHITE, TA_RIGHT, 11)
    s_td       = ps('td',  font_name, 9, TEXT,  TA_LEFT,   13)
    s_td_c     = ps('td_c', font_name, 9, TEXT, TA_CENTER, 13)
    s_td_r     = ps('td_r', font_name, 9, TEXT, TA_RIGHT,  13)
    s_sum_lbl  = ps('sum_lbl', font_name,  9, TEXT2, TA_LEFT,  13)
    s_sum_val  = ps('sum_val', font_name,  9, TEXT,  TA_RIGHT, 13)
    s_gtl      = ps('gtl', 'Helvetica-Bold', 10, _WHITE, TA_LEFT,  14)
    s_gtv      = ps('gtv', font_name, 11, _WHITE, TA_RIGHT, 15)
    s_terms    = ps('terms', font_name, 9, TEXT2, TA_LEFT, 14, leftIndent=14, spaceAfter=4)

    def P(text, style):
        return Paragraph(text, style)

    def format_inr_local(n):
        n = float(n)
        s = f"{n:.2f}"
        integer, dec = s.split(".")
        if len(integer) > 3:
            last3 = integer[-3:]
            rest = integer[:-3]
            chunks = ""
            while len(rest) > 2:
                chunks = "," + rest[-2:] + chunks
                rest = rest[:-2]
            integer = rest + chunks + "," + last3
        return f"\u20b9 {integer}.{dec}"

    logo_img = _load_logo_image(width=0.78 * inch, height=0.78 * inch, circular=True)
    elements = []

    # 1. HEADER BAND
    left_info = Table([
        [P("SATYAM ALUMINIUM", s_co_name)],
        [P("PRECISION\u00A0\u2022\u00A0QUALITY\u00A0\u2022\u00A0EXCELLENCE", s_tagline)],
        [Spacer(1, 4)],
        [P("<font size='7.5' color='#94A3B8'>"
           "\u25cf\u00A0 Shop No. 4, Ganesh Plaza, Beside Triveni Bakery, "
           "Nehru Nagar, Gokul Road, Hubballi\u2013580030</font>", s_info_hdr)],
        [P("<font size='7.5' color='#94A3B8'>"
           "\u260e\u00A0 +91\u00A08073709478\u2002|\u2002+91\u00A09448442717"
           "\u2002|\u2002+91\u00A09591291155\u2002\u00A0"
           "\u2709\u00A0satyamaluminiumhubli@gmail.com</font>", s_info_hdr)],
    ], colWidths=[page_w * 0.55])
    left_info.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    right_doc = Table([
        [P("QUOTATION", s_doc_title)],
        [P(f"#{q.id:04d}", s_doc_sub)],
        [Spacer(1, 6)],
        [P(f"<font size='8' color='#93C5FD'>Date:\u00A0</font>"
           f"<font size='9' color='#FFFFFF'><b>{today_date}</b></font>", s_doc_sub)],
        [P(f"<font size='8' color='#93C5FD'>GSTIN:\u00A0</font>"
           f"<font size='9' color='#FFFFFF'><b>29ADRP1399D1ZX</b></font>", s_doc_sub)],
    ], colWidths=[page_w * 0.35 - 0.88 * inch])
    right_doc.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
    ]))

    header_inner = Table(
        [[logo_img, left_info, right_doc]],
        colWidths=[0.88 * inch, page_w * 0.55, page_w * 0.35 - 0.88 * inch]
    )
    header_inner.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (1, 0), (1, 0), 12),
    ]))

    header_band = Table([[header_inner]], colWidths=[page_w])
    header_band.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), NAVY),
        ('LEFTPADDING', (0, 0), (-1, -1), 16), ('RIGHTPADDING', (0, 0), (-1, -1), 16),
        ('TOPPADDING', (0, 0), (-1, -1), 16), ('BOTTOMPADDING', (0, 0), (-1, -1), 16),
        ('ROUNDEDCORNERS', [8]),
    ]))
    elements.append(header_band)
    elements.append(Spacer(1, 14))

    # 2. CLIENT CARD
    gst_label = "With GST (18%)" if q.gst_type == "with_gst" else "Without GST"
    gst_color = "#059669" if q.gst_type == "with_gst" else "#DC2626"
    left_w  = page_w * 0.62
    right_w = page_w * 0.38

    bill_block = Table([
        [P("BILL TO", s_sec_lbl)],
        [P(q.customer.name, s_client_n)],
        [P(q.customer.address or "\u2014", s_client_s)],
    ], colWidths=[left_w - 28])
    bill_block.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    details_block = Table([
        [P("QUOTATION DETAILS", s_sec_lbl)],
        [Table([
            [P("Quotation No.", s_pill_lbl), P(f"Q-{q.id}", s_pill_val)],
            [P("GST Type", s_pill_lbl),
             P(f'<font color="{gst_color}"><b>{gst_label}</b></font>', s_pill_val)],
        ], colWidths=[(right_w - 28) * 0.45, (right_w - 28) * 0.55])],
    ], colWidths=[right_w - 28])
    details_block.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    info_card = Table([[bill_block, details_block]], colWidths=[left_w, right_w])
    info_card.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, BORDER),
        ('LINEAFTER', (0, 0), (0, -1), 0.5, BORDER),
        ('BACKGROUND', (1, 0), (-1, -1), SLATE_LIGHT),
        ('LEFTPADDING', (0, 0), (-1, -1), 14), ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ('TOPPADDING', (0, 0), (-1, -1), 12), ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROUNDEDCORNERS', [6]),
    ]))
    elements.append(info_card)
    elements.append(Spacer(1, 16))

    # 3. ITEMS TABLE
    elements.append(Paragraph("<b>ITEMS &amp; SERVICES</b>",
        ps('sh', 'Helvetica-Bold', 15, NAVY, TA_CENTER, 14, spaceAfter=8)))

    col_sl   = 35
    col_qty  = 80
    col_rate = 95
    col_tot  = 95
    col_desc = page_w - col_sl - col_qty - col_rate - col_tot

    tbl_data = [[
        P("SL", s_th),
        P("DESCRIPTION", s_th),
        P("QTY", s_th),
        P("RATE", s_th_r),
        P("AMOUNT", s_th_r),
    ]]

    subtotal = Decimal("0")
    for i, item in enumerate(items, 1):
        subtotal += Decimal(item.total)
        tbl_data.append([
            P(str(i), s_td_c),
            P(item.description, s_td),
            P(f"{item.quantity}\u00A0{item.unit}", s_td_c),
            P(format_inr_local(item.price), s_td_r),
            P(format_inr_local(item.total), s_td_r),
        ])

    items_tbl = Table(
        tbl_data,
        colWidths=[col_sl, col_desc, col_qty, col_rate, col_tot],
        repeatRows=1
    )
    items_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), _WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), font_name),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),
        ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BOX', (0, 0), (-1, -1), 0.8, BORDER),
        ('LINEBELOW', (0, 0), (-1, 0), 0.8, BORDER),
        ('LINEBELOW', (0, 1), (-1, -1), 0.4, BORDER),
        ('LINEAFTER', (0, 0), (0, -1), 0.5, BORDER),
        ('LINEAFTER', (1, 0), (1, -1), 0.5, BORDER),
        ('LINEAFTER', (2, 0), (2, -1), 0.5, BORDER),
        ('LINEAFTER', (3, 0), (3, -1), 0.5, BORDER),
        *[
            ('BACKGROUND', (0, i), (-1, i),
             SLATE_LIGHT if i % 2 == 0 else _WHITE)
            for i in range(1, len(tbl_data))
        ],
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(items_tbl)
    elements.append(Spacer(1, 18))

    # 4. SUMMARY
    cgst = sgst = Decimal("0")
    if q.gst_type == "with_gst":
        cgst = subtotal * Decimal("0.09")
        sgst = subtotal * Decimal("0.09")

    discount = getattr(q, 'discount', Decimal('0')) or Decimal('0')
    grand_total = (subtotal + cgst + sgst - discount) if q.gst_type == "with_gst" \
                  else (subtotal - discount)
    grand_total = max(grand_total, Decimal('0'))

    sw = 140
    summary_rows = [[P("<b>Subtotal</b>", s_sum_lbl), P(format_inr_local(subtotal), s_sum_val)]]
    if q.gst_type == "with_gst":
        summary_rows += [
            [P("CGST (9%)", s_sum_lbl), P(format_inr_local(cgst), s_sum_val)],
            [P("SGST (9%)", s_sum_lbl), P(format_inr_local(sgst), s_sum_val)],
        ]
    if discount and discount > 0:
        summary_rows.append([
            P("<font color='#D97706'><b>Special Discount</b></font>", s_sum_lbl),
            P(f"<font color='#D97706'>\u2212\u00A0{format_inr_local(discount)}</font>", s_sum_val),
        ])
    summary_rows.append([P("", s_sum_lbl), P("", s_sum_val)])
    gt_idx = len(summary_rows)
    summary_rows.append([P("GRAND TOTAL", s_gtl), P(format_inr_local(grand_total), s_gtv)])

    sum_tbl = Table(summary_rows, colWidths=[sw, sw])
    sum_tbl.setStyle(TableStyle([
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, gt_idx - 2), 0.4, BORDER),
        ('BACKGROUND', (0, gt_idx), (-1, gt_idx), NAVY),
        ('TOPPADDING', (0, gt_idx), (-1, gt_idx), 11),
        ('BOTTOMPADDING', (0, gt_idx), (-1, gt_idx), 11),
        ('BOX', (0, 0), (-1, -1), 0.75, BORDER),
        ('ROUNDEDCORNERS', [4]),
    ]))

    sum_wrapper = Table([[Spacer(1, 1), sum_tbl]], colWidths=[page_w - sw * 2, sw * 2])
    sum_wrapper.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(sum_wrapper)
    elements.append(Spacer(1, 22))

    # 5. TERMS & CONDITIONS
    elements.append(HRFlowable(width="100%", thickness=0.75, color=BORDER, spaceAfter=10))
    elements.append(Paragraph("<b>TERMS &amp; CONDITIONS</b>",
        ps('tc_h', 'Helvetica-Bold', 15, NAVY, TA_CENTER, 14, spaceAfter=8)))

    i = 0
    qt_qs = q.quotation_terms.select_related('term').order_by('order', 'id')
    for i, qt in enumerate(qt_qs, 1):
        elements.append(P(
            f"<font color='#2563EB'><b>{i}.</b></font>\u00A0\u00A0{qt.term.text}",
            s_terms))
    if q.custom_terms:
        for j, line in enumerate(q.custom_terms.split("\n"), i + 1):
            if line.strip():
                elements.append(P(
                    f"<font color='#2563EB'><b>{j}.</b></font>\u00A0\u00A0{line.strip()}",
                    s_terms))

    elements.append(Spacer(1, 18))

    # 6. FOOTER BAND
    footer_band = Table([[
        P("<font color='#64748B'>System-generated quotation \u2014 no signature required.\u2002"
          "|\u2002satyamaluminiumhubli@gmail.com\u2002"
          "|\u2002GSTIN: 29ADRP1399D1ZX</font>",
          ps('fb', 'Helvetica', 7.5, TEXT3, TA_CENTER, 10))
    ]], colWidths=[page_w])
    footer_band.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), SLATE_LIGHT),
        ('LEFTPADDING', (0, 0), (-1, -1), 14), ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ('TOPPADDING', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('ROUNDEDCORNERS', [4]),
    ]))
    elements.append(footer_band)

    doc.build(elements)
    return response


# ================= ORDERS =================
@login_required(login_url='/login/')
def orders(request):
    query = request.GET.get('q', '').strip()
    qs = Order.objects.all().order_by('-id')
    if query:
        from django.db.models import Q as DQ
        qs = qs.filter(DQ(customer__name__icontains=query) | DQ(id__icontains=query))
    return render(request, 'orders.html', {'data': qs, 'q': query})


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
    from reportlab.pdfgen import canvas as rl_canvas

    order    = get_object_or_404(Order, id=order_id)
    customer = order.customer
    payments = OrderPayment.objects.filter(order=order).order_by('date')

    payments_sum = sum((p.amount for p in payments), Decimal('0'))
    total_paid   = order.advance_paid + payments_sum
    remaining    = order.total_amount - total_paid

    # Colour palette
    _NAVY      = colors.HexColor("#0D1B2A")
    _GOLD      = colors.HexColor("#B8922A")
    GOLD_LIGHT = colors.HexColor("#F5E6C8")
    _CREAM     = colors.HexColor("#FDFAF5")
    _SLATE     = colors.HexColor("#3D4F61")
    RED_DEEP   = colors.HexColor("#9B1C1C")
    RED_PALE   = colors.HexColor("#FEF2F2")
    _RULE      = colors.HexColor("#D4AF6A")
    LIGHT_RULE = colors.HexColor("#E8DCC8")
    _WHITE2    = colors.white

    TNR        = "Times-Roman"
    TNR_BOLD   = "Times-Bold"
    TNR_ITALIC = "Times-Italic"
    SANS       = "Helvetica"
    SANS_BOLD  = "Helvetica-Bold"

    font_name, rupee_symbol = _load_unicode_font()

    def fmt(amount):
        try:
            return f"{rupee_symbol} {format_inr(amount)}"
        except Exception:
            return f"{rupee_symbol} {Decimal(amount).quantize(Decimal('0.01'))}"

    class GoldRule(Flowable):
        def __init__(self, width=515, thickness=1.2, color=_RULE, top_gap=0, bot_gap=0):
            super().__init__()
            self.width     = width
            self.thickness = thickness
            self.color     = color
            self.top_gap   = top_gap
            self.bot_gap   = bot_gap

        def draw(self):
            self.canv.setStrokeColor(self.color)
            self.canv.setLineWidth(self.thickness)
            self.canv.line(0, self.bot_gap, self.width, self.bot_gap)

        def wrap(self, *args):
            return self.width, self.top_gap + self.bot_gap + self.thickness

    s_company = ParagraphStyle(
        "Company", fontName=TNR_BOLD, fontSize=26, alignment=TA_CENTER,
        textColor=_NAVY, leading=32, spaceAfter=2,
    )
    s_tagline2 = ParagraphStyle(
        "Tagline2", fontName=TNR_ITALIC, fontSize=10, alignment=TA_CENTER,
        textColor=_GOLD, leading=14, spaceAfter=0,
    )
    s_contact = ParagraphStyle(
        "Contact", fontName=SANS, fontSize=8.5, alignment=TA_CENTER,
        textColor=_SLATE, leading=13,
    )
    s_section_title = ParagraphStyle(
        "SectionTitle", fontName=TNR_BOLD, fontSize=11, alignment=TA_LEFT,
        textColor=_NAVY, leading=15, spaceBefore=4,
    )
    s_left = ParagraphStyle(
        "Left", fontName=SANS, fontSize=9.5, alignment=TA_LEFT,
        textColor=_SLATE, leading=15,
    )
    s_right = ParagraphStyle(
        "Right", fontName=SANS, fontSize=9.5, alignment=TA_RIGHT,
        textColor=_SLATE, leading=15,
    )
    s_label = ParagraphStyle(
        "Label", fontName=SANS_BOLD, fontSize=7.5, alignment=TA_LEFT,
        textColor=_GOLD, leading=11, spaceAfter=3, spaceBefore=0,
    )
    s_label_r = ParagraphStyle(
        "LabelR", fontName=SANS_BOLD, fontSize=7.5, alignment=TA_RIGHT,
        textColor=_GOLD, leading=11, spaceAfter=3,
    )
    s_body = ParagraphStyle(
        "Body", fontName=SANS, fontSize=9.5, alignment=TA_LEFT,
        textColor=_SLATE, leading=16,
    )
    s_footer2 = ParagraphStyle(
        "Footer2", fontName=SANS, fontSize=7.5, alignment=TA_CENTER,
        textColor=colors.HexColor("#94A3B8"), leading=12,
    )

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="reminder_order_{order.id}.pdf"'

    PAGE_W, PAGE_H = A4
    MARGIN_H   = 40
    CONTENT_W  = PAGE_W - 2 * MARGIN_H

    def on_first_page(canv, doc):
        canv.saveState()
        canv.setFillColor(_CREAM)
        canv.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        canv.setStrokeColor(_NAVY)
        canv.setLineWidth(1.5)
        canv.rect(14, 14, PAGE_W - 28, PAGE_H - 28, fill=0, stroke=1)
        canv.setStrokeColor(_GOLD)
        canv.setLineWidth(0.6)
        canv.rect(18, 18, PAGE_W - 36, PAGE_H - 36, fill=0, stroke=1)
        for cx, cy in [(18, 18), (PAGE_W - 18, 18),
                       (18, PAGE_H - 18), (PAGE_W - 18, PAGE_H - 18)]:
            canv.setFillColor(_GOLD)
            canv.circle(cx, cy, 3, fill=1, stroke=0)
        canv.setFillColor(_NAVY)
        canv.rect(0, PAGE_H - 110, PAGE_W, 110, fill=1, stroke=0)
        canv.setFillColor(_GOLD)
        canv.rect(0, PAGE_H - 113, PAGE_W, 3, fill=1, stroke=0)
        canv.restoreState()

    def on_later_pages(canv, doc):
        on_first_page(canv, doc)

    doc = SimpleDocTemplate(
        response, pagesize=A4,
        rightMargin=MARGIN_H, leftMargin=MARGIN_H,
        topMargin=100, bottomMargin=45,
    )

    elements = []

    # Header block
    logo_img = _load_logo_image(width=0.85 * inch, height=0.85 * inch, circular=False)
    logo_img.hAlign = "CENTER"

    company_cell = Paragraph("SATYAM ALUMINIUM", s_company)
    tagline_cell = Paragraph("Premium Quality Aluminium Fabricators", s_tagline2)
    contact_cell = Paragraph(
        "Shop No 4, Ganesh Plaza, Gokul Rd, Hubballi&nbsp;&nbsp;|&nbsp;&nbsp;"
        "+91-8073709478&nbsp;&nbsp;|&nbsp;&nbsp;satyamaluminiumhubli@gmail.com",
        s_contact,
    )

    header_block = Table(
        [[logo_img, [company_cell, tagline_cell, Spacer(1, 4), contact_cell], ""]],
        colWidths=[70, 390, 55],
    )
    header_block.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    elements.append(Spacer(1, -95))
    elements.append(header_block)
    elements.append(Spacer(1, 20))

    # Payment reminder title
    reminder_title = Paragraph(
        "<font name='Times-Bold' size='15' color='#0D1B2A'>PAYMENT REMINDER</font>",
        ParagraphStyle("BannerText", alignment=TA_CENTER, leading=20),
    )
    subtitle = Paragraph(
        f"<font name='Times-Italic' size='9' color='#B8922A'>"
        f"Reference: Order #{order.id}  &nbsp;|&nbsp;  "
        f"Issued: {datetime.now().strftime('%d %B, %Y')}</font>",
        ParagraphStyle("BannerSub", alignment=TA_CENTER, leading=13),
    )
    banner = Table([[reminder_title], [subtitle]], colWidths=[CONTENT_W])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GOLD_LIGHT),
        ("BOX", (0, 0), (-1, -1), 1.5, _GOLD),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    elements.append(banner)
    elements.append(Spacer(1, 20))

    # Billed to / order details
    billed_label = Paragraph("BILLED TO", s_label)
    billed_name  = Paragraph(
        f"<font name='Times-Bold' size='12' color='#0D1B2A'>{clean_text(customer.name)}</font>",
        s_left
    )
    billed_phone = Paragraph(clean_text(customer.phone) or "\u2014", s_left)
    billed_addr  = Paragraph(clean_text(customer.address) or "\u2014", s_left)

    order_label   = Paragraph("ORDER DETAILS", s_label_r)
    order_id_line = Paragraph(f"<b>Order ID:</b>&nbsp; #{order.id}", s_right)
    order_date    = Paragraph(f"<b>Date Issued:</b>&nbsp; {datetime.now().strftime('%d %B, %Y')}", s_right)
    order_status  = Paragraph(
        f"<b>Status:</b>&nbsp; <font color='#9B1C1C'><b>Outstanding</b></font>", s_right
    )

    info_table = Table(
        [[[billed_label, billed_name, billed_phone, billed_addr],
          [order_label, order_id_line, order_date, order_status]]],
        colWidths=[257, 258],
    )
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.8, _RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.8, _RULE),
        ("BACKGROUND", (0, 0), (-1, -1), _WHITE2),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (0, -1), 14),
        ("RIGHTPADDING", (1, 0), (1, -1), 14),
        ("LEFTPADDING", (1, 0), (1, -1), 10),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 22))

    # Financial summary table
    elements.append(Paragraph("Financial Summary", s_section_title))
    elements.append(GoldRule(width=CONTENT_W, thickness=0.8, color=_RULE, top_gap=3, bot_gap=6))

    col_desc_w  = 370
    col_amt_w   = CONTENT_W - col_desc_w

    def _hdr(txt):
        return Paragraph(
            f"<font name='Times-Bold' size='9.5' color='#FDFAF5'>{txt}</font>",
            ParagraphStyle("Hdr", alignment=TA_LEFT if txt != "Amount" else TA_RIGHT, leading=13),
        )

    def _row_l(txt, bold=False):
        fn = SANS_BOLD if bold else SANS
        return Paragraph(
            f"<font name='{fn}' size='9.5' color='#3D4F61'>{txt}</font>",
            ParagraphStyle("RL", alignment=TA_LEFT, leading=13),
        )

    def _row_r(txt, bold=False, color_hex="#3D4F61"):
        return Paragraph(
            f"<font name='{font_name}' size='9.5' color='{color_hex}'>{txt}</font>",
            ParagraphStyle("RR", alignment=TA_RIGHT, leading=13),
        )

    summary_data = [
        [_hdr("Description"), _hdr("Amount")],
        [_row_l("Total Order Amount"), _row_r(fmt(order.total_amount))],
        [_row_l("Advance Paid"),       _row_r(f"\u2212 {fmt(order.advance_paid)}")],
        [_row_l("Additional Payments"), _row_r(f"\u2212 {fmt(payments_sum)}")],
    ]

    summary_table = Table(summary_data, colWidths=[col_desc_w, col_amt_w])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 9),
        ("BACKGROUND", (0, 1), (-1, 1), _WHITE2),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#F7F3ED")),
        ("BACKGROUND", (0, 3), (-1, 3), _WHITE2),
        ("FONTNAME", (0, 1), (-1, -1), SANS),
        ("TEXTCOLOR", (0, 1), (-1, -1), _SLATE),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, LIGHT_RULE),
        ("BOX", (0, 0), (-1, -1), 0.8, _RULE),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 18))

    # Amount due box
    due_left = Paragraph(
        "<font name='Times-Bold' size='13' color='#0D1B2A'>TOTAL AMOUNT DUE</font>"
        "<br/><font name='Helvetica' size='8' color='#9B1C1C'>"
        "Please settle at your earliest convenience</font>",
        ParagraphStyle("DueL", alignment=TA_LEFT, leading=18),
    )
    due_right = Paragraph(
        f"<b>{fmt(remaining)}</b>",
        ParagraphStyle("DueR", fontName=font_name, fontSize=20,
                       alignment=TA_RIGHT, textColor=RED_DEEP, leading=24),
    )
    due_table = Table([[due_left, due_right]], colWidths=[290, 225])
    due_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), RED_PALE),
        ("BOX", (0, 0), (-1, -1), 2, colors.HexColor("#DC2626")),
        ("LINEAFTER", (0, 0), (0, 0), 0.8, colors.HexColor("#FCA5A5")),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (0, 0), 16),
        ("RIGHTPADDING", (1, 0), (1, 0), 16),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(due_table)
    elements.append(Spacer(1, 26))

    # Message
    elements.append(GoldRule(width=CONTENT_W, thickness=0.6, color=_RULE, top_gap=2, bot_gap=6))
    msg = (
        f"Dear <b>{clean_text(customer.name)}</b>,<br/>"
        f"This is a gentle reminder that an amount of "
        f"<font name='{font_name}' color='#9B1C1C'><b>{fmt(remaining)}</b></font> "
        f"is due for Order #{order.id}.<br/>"
        f"We kindly request you to make the payment at your earliest convenience.<br/>"
        f"For any queries, please feel free to contact us.<br/>"
        f"Thank you for choosing <b>Satyam Aluminium</b>."
    )
    elements.append(Paragraph(msg, s_body))
    elements.append(Spacer(1, 20))
    elements.append(GoldRule(width=CONTENT_W, thickness=0.6, color=_RULE, top_gap=2, bot_gap=4))

    # Footer
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        "Shop No 4, Ganesh Plaza, Gokul Rd, Hubballi  &nbsp;|&nbsp;  "
        "+91-8073709478  &nbsp;|&nbsp;  satyamaluminiumhubli@gmail.com<br/>"
        "<font color='#B8922A'>This document is system-generated and does not require any physical signature.</font>",
        s_footer2,
    ))

    doc.build(elements, onFirstPage=on_first_page, onLaterPages=on_later_pages)
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
        try:
            amount = Decimal(amount_str or '0')
        except InvalidOperation:
            return render(request, 'add_payment.html', {
                'order': order, 'error': 'Invalid amount format'
            })

        OrderPayment.objects.create(order=order, amount=amount)
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
        except Exception:
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
        except Exception:
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
        status            = request.POST.get('status')
        overtime_flag     = request.POST.get('overtime')
        overtime_bool     = True if overtime_flag in ('on', 'true', '1', 'yes') else False

        try:
            selected_date = _date.fromisoformat(selected_date_str)
        except Exception:
            return render(request, 'mark_attendance.html', {
                'emp': emp, 'error': 'Invalid date format', 'already_marked': already_marked
            })

        if Attendance.objects.filter(employee=emp, date=selected_date).exists():
            return render(request, 'mark_attendance.html', {
                'emp': emp, 'error': 'Attendance already marked for this date', 'already_marked': True
            })

        Attendance.objects.create(
            employee=emp, date=selected_date, status=status, overtime=overtime_bool
        )
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Attendance marked'})
        return redirect('employees')

    return render(request, 'mark_attendance.html', {'emp': emp, 'already_marked': already_marked})


@login_required(login_url='/login/')
def salary(request, emp_id):
    emp        = get_object_or_404(Employee, id=emp_id)
    attendance = Attendance.objects.filter(employee=emp)
    payments   = Payment.objects.filter(employee=emp)

    full_total = half_total = overtime_total = Decimal('0')

    for r in attendance:
        if r.status == 'full':
            full_total += emp.daily_salary
        elif r.status == 'half':
            half_total += emp.half_day_salary

        try:
            if getattr(r, 'overtime', False) and emp.overtime_salary is not None:
                overtime_total += emp.overtime_salary
        except Exception:
            pass

    total_earned = full_total + half_total + overtime_total
    total_paid   = sum((p.amount_paid for p in payments), Decimal('0'))
    remaining    = total_earned - total_paid

    return render(request, 'salary.html', {
        'emp': emp,
        'full_total': full_total,
        'half_total': half_total,
        'overtime_total': overtime_total,
        'total_earned': total_earned,
        'total_paid': total_paid,
        'remaining': remaining,
        'payments': payments
    })


@login_required(login_url='/login/')
def pay_salary(request, emp_id):
    emp        = get_object_or_404(Employee, id=emp_id)
    attendance = Attendance.objects.filter(employee=emp)
    payments   = Payment.objects.filter(employee=emp)

    full_total = half_total = overtime_total = Decimal('0')

    for r in attendance:
        if r.status == 'full':
            full_total += emp.daily_salary
        elif r.status == 'half':
            half_total += emp.half_day_salary
        try:
            if getattr(r, 'overtime', False) and emp.overtime_salary is not None:
                overtime_total += emp.overtime_salary
        except Exception:
            pass

    total_earned = full_total + half_total + overtime_total
    total_paid   = sum((p.amount_paid for p in payments), Decimal('0'))
    remaining    = total_earned - total_paid

    if request.method == "POST":
        amount_str = request.POST.get('amount')
        try:
            amount = Decimal(amount_str)
        except Exception:
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
        'payments': Payment.objects.filter(employee=emp)
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
    records = Attendance.objects.filter(employee=emp)

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
        except Exception:
            pass

    total_days   = records.count()
    present_days = sum(1 for r in records if r.status == 'full')
    half_days    = sum(1 for r in records if r.status == 'half')
    absent_days  = total_days - present_days - half_days

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
    elements.append(Paragraph('Shop no 4, Ganesh Plaza, Gokul Rd, Hubballi, Karnataka', subtitle_style))
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
    table_data = [['Date', 'Day', 'Status']]
    for r in records:
        date_str = r.date.strftime('%d-%m-%Y') if hasattr(r.date, 'strftime') else str(r.date)
        day      = r.date.strftime('%A') if hasattr(r.date, 'strftime') else ''
        status   = 'Full' if r.status == 'full' else ('Half' if r.status == 'half' else 'Absent')
        table_data.append([date_str, day, status])

    att_table = Table(table_data, colWidths=[100, 200, doc.width - 300])
    tbl_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2E86C1")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
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
    emp        = get_object_or_404(Employee, id=emp_id)
    attendance = Attendance.objects.filter(employee=emp).order_by('date')
    payments   = Payment.objects.filter(employee=emp).order_by('date')

    total_earned = Decimal('0')
    for r in attendance:
        if r.status == 'full':
            total_earned += emp.daily_salary
        elif r.status == 'half':
            total_earned += emp.daily_salary / 2

    total_paid = sum((p.amount_paid for p in payments), Decimal('0'))
    remaining  = total_earned - total_paid

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{emp.name}_salary_report.pdf"'

    DATA, BOLD, RUPEE = _get_fonts()

    W, _ = A4
    doc  = SimpleDocTemplate(
        response, pagesize=A4,
        leftMargin=40, rightMargin=40,
        topMargin=36, bottomMargin=36,
    )
    PAGE_W = W - 80

    s_co      = _ps('co',  'Times-Bold',  26, TA_CENTER, DARK,  32)
    s_tag     = _ps('tag', 'Times-Roman', 10, TA_CENTER, colors.HexColor('#555555'))
    s_contact = _ps('ct',  DATA,           8, TA_CENTER, GREY)
    s_small   = _ps('sm',  DATA,           8, TA_CENTER, LGREY)

    elements = []

    stripe = Table([['']], colWidths=[PAGE_W])
    stripe.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), GOLD),
        ('ROWHEIGHT',  (0, 0), (-1, -1), 5),
    ]))
    elements.append(stripe)
    elements.append(Spacer(1, 14))

    elements.append(Paragraph('SATYAM ALUMINIUM', s_co))
    elements.append(Spacer(1, 4))
    elements.append(HRFlowable(width=PAGE_W, thickness=1.5, color=GOLD, spaceAfter=4))
    elements.append(Paragraph(
        'Shop No. 4, Ganesh Plaza, Gokul Road, Hubballi, Karnataka \u2014 580030', s_tag))
    elements.append(Paragraph(
        '+91-8073709478   |   satyamaluminiumhubli@gmail.com', s_contact))
    elements.append(Spacer(1, 16))

    title_p = Paragraph(
        "<font name='Times-Bold' size='15' color='white'>EMPLOYEE SALARY REPORT</font>",
        _ps('tb', 'Times-Bold', 15, TA_CENTER, WHITE),
    )
    title_band = Table([[title_p]], colWidths=[PAGE_W])
    title_band.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), DARK),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(title_band)
    elements.append(Spacer(1, 20))

    # Employee info panel
    gen_date = datetime.now().strftime('%d %B, %Y')
    emp_role = getattr(emp, 'role', None) or 'N/A'

    left_cells  = [_info_cell('EMPLOYEE NAME', emp.name,           DATA, BOLD),
                   Spacer(1, 8),
                   _info_cell('ROLE',          emp_role,           DATA, BOLD)]
    mid_cells   = [_info_cell('EMPLOYEE ID',   f'#EMP-{emp.id}',  DATA, BOLD),
                   Spacer(1, 8),
                   _info_cell('REPORT DATE',   gen_date,           DATA, BOLD)]
    right_cells = [_info_cell('DAILY SALARY',  _fmt(emp.daily_salary, RUPEE), DATA, BOLD),
                   Spacer(1, 8),
                   _info_cell('PERIOD',        'All Time',         DATA, BOLD)]

    info_tbl = Table([[left_cells, mid_cells, right_cells]], colWidths=[PAGE_W / 3] * 3)
    info_tbl.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('BOX',           (0, 0), (-1, -1), 0.8, RULE),
        ('INNERGRID',     (0, 0), (-1, -1), 0.4, RULE),
        ('BACKGROUND',    (0, 0), (-1, -1), CREAM),
        ('TOPPADDING',    (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
    ]))
    elements.append(info_tbl)
    elements.append(Spacer(1, 22))

    # Ledger table
    elements += _section_heading('ATTENDANCE & PAYMENT LEDGER', PAGE_W)

    hdr = ['DATE', 'DAY', 'TYPE', 'DESCRIPTION', f'AMOUNT ({RUPEE})']
    rows_data = []

    for r in attendance:
        date_str = r.date.strftime('%d %b %Y') if hasattr(r.date, 'strftime') else str(r.date)
        day_str  = r.date.strftime('%A')        if hasattr(r.date, 'strftime') else ''
        if r.status == 'full':
            amt, desc = emp.daily_salary, 'Full Day'
        elif r.status == 'half':
            amt, desc = emp.daily_salary / 2, 'Half Day'
        else:
            amt, desc = Decimal('0'), 'Absent'
        rows_data.append([date_str, day_str, 'Earned', desc, f"{amt:,.2f}"])

    for p in payments:
        date_str = p.date.strftime('%d %b %Y') if hasattr(p.date, 'strftime') else str(p.date)
        day_str  = p.date.strftime('%A')        if hasattr(p.date, 'strftime') else ''
        rows_data.append([date_str, day_str, 'Paid', 'Salary Paid', f"{p.amount_paid:,.2f}"])

    ledger_data = [hdr] + rows_data
    l_style = TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  DARK),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  WHITE),
        ('FONTNAME',      (0, 0), (-1, 0),  BOLD),
        ('FONTSIZE',      (0, 0), (-1, 0),  8.5),
        ('TOPPADDING',    (0, 0), (-1, 0),  8),
        ('BOTTOMPADDING', (0, 0), (-1, 0),  8),
        ('FONTNAME',      (0, 1), (-1, -1), DATA),
        ('FONTSIZE',      (0, 1), (-1, -1), 8.5),
        ('TOPPADDING',    (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('ALIGN',         (4, 0), (4, -1),  'RIGHT'),
        ('ALIGN',         (2, 0), (2, -1),  'CENTER'),
        ('GRID',          (0, 0), (-1, -1), 0.4, RULE),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, CREAM]),
    ])

    for i, row in enumerate(rows_data, 1):
        clr = GREEN if row[2] == 'Earned' else RED
        l_style.add('TEXTCOLOR', (2, i), (2, i), clr)
        l_style.add('FONTNAME',  (2, i), (2, i), BOLD)

    ledger_tbl = Table(ledger_data, colWidths=[72, 78, 55, PAGE_W - 335, 85])
    ledger_tbl.setStyle(l_style)
    elements.append(ledger_tbl)
    elements.append(Spacer(1, 22))

    # Financial summary
    elements += _section_heading('FINANCIAL SUMMARY', PAGE_W)

    summary_rows = [
        ['Total Earned', _fmt(total_earned, RUPEE)],
        ['Total Paid',   _fmt(total_paid,   RUPEE)],
    ]
    sum_tbl = Table(summary_rows, colWidths=[PAGE_W - 160, 160])
    sum_tbl.setStyle(TableStyle([
        ('FONTNAME',      (0, 0), (-1, -1), DATA),
        ('FONTSIZE',      (0, 0), (-1, -1), 9.5),
        ('ALIGN',         (1, 0), (1, -1),  'RIGHT'),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
        ('GRID',          (0, 0), (-1, -1), 0.4, RULE),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [CREAM, WHITE]),
    ]))
    elements.append(sum_tbl)
    elements.append(Spacer(1, 2))

    bal_label = Paragraph(
        "<font name='Times-Bold' size='12'>REMAINING BALANCE</font>",
        _ps('_bl', 'Times-Bold', 12, TA_LEFT, WHITE),
    )
    bal_amount = Paragraph(
        f"<font name='{BOLD}' size='13'>{_fmt(remaining, RUPEE)}</font>",
        _ps('_ba', BOLD, 13, TA_RIGHT, WHITE),
    )
    bal_tbl = Table([[bal_label, bal_amount]], colWidths=[PAGE_W - 160, 160])
    bal_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), RED),
        ('TOPPADDING',    (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
        ('LEFTPADDING',   (0, 0), (0, 0),   14),
        ('RIGHTPADDING',  (1, 0), (1, 0),   14),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(bal_tbl)
    elements.append(Spacer(1, 28))

    # Footer
    elements.append(HRFlowable(width=PAGE_W, thickness=1.5, color=GOLD, spaceAfter=6))
    elements.append(Paragraph(
        'This is a system-generated document. No physical signature required.',
        s_small,
    ))
    elements.append(Spacer(1, 6))
    bot = Table([['']], colWidths=[PAGE_W])
    bot.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), GOLD),
        ('ROWHEIGHT',  (0, 0), (-1, -1), 4),
    ]))
    elements.append(bot)

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
    """AJAX endpoint to create a new TermCondition. Expects POST with 'text'."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    text = request.POST.get('text')
    if not text or not text.strip():
        return JsonResponse({'error': 'Text required'}, status=400)

    term = TermCondition.objects.create(text=text.strip())
    return JsonResponse({'id': term.id, 'text': term.text})


@login_required(login_url='/login/')
def edit_term(request, id):
    """AJAX endpoint to edit an existing TermCondition."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    term = get_object_or_404(TermCondition, id=id)
    text = request.POST.get('text', '').strip()
    if not text:
        return JsonResponse({'error': 'Text required'}, status=400)

    term.text = text
    term.save()
    return JsonResponse({'id': term.id, 'text': term.text})