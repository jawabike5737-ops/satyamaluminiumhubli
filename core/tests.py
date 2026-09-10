from decimal import Decimal
import json
import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .forms import PaymentDetailsForm
from .models import (
    Attendance,
    Company,
    Customer,
    Employee,
    Measurement,
    MeasurementItem,
    MeasurementSubItem,
    Order,
    OrderPayment,
    Payment,
    PaymentDetails,
    Quotation,
    QuotationItem,
    Service,
    TermCondition,
)
from .services import calculate_salary
from .utils import clean_text, format_quantity, to_decimal


@override_settings(
    MEDIA_ROOT=tempfile.gettempdir(),
    DEFAULT_FILE_STORAGE='django.core.files.storage.FileSystemStorage',
    SECURE_SSL_REDIRECT=False,
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
)
class BaseTestCase(TestCase):
    pass


class AuthenticationTests(BaseTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='tester', password='pass')

    def test_login_page_and_login_flow(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Login')

        response = self.client.post(reverse('login'), {'username': 'tester', 'password': 'pass'})
        self.assertRedirects(response, reverse('dashboard'))

        other_client = self.client_class()
        response = other_client.post(reverse('login'), {'username': 'tester', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')

    def test_logout_redirects_to_login(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('logout'))
        self.assertRedirects(response, reverse('login'))

    def test_protected_views_redirect_anonymous_users(self):
        for url_name, kwargs in [
            ('dashboard', {}),
            ('services_api', {}),
            ('get_service_by_code', {'service_code': 'GL-01'}),
        ]:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name, kwargs=kwargs))
                self.assertNotEqual(response.status_code, 200)


class CustomerTests(BaseTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='customer_user', password='pass')
        self.client.force_login(self.user)

    def test_customer_crud_and_search(self):
        response = self.client.post(
            reverse('add_customer'),
            {'name': 'Asha', 'phone': '9876543210', 'address': 'Hubballi'},
        )
        self.assertRedirects(response, reverse('customers'))
        customer = Customer.objects.get(name='Asha')
        self.assertEqual(customer.phone, '9876543210')

        response = self.client.post(
            reverse('edit_customer', args=[customer.id]),
            {'name': 'Asha Updated', 'phone': '9876543211', 'address': 'Dharwad'},
        )
        self.assertRedirects(response, reverse('customers'))
        customer.refresh_from_db()
        self.assertEqual(customer.name, 'Asha Updated')

        response = self.client.post(reverse('delete_customer', args=[customer.id]))
        self.assertRedirects(response, reverse('customers'))
        self.assertFalse(Customer.objects.filter(id=customer.id).exists())

    def test_customer_form_validation_and_search_api(self):
        response = self.client.post(reverse('add_customer'), {'name': '', 'phone': '', 'address': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Name and Phone are required')

        Customer.objects.create(name='Ravi', phone='1111111111', address='Bengaluru')
        Customer.objects.create(name='Rakesh', phone='2222222222', address='Mysuru')
        response = self.client.get(reverse('search_customers'), {'q': 'Rav'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('results', payload)
        self.assertTrue(payload['results'])

    def test_customer_accepts_unicode_and_special_characters(self):
        customer = Customer.objects.create(name='नवीन & Sons', phone='9999999999', address='Café, Hubballi')
        self.assertEqual(str(customer), 'नवीन & Sons')


class ServiceTests(BaseTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='service_user', password='pass')
        self.client.force_login(self.user)

    def test_service_crud_image_and_api_endpoints(self):
        image_buffer = BytesIO()
        Image.new('RGB', (120, 120), color=(255, 0, 0)).save(image_buffer, format='JPEG')
        image = SimpleUploadedFile('test.jpg', image_buffer.getvalue(), content_type='image/jpeg')
        response = self.client.post(
            reverse('add_service'),
            {'service_name': 'Glass Panel', 'description': 'Test description', 'price': '150.50', 'image': image},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        service = Service.objects.get(service_name='Glass Panel')
        self.assertEqual(service.default_rate, Decimal('150.50'))
        self.assertTrue(service.image.name)

        response = self.client.post(
            reverse('edit_service', args=[service.id]),
            {'service_name': 'Glass Panel Updated', 'description': 'Updated', 'price': '175.00'},
        )
        self.assertRedirects(response, reverse('services'))
        service.refresh_from_db()
        self.assertEqual(service.service_name, 'Glass Panel Updated')

        response = self.client.post(reverse('delete_service_image', args=[service.id]))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content.decode(), {'ok': True})

        response = self.client.get(reverse('service_details_api', args=[service.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['service_name'], 'Glass Panel Updated')

        response = self.client.get(reverse('services_api'))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('results', payload)

        response = self.client.post(
            reverse('create_service_api'),
            data=json.dumps({'service_name': 'API Service', 'price': '230.00'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['id'])

        response = self.client.post(reverse('delete_service', args=[service.id]))
        self.assertRedirects(response, reverse('services'))
        self.assertFalse(Service.objects.filter(id=service.id).exists())

    def test_service_search_api_and_duplicate_service(self):
        Service.objects.create(service_name='Door Frame', name='Door Frame', description='Frame', default_rate=Decimal('200.00'))
        response = self.client.get(reverse('service_search_api'), {'q': 'Door'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload)

        response = self.client.post(
            reverse('create_service_api'),
            data=json.dumps({'service_name': 'Door Frame', 'price': '200.00'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['service_name'], 'Door Frame')


class MeasurementTests(BaseTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='measure_user', password='pass')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name='Meas', phone='3333333333', address='Hubballi')
        self.service = Service.objects.create(service_name='Window', name='Window', service_code='WIN-1', default_rate=Decimal('120.00'))

    def test_measurement_crud_and_pdf(self):
        payload = {
            'items': [
                {
                    'description': 'Pane',
                    'service_id': self.service.id,
                    'price_per_unit': '120',
                    'subs': [{'height': '2', 'width': '3', 'quantity': '1'}],
                }
            ]
        }
        response = self.client.post(
            reverse('save_measurements', args=[self.customer.id]),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get('ok'))
        measurement = Measurement.objects.get(id=data['measurement_id'])
        self.assertEqual(measurement.items.count(), 1)
        item = measurement.items.first()
        self.assertEqual(str(item.total_price), '720.00')

        response = self.client.get(reverse('get_measurements_json', args=[self.customer.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('items', payload)

        response = self.client.post(reverse('delete_measurement_item'), {'item_id': item.id})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MeasurementItem.objects.filter(id=item.id).exists())

        response = self.client.get(reverse('measurement_pdf', args=[self.customer.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_measurement_invalid_json_returns_400(self):
        response = self.client.post(
            reverse('save_measurements', args=[self.customer.id]),
            data='not-json',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_measurement_save_is_snapshot_and_idempotent(self):
        def item(description, height, width, service_id=self.service.id):
            return {
                'description': description,
                'service_id': service_id,
                'price_per_unit': '120.00',
                'item_type': 'size',
                'subs': [{'height': str(height), 'width': str(width), 'quantity': '1'}],
            }

        first = {'items': [item('A', 2, 3), item('B', 4, 5, None)]}
        response = self.client.post(reverse('save_measurements', args=[self.customer.id]), data=json.dumps(first), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        measurement = Measurement.objects.get(id=response.json()['measurement_id'])
        self.assertEqual(measurement.items.count(), 2)
        self.assertEqual(measurement.items.first().total, Decimal('720.00'))

        loaded = self.client.get(reverse('get_measurements_json', args=[self.customer.id])).json()['items']
        second = {'items': [{**first['items'][0], 'measurement_item_id': loaded[0]['measurement_item_id']},
                            {**first['items'][1], 'measurement_item_id': loaded[1]['measurement_item_id']}]}
        response = self.client.post(reverse('save_measurements', args=[self.customer.id]), data=json.dumps(second), content_type='application/json')
        self.assertEqual(response.json()['total_amount'], '3120.00')
        self.assertEqual(measurement.items.count(), 2)
        self.assertEqual(MeasurementSubItem.objects.filter(item__measurement=measurement).count(), 2)

        response = self.client.post(reverse('save_measurements', args=[self.customer.id]), data=json.dumps({'items': [second['items'][0]]}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(measurement.items.count(), 1)


class QuotationTests(BaseTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='quote_user', password='pass')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name='Quote Customer', phone='4444444444', address='Belagavi')
        self.company = Company.objects.create(name='Satyam', slug='satyam-test', phone='123', email='a@example.com')
        self.term = TermCondition.objects.create(text='Terms text')

    def test_create_and_view_quotation_with_tax_and_discount(self):
        response = self.client.post(
            reverse('create_quotation'),
            {
                'customer': self.customer.id,
                'company': self.company.id,
                'tax_type': 'gst',
                'discount': '10.00',
                'description': ['Window Frame'],
                'quantity': ['2'],
                'unit': ['Nos'],
                'price': ['100'],
                'service_name': ['Window Frame'],
                'terms': [str(self.term.id)],
            },
        )
        self.assertEqual(response.status_code, 302)
        quotation = Quotation.objects.latest('id')
        self.assertEqual(quotation.tax_type, 'gst')
        self.assertEqual(quotation.discount, Decimal('10.00'))
        self.assertEqual(str(quotation.subtotal), '200.00')
        self.assertEqual(str(quotation.cgst), '18.00')
        self.assertEqual(str(quotation.sgst), '18.00')
        self.assertEqual(str(quotation.total), '226.00')

        response = self.client.get(reverse('view_quotation', args=[quotation.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Window Frame')

    def test_edit_quotation_updates_totals_and_terms(self):
        quotation = Quotation.objects.create(customer=self.customer, tax_type='none', gst_type='without_gst')
        QuotationItem.objects.create(quotation=quotation, description='Old', quantity=1, unit='Nos', rate=100, total=100)
        response = self.client.post(
            reverse('edit_quotation', args=[quotation.id]),
            {
                'customer': self.customer.id,
                'company': self.company.id,
                'tax_type': 'none',
                'discount': '5.00',
                'description': ['Updated'],
                'quantity': ['2'],
                'unit': ['Nos'],
                'price': ['150'],
                'service_name': ['Updated Service'],
                'terms': [str(self.term.id)],
            },
        )
        self.assertRedirects(response, reverse('view_quotation', args=[quotation.id]))
        quotation.refresh_from_db()
        self.assertEqual(str(quotation.subtotal), '300.00')
        self.assertEqual(str(quotation.discount), '5.00')
        self.assertEqual(str(quotation.total), '295.00')
        self.assertTrue(quotation.quotation_terms.exists())

    def test_update_quotation_item_ajax_and_delete_quotation(self):
        quotation = Quotation.objects.create(customer=self.customer, tax_type='none', gst_type='without_gst')
        item = QuotationItem.objects.create(quotation=quotation, description='Line', quantity=1, unit='Nos', rate=100, total=100)
        response = self.client.post(
            reverse('update_quotation_item'),
            data=json.dumps({'item_id': item.id, 'width': '2', 'height': '3', 'raw_quantity': '1', 'price': '150'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['quotation_total'], '900.00')

        response = self.client.post(reverse('delete_quotation', args=[quotation.id]))
        self.assertRedirects(response, reverse('quotations'))
        self.assertFalse(Quotation.objects.filter(id=quotation.id).exists())

    def test_quotation_pdf_response(self):
        quotation = Quotation.objects.create(customer=self.customer, tax_type='none', gst_type='without_gst', subtotal=100, total=100)
        QuotationItem.objects.create(quotation=quotation, description='Doc', quantity=1, unit='Nos', rate=100, total=100)
        response = self.client.get(reverse('quotation_pdf', args=[quotation.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_save_quotation_draft_api(self):
        response = self.client.post(
            reverse('save_quotation_draft'),
            data=json.dumps({'customer_id': self.customer.id, 'tax_type': 'igst', 'discount': '0', 'items': [{'description': 'Draft', 'quantity': '3', 'unit': 'Nos', 'price': '50'}]}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(payload['quotation_id'])


class OrderAndPaymentTests(BaseTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='order_user', password='pass')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name='Order Cust', phone='5555555555', address='Hubballi')
        self.quotation = Quotation.objects.create(customer=self.customer, tax_type='none', gst_type='without_gst', subtotal=100, total=100)
        self.order = Order.objects.create(customer=self.customer, quotation=self.quotation, total_amount=Decimal('100.00'), advance_paid=Decimal('20.00'))

    def test_convert_to_order_and_reminder_pdf(self):
        response = self.client.post(reverse('convert_to_order', args=[self.quotation.id]), {'advance': '20'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(Order.objects.filter(quotation=self.quotation).exists())

    def test_add_order_payment_validation_and_balance(self):
        response = self.client.post(reverse('add_payment', args=[self.order.id]), {'amount': '80', 'payment_date': timezone.now().date().strftime('%Y-%m-%d')})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.order.remaining(), Decimal('0.00'))
        self.assertTrue(OrderPayment.objects.filter(order=self.order).exists())

        response = self.client.post(reverse('add_payment', args=[self.order.id]), {'amount': '10'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(OrderPayment.objects.filter(order=self.order).count(), 1)

    def test_delete_order(self):
        response = self.client.post(reverse('delete_order', args=[self.order.id]))
        self.assertRedirects(response, reverse('orders'))
        self.assertFalse(Order.objects.filter(id=self.order.id).exists())


class EmployeeAttendanceSalaryTests(BaseTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='emp_user', password='pass')
        self.client.force_login(self.user)
        self.employee = Employee.objects.create(name='Asha', phone='6666666666', role='Technician', daily_salary=Decimal('500.00'), half_day_salary=Decimal('250.00'), overtime_salary=Decimal('100.00'))

    def test_employee_crud_salary_and_pdf(self):
        response = self.client.post(
            reverse('add_employee'),
            {'name': 'Ravi', 'phone': '7777777777', 'role': 'Worker', 'salary': '600', 'half_salary': '300', 'overtime_salary': '120'},
        )
        self.assertRedirects(response, reverse('employees'))
        employee = Employee.objects.get(name='Ravi')

        response = self.client.post(reverse('edit_employee', args=[employee.id]), {'name': 'Ravi Updated', 'phone': '7777777777', 'role': 'Worker', 'salary': '650', 'half_salary': '325', 'overtime_salary': '130'})
        self.assertRedirects(response, reverse('employees'))
        employee.refresh_from_db()
        self.assertEqual(employee.name, 'Ravi Updated')

        Attendance.objects.create(employee=employee, date=timezone.now().date(), status='full')
        Attendance.objects.create(employee=employee, date=timezone.now().date() - timezone.timedelta(days=1), status='half', overtime=True)
        Payment.objects.create(employee=employee, amount_paid=Decimal('400.00'))
        result = calculate_salary(employee)
        self.assertEqual(result['earned'], Decimal('650.00') + Decimal('325.00') + Decimal('130.00'))
        self.assertEqual(result['remaining'], result['earned'] - Decimal('400.00'))

        response = self.client.post(reverse('pay_salary', args=[employee.id]), {'amount': '100'})
        self.assertRedirects(response, reverse('salary', args=[employee.id]))
        self.assertTrue(Payment.objects.filter(employee=employee).count() >= 2)

        response = self.client.get(reverse('salary_pdf', args=[employee.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

        response = self.client.get(reverse('attendance_report_pdf', args=[employee.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

        response = self.client.get(reverse('export_excel', args=[employee.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response['Content-Type'])

        response = self.client.post(reverse('delete_employee', args=[employee.id]))
        self.assertRedirects(response, reverse('employees'))
        self.assertFalse(Employee.objects.filter(id=employee.id).exists())

    def test_mark_attendance_validation_and_view(self):
        response = self.client.post(reverse('attendance', args=[self.employee.id]), {'date': timezone.now().date().strftime('%Y-%m-%d'), 'status': 'full', 'overtime': 'on'})
        self.assertRedirects(response, reverse('employees'))
        self.assertTrue(Attendance.objects.filter(employee=self.employee).exists())

        response = self.client.post(reverse('attendance', args=[self.employee.id]), {'date': timezone.now().date().strftime('%Y-%m-%d'), 'status': 'full'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Attendance already marked for this date')

        response = self.client.get(reverse('view_attendance', args=[self.employee.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.name)


class AjaxAndFormTests(BaseTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='ajax_user', password='pass')
        self.client.force_login(self.user)

    def test_payment_details_form_validation_and_ajax_save(self):
        form = PaymentDetailsForm({'account_type': PaymentDetails.BUSINESS, 'account_name': 'Shop', 'holder_name': 'Test', 'bank_name': 'Bank', 'account_number': '', 'ifsc_code': '', 'branch': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('Account number is required for bank accounts.', form.non_field_errors())

        response = self.client.post(
            reverse('ajax_save_payment'),
            {'payment_account_type': PaymentDetails.BUSINESS, 'payment_account_name': 'Shop', 'payment_holder_name': 'Test', 'payment_bank_name': 'Bank', 'payment_account_number': '123', 'payment_ifsc_code': 'IFSC123', 'payment_branch': 'Hubballi', 'make_default': 'on'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(PaymentDetails.objects.filter(user=self.user).exists())

        response = self.client.post(reverse('delete_payment_account', args=[payload['id']]))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content.decode(), {'success': True})

    def test_term_endpoints(self):
        response = self.client.post(reverse('add_term'), {'text': 'New term'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['id'])

        response = self.client.post(reverse('edit_term', args=[payload['id']]), {'text': 'Updated term'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['text'], 'Updated term')


class UtilityAndRegressionTests(BaseTestCase):
    def test_utils_and_special_cases(self):
        self.assertEqual(to_decimal(None), Decimal('0'))
        self.assertEqual(to_decimal('12.50'), Decimal('12.50'))
        self.assertEqual(format_quantity(Decimal('49.000')), '49')
        self.assertEqual(clean_text('A&B'), 'AB')

    def test_search_endpoints_handle_empty_queries(self):
        self.user = get_user_model().objects.create_user(username='reg_user', password='pass')
        self.client.force_login(self.user)
        response = self.client.get(reverse('search_services'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.json())

        response = self.client.get(reverse('search_quotations'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.json())