from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Measurement, MeasurementItem


class Command(BaseCommand):
    help = 'Report measurement integrity issues; use --repair only after taking a database backup.'

    def add_arguments(self, parser):
        parser.add_argument('--customer-id', type=int)
        parser.add_argument('--measurement-id', type=int)
        parser.add_argument('--repair', action='store_true')

    def handle(self, *args, **options):
        queryset = Measurement.objects.prefetch_related('items__subitems').order_by('id')
        if options['customer_id']:
            queryset = queryset.filter(customer_id=options['customer_id'])
        if options['measurement_id']:
            queryset = queryset.filter(id=options['measurement_id'])

        for measurement in queryset:
            items = list(measurement.items.all())
            service_counts = Counter(item.service_id for item in items if item.service_id is not None)
            duplicate_services = {service_id: count for service_id, count in service_counts.items() if count > 1}
            calculated_total = Decimal('0')
            calculated_area = Decimal('0')
            for item in items:
                item_area = sum((sub.area() for sub in item.subitems.all()), Decimal('0'))
                calculated_area += item_area
                calculated_total += (item_area * item.rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            self.stdout.write(
                f'Measurement {measurement.id} customer={measurement.customer_id} '
                f'items={len(items)} subitems={sum(item.subitems.count() for item in items)} '
                f'stored_total={sum((item.total for item in items), Decimal("0"))} '
                f'calculated_total={calculated_total} area={calculated_area} '
                f'duplicate_services={duplicate_services or "none"}'
            )

            if options['repair']:
                with transaction.atomic():
                    for item in items:
                        item.save()
                self.stdout.write(self.style.WARNING(f'Recalculated totals for measurement {measurement.id}'))

        if not options['repair']:
            self.stdout.write('Dry run only. No records were changed.')
        else:
            self.stdout.write(self.style.WARNING('Repair completed. Verify the report and application totals.'))
