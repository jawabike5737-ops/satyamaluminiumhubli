import os
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
else:
    rf = RequestFactory()
    req = rf.get(f'/quotation-pdf/{q.id}/')
    user = User.objects.first()
    if not user:
        user = User.objects.create_superuser('devuser', 'dev@example.com', 'password')
    req.user = user
    resp = quotation_pdf(req, q.id)
    out = f'sample_quotation_{q.id}.pdf'
    with open(out, 'wb') as f:
        f.write(resp.content)
    print('WROTE', out)
