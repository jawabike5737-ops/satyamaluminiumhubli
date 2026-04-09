from django.db import models
from django.utils import timezone
from decimal import Decimal


# ================= CUSTOMER =================
class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    address = models.TextField()

    def __str__(self):
        return self.name


# ================= PRODUCT =================
class Product(models.Model):
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField()

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
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="quotations")
    date = models.DateField(auto_now_add=True)

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
    custom_terms = models.TextField(blank=True, null=True)
    # Store the full terms & conditions text for this quotation (editable copy)
    terms_and_conditions = models.TextField(blank=True, null=True)
    
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


# Through model to store ordering for terms selected on a quotation
class QuotationTerm(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='quotation_terms')
    term = models.ForeignKey(TermCondition, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Q{self.quotation.id} - T{self.term.id} ({self.order})"


# ================= SERVICE =================
class Service(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.name


# ================= QUOTATION ITEMS =================
class QuotationItem(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE)

    description = models.CharField(max_length=255)
    quantity = models.IntegerField()
    unit = models.CharField(max_length=50)

    price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)


# ================= MEASUREMENTS =================
class Measurement(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='measurements')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Measurements for {self.customer.name} ({self.id})"


class MeasurementItem(models.Model):
    SIZE = 'size'
    LENGTH = 'length'
    NOS = 'nos'
    ITEM_TYPE_CHOICES = [
        (SIZE, 'Size based'),
        (LENGTH, 'Length / RFT'),
        (NOS, 'Count / Nos'),
    ]

    measurement = models.ForeignKey(Measurement, on_delete=models.CASCADE, related_name='items')
    # Link to a predefined Service (optional). If set, use Service.name as item name.
    service = models.ForeignKey('Service', on_delete=models.SET_NULL, null=True, blank=True, related_name='measurement_items')
    # If user typed a custom item name (not a Service), store it here.
    custom_item_name = models.CharField(max_length=200, null=True, blank=True)
    # Description (editable copy)
    description = models.CharField(max_length=200)
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES, default=SIZE)
    unit = models.CharField(max_length=20, default='Sq Ft')
    # Price per unit for this item (editable by user when creating quotation)
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Total price (aggregate across subitems) saved for convenience
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.description} ({self.measurement.customer.name})"


class MeasurementSubItem(models.Model):
    item = models.ForeignKey(MeasurementItem, on_delete=models.CASCADE, related_name='subitems')

    # For size based items
    height = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    width = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    # For length-based items
    length = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)

    # For other items (length etc.) reuse height as length
    quantity = models.IntegerField(default=1)

    def area(self):
        try:
            # size-based
            if self.height is not None and self.width is not None:
                return float(self.height) * float(self.width) * int(self.quantity)
            # length-based: use length * quantity
            if self.length is not None:
                return float(self.length) * int(self.quantity)
            # nos: area not applicable, return quantity
            return float(self.quantity)
        except Exception:
            return None

    def __str__(self):
        return f"Subitem {self.id} of {self.item.description}"
# ================= ORDER =================
class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="orders")
    quotation = models.ForeignKey(Quotation, on_delete=models.SET_NULL, null=True, blank=True)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    advance_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_at = models.DateTimeField(default=timezone.now)

    def total_paid(self):
        extra = sum((p.amount for p in self.payments.all()), Decimal('0'))
        return self.advance_paid + extra

    def remaining(self):
        return self.total_amount - self.total_paid()

    def __str__(self):
        return f"Order {self.id} - {self.customer.name}"


# ================= ORDER ITEMS =================
class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()

    def __str__(self):
        return f"{self.product.name} ({self.quantity})"


# ================= ORDER PAYMENT =================
class OrderPayment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"Order {self.order.id} - {self.amount}"


# ================= BILL =================
class Bill(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="bill")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    gst = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"Bill for Order {self.order.id}"


# ================= EMPLOYEE =================
class Employee(models.Model):
    name = models.CharField(max_length=100)
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

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    # Whether overtime is marked for this attendance record.
    overtime = models.BooleanField(default=False)

    class Meta:
        unique_together = ['employee', 'date']

    def __str__(self):
        return f"{self.employee.name} - {self.date}"


# ================= PAYMENT =================
class Payment(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payments")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(auto_now_add=True)
    remaining_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.employee.name} - {self.amount_paid}"