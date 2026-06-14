from django.db import models
from django.db.models import Sum
from django.utils import timezone
from decimal import Decimal
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from io import BytesIO
from PIL import Image
from .utils import compress_image_file, optimize_image


# ================= CUSTOMER =================
class Customer(models.Model):
    name = models.TextField(db_index=True)
    phone = models.CharField(max_length=15)
    address = models.TextField()

    def __str__(self):
        return self.name


# ================= PRODUCT =================
class Product(models.Model):
    name = models.TextField(db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.name


# ================= TERMS & CONDITIONS =================
class TermCondition(models.Model):
    text = models.TextField()

    def __str__(self):
        # return first 50 chars for admin lists
        return (self.text[:47] + '...') if len(self.text) > 50 else self.text


# ================= COMPANY / FIRM =================
class Company(models.Model):
    """Stores firm-specific header and contact details for PDFs.

    Keep fields simple and text-based so existing static assets can be referenced
    (e.g. use 'static/jglogo.png' for `logo_path`).
    """
    name = models.CharField(max_length=200, db_index=True)
    slug = models.SlugField(max_length=50, unique=True)
    tagline = models.CharField(max_length=200, blank=True)
    logo_path = models.CharField(max_length=255, blank=True,
                                 help_text="Static path or filename to company logo (e.g. 'logo.png' or 'static/jglogo.png')")
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=100, blank=True)
    email = models.CharField(max_length=200, blank=True)
    gstin = models.CharField(max_length=32, blank=True)
    bank_details = models.TextField(blank=True)
    terms = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


# ================= QUOTATION =================
class Quotation(models.Model):
    # NOTE: use select_related('customer') when querying quotations
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="quotations", db_index=True)
    # Link quotation to a firm/company
    company = models.ForeignKey('Company', null=True, blank=True, on_delete=models.SET_NULL, related_name='quotations')
    date = models.DateField(auto_now_add=True, db_index=True)

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cgst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sgst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Special discount as fixed amount (INR). Applies after GST when GST is enabled.
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Terms and custom terms saved per quotation
    # ManyToMany to TermCondition allows selecting multiple predefined terms
    # custom_terms stores freeform terms entered for this quotation
    terms = models.ManyToManyField('TermCondition', blank=True, through='QuotationTerm')
    custom_terms = models.TextField(blank=True, default='')
    # Store the full terms & conditions text for this quotation (editable copy)
    terms_and_conditions = models.TextField(blank=True)
    # Payment details inclusion
    include_payment_details = models.BooleanField(default=False)
    payment_details = models.ForeignKey(
        'PaymentDetails', null=True, blank=True, on_delete=models.SET_NULL, related_name='quotations'
    )
    
    # GST Type: with_gst or without_gst
    gst_type = models.CharField(
        max_length=20,
        choices=[
            ('with_gst', 'With GST'),
            ('without_gst', 'Without GST')
        ],
        default='with_gst'
    )

    # New unified tax type field: none | gst | igst
    tax_type = models.CharField(
        max_length=20,
        choices=[
            ('none', 'Without Tax'),
            ('gst', 'GST'),
            ('igst', 'IGST')
        ],
        default='none'
    )

    def __str__(self):
        return f"Quotation {self.id}"

    class Meta:
        ordering = ['-date']
        indexes = [
            models.Index(fields=['customer']),
            models.Index(fields=['date']),
            models.Index(fields=['customer', 'date']),
        ]


# Through model to store ordering for terms selected on a quotation
class QuotationTerm(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='quotation_terms')
    term = models.ForeignKey(TermCondition, on_delete=models.CASCADE, related_name='quotation_terms_on_term')
    order = models.PositiveIntegerField(default=0, db_index=True)

    class Meta:
        ordering = ['order', 'id']
        indexes = [
            models.Index(fields=['quotation']),
            models.Index(fields=['term']),
        ]

    def __str__(self):
        return f"Q{self.quotation_id} - T{self.term_id} ({self.order})"


# ================= PAYMENT DETAILS =================
class PaymentDetails(models.Model):
    BUSINESS = 'business'
    PERSONAL = 'personal'
    UPI = 'upi'
    ACCOUNT_TYPE_CHOICES = [
        (BUSINESS, 'Business Account'),
        (PERSONAL, 'Personal Account'),
        (UPI, 'UPI / Wallet'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payment_details')
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, default=BUSINESS)
    account_name = models.CharField(max_length=100, blank=True, help_text='Custom name like "Shop Account"')

    holder_name = models.CharField(max_length=100, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    ifsc_code = models.CharField(max_length=20, blank=True)
    branch = models.CharField(max_length=100, blank=True)

    upi_id = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=15, blank=True)

    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, null=True)

    class Meta:
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.account_name or self.get_account_type_display()} ({self.user})"


