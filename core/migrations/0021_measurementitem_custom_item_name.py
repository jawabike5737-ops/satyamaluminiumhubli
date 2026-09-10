from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0020_quotation_customer_gstin'),
    ]

    operations = [
        migrations.AddField(
            model_name='measurementitem',
            name='custom_item_name',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]