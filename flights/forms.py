from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Booking


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ("passenger_name", "passenger_email", "passenger_phone", "seats")
        widgets = {
            "passenger_name": forms.TextInput(attrs={"placeholder": "Full name"}),
            "passenger_email": forms.EmailInput(attrs={"placeholder": "Email"}),
            "passenger_phone": forms.TextInput(attrs={"placeholder": "+1 312 555 0148 (for delay SMS alerts)"}),
            "seats": forms.NumberInput(attrs={"min": 1, "max": 9}),
        }


class PassengerSignupForm(UserCreationForm):
    username = forms.CharField(required=True, max_length=150)
    email = forms.EmailField(required=True)
    full_name = forms.CharField(required=False, max_length=150)

    class Meta:
        model = User
        fields = ("username", "email", "full_name", "password1", "password2")

    error_messages = {
        "password_mismatch": "Passwords do not match.",
    }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data["email"].strip().lower()
        full_name = self.cleaned_data.get("full_name", "").strip()
        user.username = self.cleaned_data["username"].strip()
        user.email = email
        if full_name:
            first, *_rest = full_name.split(" ", 1)
            user.first_name = first
        if commit:
            user.save()
        return user



class PassengerSigninForm(forms.Form):
    identifier = forms.CharField(label="Email or username", max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)