# ================= SERVICE =================
class Service(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    service_code = models.CharField(max_length=50, unique=True, db_index=True, null=True, blank=True)
    name = models.CharField(max_length=200, db_index=True)
    category = models.CharField(max_length=100, blank=True, db_index=True)
    description = models.TextField(blank=True)
    default_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Compatibility alias: expose `service_name` and `price` as requested
    service_name = models.CharField(max_length=200, blank=True, db_index=True)
    unit = models.CharField(max_length=50, default='Sq Ft')
    image = models.ImageField(upload_to='services/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True, null=True)
    

    class Meta:
        ordering = ['service_code', 'name']

    def __str__(self):
        display = self.service_name or self.name
        return f"{self.service_code or ''} - {display}"

    def save(self, *args, **kwargs):
        # If an image is present and is a new upload, compress it before saving
        old_name = None
        try:
            # keep track of existing image name so we can delete it after replacing
            if self.pk:
                orig = Service.objects.filter(pk=self.pk).first()
                if orig and orig.image:
                    old_name = orig.image.name
        except Exception:
            old_name = None

        try:
            if self.image and hasattr(self.image, 'file'):
                try:
                    self.image.open()
                    optimized = optimize_image(self.image.file, max_width=1920, quality=85, fmt='WEBP', method=6)
                    if optimized:
                        # generate new filename with .webp
                        name = self.image.name.rsplit('/', 1)[-1]
                        base = name.rsplit('.', 1)[0] if '.' in name else name
                        new_name = base + '.webp'
                        # save optimized content to the ImageField (do not commit yet)
                        self.image.save(new_name, optimized, save=False)
                except Exception:
                    pass
        except Exception:
            pass

        # Finally save the model (after compression)
        super().save(*args, **kwargs)

        # After saving, remove the old original (jpg/png) if it exists and is different from current
        try:
            if old_name and self.image and self.image.name and old_name != self.image.name:
                try:
                    if old_name.lower().endswith(('.jpg', '.jpeg', '.png')):
                        if default_storage.exists(old_name):
                            default_storage.delete(old_name)
                except Exception:
                    pass
        except Exception:
            pass

    @property
    def thumbnail(self):
        if not self.image:
            return ''
        thumb_name = self.image.name.rsplit('.', 1)[0] + '_thumb.jpg'
        try:
            if self.image.storage.exists(thumb_name):
                return self.image.storage.url(thumb_name)
        except Exception:
            pass
        return ''

    @property
    def price(self):
        # compatibility alias used throughout existing code
        return self.default_rate

    @price.setter
    def price(self, val):
        try:
            self.default_rate = val
        except Exception:
            pass

    @property
    def service_name_or_name(self):
        return self.service_name or self.name


class QuotationItem(models.Model):

    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.CASCADE,
        related_name='items',
        db_index=True
    )

    service = models.ForeignKey(
        'Service',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quotation_items',
        db_index=True
    )

    service_code = models.CharField(
        max_length=50,
        blank=True,
        db_index=True
    )

    description = models.TextField(blank=True)

    custom_item_name = models.CharField(
        max_length=200,
        blank=True
    )

    width = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True
    )

    height = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=1
    )

    # Preserve the original raw measurement value (3 decimal places)
    raw_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True
    )

    # When user manually types a quantity, mark it so measurement imports
    # and future autosaves do not overwrite the value.
    manual_quantity = models.BooleanField(default=False)

    unit = models.CharField(
        max_length=50,
        default='Sq Ft'
    )

    rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    notes = models.TextField(blank=True)

    @property
    def price(self):
        return self.rate

    def __str__(self):

        if self.service:
            return f"{self.service.service_code} - {self.service.name}"

        return (
            self.description[:60]
            if self.description
            else f"Item {self.id}"
        )

# ================= MEASUREMENTS =================
class Measurement(models.Model):
    # NOTE: use select_related('customer') when querying measurements
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='measurements', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"Measurements {self.id}"
    class Meta:
        ordering = ['-created_at']


