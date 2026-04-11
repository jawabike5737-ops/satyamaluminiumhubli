#!/usr/bin/env python3
"""
dev-scripts/gen_quotation_pdf.py
Dev-only helper: generate a sample quotation PDF.
Runs only when DEBUG=True or DEV_ALLOW=1 in env.
"""
import os
import sys

if os.environ.get('DEBUG', 'False') != 'True' and os.environ.get('DEV_ALLOW') != '1':
    print("This script is for development only. Set DEBUG=True or DEV_ALLOW=1 to run.")
    sys.exit(1)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'satyam_project.settings')
import django
django.setup()

from django.test.client import RequestFactory
from django.contrib.auth.models import User
from core.views import quotation_pdf
from core.models import Quotation

q = Quotation.objects.order_by('-id').first()
if not q:
    print('NO_QUOTATION')
    sys.exit(0)

rf = RequestFactory()
req = rf.get(f'/quotation-pdf/{q.id}/')
user = User.objects.first()
if not user:
    print("No user found. Create a user first (this script will not create one).")
    sys.exit(1)
req.user = user
resp = quotation_pdf(req, q.id)
out = f'sample_quotation_{q.id}.pdf'
with open(out, 'wb') as f:
    f.write(resp.content)
print('WROTE', out)
