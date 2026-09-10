from django.db import migrations


def create_companies(apps, schema_editor):
    Company = apps.get_model('core', 'Company')

    Company.objects.update_or_create(
        slug='satyam',
        defaults={
            'name': 'SATYAM ALUMINIUM',
            'tagline': 'PRECISION • QUALITY • EXCELLENCE',
            'logo_path': 'logo.png',
            'address': 'Shop No. 4, Ganesh Plaza,\nBeside Triveni Bakery,\nNehru Nagar,\nGokul Road,\nHubballi – 580030',
            'phone': '+91 8073709478 | +91 9448442717 | +91 9591291155',
            'email': 'satyamaluminiumhubli@gmail.com',
            'gstin': '29ADRPR1399D1ZX',
            'bank_details': '',
            'terms': '',
        }
    )

    Company.objects.update_or_create(
        slug='paras',
        defaults={
            'name': 'PARAS UPVEX',
            'tagline': 'PRECISION • QUALITY • EXCELLENCE',
            'logo_path': 'paraslogo.png',
            'address': '#337,\nMayur Nagar,\nAnand Nagar,\nOld Hubli,\nHubballi – 580024',
            'phone': '8792749555 | 9448442717 | 8073709478',
            'email': 'sanjayrajpurohit9738@gmail.com',
            'gstin': '29AAIFP8343D1Z1',
            'bank_details': '',
            'terms': '',
        }
    )

    Company.objects.update_or_create(
        slug='jayashree',
        defaults={
            'name': 'JAYSHREE GLASS',
            'tagline': 'PRECISION • QUALITY • EXCELLENCE',
            'logo_path': 'jglogo.png',
            'address': '#6 Hurkadli Building,\nManjunath Nagar,\nGokul Road,\nHubli – 580030',
            'phone': '9036062717 | 9448442717',
            'email': 'virandarsingh6362@gmail.com',
            'gstin': '29CHAPR5091P1ZI',
            'bank_details': '',
            'terms': '',
        }
    )


def remove_companies(apps, schema_editor):
    Company = apps.get_model('core', 'Company')
    Company.objects.filter(slug__in=['satyam', 'paras', 'jayashree']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_company_quotation_company'),
    ]

    operations = [
        migrations.RunPython(create_companies, reverse_code=remove_companies),
    ]
