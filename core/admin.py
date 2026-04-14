from django.contrib import admin
from .models import *

# ================= CUSTOMER =================
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'phone')
    search_fields = ('name', 'phone')


# ================= PRODUCT =================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'price', 'quantity')
    search_fields = ('name',)


# ================= ORDER =================
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'total_amount', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('customer__name',)

    # 🔥 IMPORTANT (removes N+1)
    list_select_related = ('customer',)


# ================= ORDER ITEM =================
@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'product', 'quantity')

    # 🔥 Fix N+1
    list_select_related = ('order', 'product')


# ================= BILL =================
@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'total_amount', 'gst')

    list_select_related = ('order',)


# ================= EMPLOYEE =================
@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'phone', 'role')
    search_fields = ('name',)


# ================= ATTENDANCE =================
@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'employee', 'date', 'status')
    list_filter = ('status', 'date')

    # 🔥 Fix N+1
    list_select_related = ('employee',)


# ================= SERVICE =================
@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'price')
    search_fields = ('name',)


# ================= QUOTATION =================
@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'total', 'date')
    list_filter = ('date',)

    # 🔥 Fix N+1
    list_select_related = ('customer',)


# ================= QUOTATION ITEM =================
@admin.register(QuotationItem)
class QuotationItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'quotation', 'description', 'quantity', 'total')

    list_select_related = ('quotation',)


# ================= TERMS =================
@admin.register(TermCondition)
class TermConditionAdmin(admin.ModelAdmin):
    list_display = ('id', 'text')


# ================= QUOTATION TERM =================
@admin.register(QuotationTerm)
class QuotationTermAdmin(admin.ModelAdmin):
    list_display = ('id', 'quotation', 'term', 'order')
    list_filter = ('quotation',)
    ordering = ('order',)

    # 🔥 Fix N+1
    list_select_related = ('quotation', 'term')


# ================= MEASUREMENT =================
@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'created_at')
    list_filter = ('created_at',)

    # 🔥 Fix N+1
    list_select_related = ('customer',)


# ================= MEASUREMENT ITEM =================
@admin.register(MeasurementItem)
class MeasurementItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'measurement', 'description', 'item_type', 'unit')
    list_filter = ('item_type', 'unit')

    # 🔥 Fix N+1
    list_select_related = ('measurement',)


# ================= MEASUREMENT SUBITEM =================
@admin.register(MeasurementSubItem)
class MeasurementSubItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'item', 'height', 'width', 'length', 'quantity')

    list_select_related = ('item',)