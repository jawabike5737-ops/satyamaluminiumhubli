from django.db import models
from django.db.models import Sum
from django.utils import timezone
from decimal import Decimal
from django.conf import settings


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


# ================= QUOTATION =================
class Quotation(models.Model):
    # NOTE: use select_related('customer') when querying quotations
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="quotations", db_index=True)
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
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.account_name or self.get_account_type_display()} ({self.user})"


# ================= SERVICE =================
class Service(models.Model):
    name = models.CharField(max_length=200, db_index=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.name


# ================= QUOTATION ITEMS =================
class QuotationItem(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='items', db_index=True)

    description = models.TextField()
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50)

    price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.description[:60] if self.description else f"Item {self.id}"


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
    SIZE = 'size'
    LENGTH = 'length'
    NOS = 'nos'
    ITEM_TYPE_CHOICES = [
        (SIZE, 'Size based'),
        (LENGTH, 'Length / RFT'),
        (NOS, 'Count / Nos'),
    ]

    measurement = models.ForeignKey(Measurement, on_delete=models.CASCADE, related_name='items', db_index=True)
    # Link to a predefined Service (optional). If set, use Service.name as item name.
    service = models.ForeignKey('Service', on_delete=models.SET_NULL, null=True, blank=True, related_name='measurement_items', db_index=True)
    # If user typed a custom item name (not a Service), store it here.
    # Use a model-level default to avoid NULLs and make field safe across forms/apis
    custom_item_name = models.TextField(blank=True, default='')
    # Description (editable copy)
    description = models.TextField()
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES, default=SIZE)
    unit = models.CharField(max_length=20, default='Sq Ft')
    # Price per unit for this item (editable by user when creating quotation)
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Total price (aggregate across subitems) saved for convenience
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.description} (M{self.measurement_id})"


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
        try:
            q = float(self.quantity)
            # size-based
            if self.height is not None and self.width is not None:
                return float(self.height) * float(self.width) * q
            # length-based: use length * quantity
            if self.length is not None:
                return float(self.length) * q
            # nos: area not applicable, return quantity
            return q
        except Exception:
            return None

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
    date = models.DateField(auto_now_add=True, db_index=True)

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
