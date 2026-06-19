from django.urls import path
from . import views

urlpatterns = [

    # ================= MEASUREMENT PDF =================
    path('measurement-pdf/<int:cust_id>/', views.measurement_pdf, name='measurement_pdf'),

    # ================= DASHBOARD =================
    path('', views.dashboard, name='dashboard'),

    # ================= AUTH =================
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),

    # ================= CUSTOMERS =================
    path('customers/', views.customers, name='customers'),
    path('add-customer/', views.add_customer, name='add_customer'),
    path('example-ajax/', views.example_ajax_form, name='example_ajax_form'),
    path('edit-customer/<int:id>/', views.edit_customer, name='edit_customer'),
    path('delete-customer/<int:id>/', views.delete_customer, name='delete_customer'),

    # ================= SERVICES =================
    path('services/', views.services, name='services'),
    path('api/services/', views.services_api, name='services_api'),
    path('api/service-search/', views.service_search_api, name='service_search_api'),
    path('api/search-customers/', views.search_customers, name='search_customers'),
    path('api/search-services/', views.search_services, name='search_services'),
    path('api/search-companies/', views.search_companies, name='search_companies'),
    path('api/search-payment-accounts/', views.search_payment_accounts, name='search_payment_accounts'),
    path('api/search-terms/', views.search_terms, name='search_terms'),
    path('api/create-service/', views.create_service_api, name='create_service_api'),
    path('api/save-service/', views.create_service_api, name='save_service_api'),
    path('api/update-service/<int:id>/', views.update_service_api, name='update_service_api'),
    path('api/service-details/<int:id>/', views.service_details_api, name='service_details_api'),
    path('api/get-service/<str:service_code>/', views.get_service_by_code, name='get_service_by_code'),
    path('api/service/<int:id>/delete-image/', views.delete_service_image, name='delete_service_image'),
    path('add-service/', views.add_service, name='add_service'),
    path('edit-service/<int:id>/', views.edit_service, name='edit_service'),
    path('delete-service/<int:id>/', views.delete_service, name='delete_service'),

    # ================= QUOTATIONS =================
    path('quotations/', views.quotations, name='quotations'),
    path('create-quotation/', views.create_quotation, name='create_quotation'),
    path('api/search-quotations/', views.search_quotations, name='search_quotations'),
    path('api/payment/save/', views.ajax_save_payment, name='ajax_save_payment'),
    path('api/payment/delete/<int:id>/', views.delete_payment_account, name='delete_payment_account'),
    path('add-term/', views.add_term, name='add_term'),
    path('edit-term/<int:id>/', views.edit_term, name='edit_term'),
    path('view-quotation/<int:id>/', views.view_quotation, name='view_quotation'),
    path('edit-quotation/<int:id>/', views.edit_quotation, name='edit_quotation'),
    path('quotation-pdf/<int:id>/', views.quotation_pdf, name='quotation_pdf'),
    path('api/quotation-item/update/', views.update_quotation_item, name='update_quotation_item'),
    path('api/service/<int:id>/json/', views.get_service_json, name='get_service_json'),
    path('api/quotation/save-draft/', views.save_quotation_draft, name='save_quotation_draft'),
    path('delete-quotation/<int:id>/', views.delete_quotation, name='delete_quotation'),

    # ================= MEASUREMENTS =================
    path('customer/<int:cust_id>/measurements/', views.take_measurements, name='take_measurements'),
    path('take-measurements/<int:cust_id>/', views.take_measurements, name='take_measurements_alias'),
    path('customer/<int:cust_id>/measurements/save/', views.save_measurements, name='save_measurements'),
    path('customer/<int:cust_id>/measurements/json/', views.get_measurements_json, name='get_measurements_json'),
    path('api/get-measurements/<int:cust_id>/', views.get_measurements_json, name='api_get_measurements'),
    path('measurement-item/delete/', views.delete_measurement_item, name='delete_measurement_item'),

    # ================= ORDERS =================
    path('orders/', views.orders, name='orders'),
    path('delete-order/<int:id>/', views.delete_order, name='delete_order'),
    path('convert-order/<int:q_id>/', views.convert_to_order, name='convert_to_order'),
    path('add-payment/<int:order_id>/', views.add_order_payment, name='add_payment'),
    path('reminder/<int:order_id>/', views.generate_reminder_pdf, name='generate_reminder'),

    # ================= EMPLOYEES =================
    path('employees/', views.employees, name='employees'),
    path('add-employee/', views.add_employee, name='add_employee'),
    path('edit-employee/<int:emp_id>/', views.edit_employee, name='edit_employee'),
    path('delete-employee/<int:emp_id>/', views.delete_employee, name='delete_employee'),

    # ================= ATTENDANCE =================
    path('attendance/<int:emp_id>/', views.mark_attendance, name='attendance'),
    path('view-attendance/<int:emp_id>/', views.view_attendance, name='view_attendance'),
    path('attendance-report/<int:emp_id>/', views.attendance_report_pdf, name='attendance_report_pdf'),
    path('excel/<int:emp_id>/', views.export_excel, name='export_excel'),

    # ================= SALARY =================
    path('salary/<int:emp_id>/', views.salary, name='salary'),
    path('pay/<int:emp_id>/', views.pay_salary, name='pay_salary'),
    path('payment-history/<int:emp_id>/', views.payment_history, name='payment_history'),
    path('reset/<int:emp_id>/', views.reset_salary, name='reset_salary'),
    path('salary-pdf/<int:emp_id>/', views.salary_pdf, name='salary_pdf'),
]