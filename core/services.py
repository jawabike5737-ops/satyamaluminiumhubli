from decimal import Decimal
from django.db.models import Sum

from .models import Attendance, Payment
from .utils import to_decimal


def calculate_salary(emp):
    """Compute salary components and payments for an employee.

    Returns a dict with keys:
    - full_total, half_total, overtime_total (Decimal)
    - earned, paid, remaining (Decimal)
    - payments (QuerySet), attendance (QuerySet)
    """
    attendance = Attendance.objects.filter(employee=emp)

    full_days = attendance.filter(status='full').count()
    half_days = attendance.filter(status='half').count()
    overtime_days = attendance.filter(overtime=True).count()

    full_total = (Decimal(full_days) * emp.daily_salary) if full_days else Decimal('0')
    half_total = (Decimal(half_days) * emp.half_day_salary) if half_days else Decimal('0')
    overtime_rate = emp.overtime_salary if emp.overtime_salary is not None else Decimal('0')
    overtime_total = (Decimal(overtime_days) * overtime_rate) if overtime_days else Decimal('0')

    earned = full_total + half_total + overtime_total

    # Use ORM aggregation for payments sum
    paid_agg = Payment.objects.filter(employee=emp).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0')
    paid = paid_agg if isinstance(paid_agg, Decimal) else to_decimal(paid_agg)

    remaining = earned - paid

    payments = Payment.objects.filter(employee=emp).order_by('-date')

    return {
        'full_total': full_total,
        'half_total': half_total,
        'overtime_total': overtime_total,
        'earned': earned,
        'paid': paid,
        'remaining': remaining,
        'payments': payments,
        'attendance': attendance,
    }
