from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q

from orderpiqrApp.models import Customer, UserProfile

User = get_user_model()

# If your UserProfile uses a different field name for the per-company username, change here:
PROFILE_USERNAME_FIELD = 'user__username'


class CompanySignupForm(forms.Form):
    # Company
    company_name = forms.CharField(label="Company name", max_length=150)
    # Admin account (Email NOT enforced unique; username unique within the company)
    admin_email = forms.EmailField(label="Admin email", required=True)
    admin_profile_username = forms.CharField(label="Admin profile username", max_length=50)
    admin_password1 = forms.CharField(label="Admin password", widget=forms.PasswordInput)
    admin_password2 = forms.CharField(label="Confirm admin password", widget=forms.PasswordInput)

    # Picker account
    picker_email = forms.EmailField(label="Orderpicker email", required=True)
    picker_profile_username = forms.CharField(label="Orderpicker profile username", max_length=50)
    picker_password1 = forms.CharField(label="Orderpicker password", widget=forms.PasswordInput)
    picker_password2 = forms.CharField(label="Confirm orderpicker password", widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()

        # Password checks
        ap1, ap2 = cleaned.get('admin_password1'), cleaned.get('admin_password2')
        pp1, pp2 = cleaned.get('picker_password1'), cleaned.get('picker_password2')
        if ap1 != ap2:
            self.add_error('admin_password2', "Passwords do not match.")
        if pp1 != pp2:
            self.add_error('picker_password2', "Passwords do not match.")

        # Validate password strength (uses Django validators)
        if ap1:
            try:
                validate_password(ap1)
            except ValidationError as e:
                self.add_error('admin_password1', e)
        if pp1:
            try:
                validate_password(pp1)
            except ValidationError as e:
                self.add_error('picker_password1', e)

        # Company uniqueness (by name; adjust if you prefer VAT/Domain)
        company_name = cleaned.get('company_name')
        if company_name and Customer.objects.filter(name__iexact=company_name).exists():
            self.add_error('company_name', "A company with this name already exists.")

        # Per-company profile username uniqueness:
        admin_un = cleaned.get('admin_profile_username')
        picker_un = cleaned.get('picker_profile_username')

        # Prevent duplicates within the same signup form
        if admin_un and picker_un and admin_un.strip().lower() == picker_un.strip().lower():
            self.add_error('picker_profile_username', "Profile usernames must be different.")

        # We can’t query per-company yet (company doesn’t exist), but
        # we can pre-flight check across all profiles with a similar name in same company_name, if you keep a unique (customer, username).
        # Final authoritative check will happen in the view after Customer is created.
        return cleaned

    def ensure_profile_username_available(self, customer, username, field_name):
        """
        Call this from the view (after customer exists) to enforce uniqueness of profile.username within that company.
        """
        if not username:
            raise ValidationError("Username is required.")
        filt = {PROFILE_USERNAME_FIELD + '__iexact': username, 'customer': customer}
        if UserProfile.objects.filter(**filt).exists():
            self.add_error(field_name, "This username is already taken for this company.")
            raise ValidationError("Duplicate profile username in company.")
