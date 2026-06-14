from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
import json
import tempfile
import shutil
from PIL import Image

from .models import Customer, Service, Measurement, MeasurementItem
from django.contrib.auth import get_user_model
from decimal import Decimal
from .models import Quotation, QuotationItem


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class MeasurementViewTests(TestCase):

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('tester', password='pass')
        self.client.login(username='tester', password='pass')

        self.customer = Customer.objects.create(
            name='Test Cust',
            phone='999999',
            address='Addr'
        )

        self.service = Service.objects.create(
            name='Glass',
            service_code='GL-01',
            default_rate=100
        )

    def test_save_measurements_creates_items(self):

        payload = {
            'items': [
                {
                    'description': 'Pane',
                    'service_id': self.service.id,
                    'price_per_unit': '100',
                    'subs': [
                        {
                            'height': '2',
                            'width': '3',
                            'quantity': '1'
                        }
                    ]
                }
            ]
        }

        url = reverse('save_measurements', args=[self.customer.id])

        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )

        self.assertEqual(resp.status_code, 200)

        data = resp.json()

        self.assertTrue(data.get('ok'))

        m_id = data.get('measurement_id')

        self.assertIsNotNone(m_id)

        m = Measurement.objects.get(id=m_id)

        self.assertEqual(m.items.count(), 1)

        mi = m.items.first()

        # area = 2*3*1 = 6 ; total = 6 * 100 = 600
        self.assertEqual(str(mi.total_price), '600.00')


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ServiceThumbnailTests(TestCase):

    def test_thumbnail_created_on_save(self):

        img_io = Image.new('RGB', (800, 600), color=(73, 109, 137))

        tmp = tempfile.NamedTemporaryFile(
            suffix='.jpg',
            delete=False
        )

        img_io.save(tmp, format='JPEG')

        tmp.seek(0)

        with open(tmp.name, 'rb') as fh:

            uploaded = SimpleUploadedFile(
                'test.jpg',
                fh.read(),
                content_type='image/jpeg'
            )

            svc = Service.objects.create(
                name='WithImg',
                service_code='IMG1',
                default_rate=50,
                image=uploaded
            )

            svc.refresh_from_db()

            self.assertTrue(bool(svc.thumbnail))

        try:
            tmp.close()
            shutil.os.unlink(tmp.name)
        except Exception:
            pass


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class QuotationAPITests(TestCase):

    def setUp(self):

        User = get_user_model()

        self.user = User.objects.create_user(
            'tester2',
            password='pass'
        )

        self.client.login(
            username='tester2',
            password='pass'
        )

        self.customer = Customer.objects.create(
            name='Q Cust',
            phone='11111',
            address='Addr'
        )

        self.service = Service.objects.create(
            name='Frame',
            service_code='FR-01',
            default_rate=200
        )

    def test_update_quotation_item_updates_totals(self):

        q = Quotation.objects.create(
            customer=self.customer,
            gst_type='with_gst'
        )

        qi = QuotationItem.objects.create(
            quotation=q,
            description='Test',
            quantity=1,
            unit='Nos',
            rate=100,
            total=100
        )

        url = reverse('update_quotation_item')

        payload = {
            'item_id': qi.id,
            'width': '2',
            'height': '3',
            'raw_quantity': '1',
            'price': '150'
        }

        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )

        self.assertEqual(resp.status_code, 200)

        data = resp.json()

        self.assertEqual(data.get('status'), 'success')

        qi.refresh_from_db()

        # area = 2*3*1 = 6 ; total = 6 * 150 = 900
        self.assertEqual(str(qi.total), '900.00')

        q.refresh_from_db()

        self.assertEqual(str(q.subtotal), '900.00')

    def test_save_quotation_draft_creates_quotation(self):

        url = reverse('save_quotation_draft')

        payload = {
            'customer_id': self.customer.id,
            'gst_type': 'without_gst',
            'discount': '50',
            'items': [
                {
                    'service_id': self.service.id,
                    'description': 'I1',
                    'width': '2',
                    'height': '2',
                    'quantity': '1',
                    'unit': 'Sq Ft',
                    'price': '200'
                },
                {
                    'description': 'I2',
                    'quantity': '3',
                    'unit': 'Nos',
                    'price': '100'
                }
            ]
        }

        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )

        self.assertEqual(resp.status_code, 200)

        data = resp.json()

        self.assertEqual(data.get('status'), 'success')

        qid = data.get('quotation_id')

        q = Quotation.objects.get(id=qid)

        # first item = 2*2*1*200 = 800
        # second item = 3*100 = 300
        # subtotal = 1100
        # total after discount = 1050

        self.assertEqual(str(q.subtotal), '1100.00')

        self.assertEqual(str(q.total), '1050.00')