class MeasurementItem(models.Model):
    measurement = models.ForeignKey(Measurement, on_delete=models.CASCADE, related_name='items', db_index=True)
    service = models.ForeignKey('Service', on_delete=models.SET_NULL, null=True, blank=True, related_name='measurement_items', db_index=True)

    # When a Service is selected, `service_code` and `description` are copied for quick lookup
    service_code = models.CharField(max_length=50, blank=True, db_index=True)
    description = models.TextField(blank=True)

    SIZE = 'size'
    LENGTH = 'length'
    NOS = 'nos'
    ITEM_TYPE_CHOICES = [
        (SIZE, 'Size based'),
        (LENGTH, 'Length / RFT'),
        (NOS, 'Count / Nos'),
    ]

    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES, default=SIZE, db_index=True)
    unit = models.CharField(max_length=20, default='Sq Ft', db_index=True)

    width = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    height = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=1)
    area = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    notes = models.TextField(blank=True)

    # Compatibility aliases for older code
    @property
    def price_per_unit(self):
        return self.rate

    @price_per_unit.setter
    def price_per_unit(self, val):
        self.rate = val

    @property
    def total_price(self):
        return self.total

    @total_price.setter
    def total_price(self, val):
        self.total = val

    def recalc(self):
        # Area = width * height * quantity when width/height provided
        from decimal import Decimal
        try:
            w = Decimal(self.width or 0)
            h = Decimal(self.height or 0)
            q = Decimal(self.quantity or 0)
            if w and h:
                self.area = (w * h * q)
            elif self.width and not self.height:
                # treat width as length for RFT-like items
                self.area = (w * q)
            else:
                self.area = q
            self.total = (self.area * Decimal(self.rate or 0))
        except Exception:
            # fallback safe values
            self.area = 0
            self.total = 0

    def save(self, *args, **kwargs):
        self.recalc()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.service_code or self.description[:30]} (M{self.measurement_id})"


class MeasurementSubItem(models.Model):
    item = models.ForeignKey(MeasurementItem, on_delete=models.CASCADE, related_name='subitems', db_index=True)

    # For size based items
    height = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    width = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    # For length-based items
    length = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)

    # For other items (length etc.) reuse height as length
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=1)

    def area(self):
        from decimal import Decimal, InvalidOperation
        try:
            q = Decimal(str(self.quantity)) if self.quantity is not None else Decimal('0')
            # size-based
            if self.height is not None and self.width is not None:
                return Decimal(str(self.height)) * Decimal(str(self.width)) * q
            # length-based: use length * quantity
            if self.length is not None:
                return Decimal(str(self.length)) * q
            # nos: area not applicable, return quantity
            return q
        except (InvalidOperation, Exception):
            return Decimal('0')

    def __str__(self):
        return f"Subitem {self.id} of Item {self.item_id}"
# ================= ORDER =================
class Order(models.Model):
    # NOTE: use select_related('customer') when querying orders
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="orders", db_index=True)
    quotation = models.ForeignKey(Quotation, on_delete=models.SET_NULL, null=True, blank=True, db_index=True)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    advance_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    def total_paid(self):
        # Use ORM aggregation to avoid Python-level summation and N+1
        extra = self.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        return self.advance_paid + extra

    def remaining(self):
        return self.total_amount - self.total_paid()

    def __str__(self):
        return f"Order {self.id}"
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Orders"
        indexes = [
            models.Index(fields=['customer']),
            models.Index(fields=['created_at']),
            models.Index(fields=['quotation']),
            models.Index(fields=['customer', 'created_at']),
        ]


# ================= ORDER ITEMS =================
class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items", db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='order_items', db_index=True)
    quantity = models.IntegerField()

    def __str__(self):
        return f"OrderItem {self.id} (P{self.product_id})"


# ================= ORDER PAYMENT =================
class OrderPayment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments", db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, db_index=True)
    # When the payment was actually made (can be backdated by user)
    payment_date = models.DateField(null=True, blank=True, db_index=True)
    # Legacy `date` field kept for compatibility (old records)
    date = models.DateField(auto_now_add=True, db_index=True)
    # Optional remarks / notes provided by user
    remarks = models.TextField(blank=True)
    # Record creation timestamp
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"OrderPayment OP{self.id} (O{self.order_id}) - {self.amount}"

    class Meta:
        indexes = [models.Index(fields=['order']), models.Index(fields=['date'])]


# ================= BILL =================
class Bill(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="bill")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    gst = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"Bill for Order {self.order_id}"


# ================= EMPLOYEE =================
class Employee(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    phone = models.CharField(max_length=15)
    role = models.CharField(max_length=100)
    # Manual salary fields
    daily_salary = models.DecimalField(max_digits=10, decimal_places=2)
    # Half day salary MUST be provided manually (no auto calculation)
    half_day_salary = models.DecimalField(max_digits=10, decimal_places=2)
    # Overtime is a fixed per-day amount (optional)
    overtime_salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return self.name


# ================= ATTENDANCE =================
class Attendance(models.Model):

    STATUS_CHOICES = [
        ('full', 'Full Day'),
        ('half', 'Half Day'),
        ('leave', 'Leave'),
        ('out', 'Out of City Work'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance", db_index=True)
    date = models.DateField(db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, db_index=True)
    # Whether overtime is marked for this attendance record.
    overtime = models.BooleanField(default=False)

    class Meta:
        unique_together = ['employee', 'date']
        indexes = [models.Index(fields=['employee', 'date'])]

    def __str__(self):
        return f"Attendance {self.id} - E{self.employee_id} {self.date}"


# ================= PAYMENT =================
class Payment(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payments", db_index=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(auto_now_add=True, db_index=True)
    remaining_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"Payment {self.id} - E{self.employee_id} - {self.amount_paid}"
