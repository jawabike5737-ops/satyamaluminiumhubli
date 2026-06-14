from django.db import migrations, models
import django.utils.timezone

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_seed_companies'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderpayment',
            name='payment_date',
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='orderpayment',
            name='remarks',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='orderpayment',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True, null=True),
        ),
    ]
