from django.contrib import admin

# Register your models here.
from .models import *

admin.site.register(Customer)
admin.site.register(Product)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(Bill)

from .models import Employee, Attendance

admin.site.register(Employee)
admin.site.register(Attendance)

from .models import Service, Quotation, QuotationItem

admin.site.register(Service)
admin.site.register(Quotation)
admin.site.register(QuotationItem)
from .models import TermCondition

admin.site.register(TermCondition)
from .models import QuotationTerm

@admin.register(QuotationTerm)
class QuotationTermAdmin(admin.ModelAdmin):
	list_display = ('id', 'quotation', 'term', 'order')
	list_filter = ('quotation',)
	ordering = ('order',)

# Measurement models
from .models import Measurement, MeasurementItem, MeasurementSubItem

@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
	list_display = ('id', 'customer', 'created_at')
	list_filter = ('created_at',)

@admin.register(MeasurementItem)
class MeasurementItemAdmin(admin.ModelAdmin):
	list_display = ('id', 'measurement', 'description', 'item_type', 'unit')
	list_filter = ('item_type', 'unit')

@admin.register(MeasurementSubItem)
class MeasurementSubItemAdmin(admin.ModelAdmin):
	list_display = ('id', 'item', 'height', 'width', 'length', 'quantity')