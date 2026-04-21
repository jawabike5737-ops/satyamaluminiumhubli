from django import forms
from .models import PaymentDetails


class PaymentDetailsForm(forms.ModelForm):
    class Meta:
        model = PaymentDetails
        fields = [
            'account_type', 'account_name', 'holder_name', 'bank_name',
            'account_number', 'ifsc_code', 'branch', 'upi_id', 'phone_number', 'is_default'
        ]

    def clean(self):
        cleaned = super().clean()
        acct_type = cleaned.get('account_type')
        acc_no = cleaned.get('account_number')
        ifsc = cleaned.get('ifsc_code')
        upi = cleaned.get('upi_id')
        phone = cleaned.get('phone_number')

        if acct_type in (PaymentDetails.BUSINESS, PaymentDetails.PERSONAL):
            if not acc_no:
                raise forms.ValidationError('Account number is required for bank accounts.')
            if not ifsc:
                raise forms.ValidationError('IFSC code is required for bank accounts.')

        if acct_type == PaymentDetails.UPI:
            if not upi and not phone:
                raise forms.ValidationError('Provide UPI ID or phone number for UPI accounts.')

        return cleaned
