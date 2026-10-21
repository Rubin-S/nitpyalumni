"""Validated alumni profile details; account identity and permissions stay server-owned."""
from django import forms
from django.core.validators import URLValidator

from web.models import UserData


class ProfileURLField(forms.URLField):
    default_validators = [URLValidator(schemes=["http", "https"])]

    def __init__(self, **kwargs):
        super().__init__(required=False, max_length=200, assume_scheme="https", **kwargs)


class AlumniProfileForm(forms.ModelForm):
    degree = forms.ChoiceField(choices=[("", "Select your degree")] + [
        (value, value) for value in ("B.Tech", "M.Tech", "Ph.D", "B.Sc. B.Ed", "M.Sc")
    ])
    department = forms.ChoiceField(choices=[("", "Select your department")] + [
        (value, value) for value in (
            "Computer Science Engineering", "Electronics and Communication Engineering",
            "Electrical and Electronics Engineering", "Mechanical Engineering", "Civil Engineering",
            "Physics", "Chemistry", "Mathematics", "Humanities",
        )
    ])
    current_status = forms.ChoiceField(label="Currently", choices=(
        ("none", "Neither"), ("job", "Working"), ("study", "Pursuing Higher Studies"),
    ))
    linkedin = ProfileURLField(label="LinkedIn profile")
    facebook = ProfileURLField(label="Facebook")
    instagram = ProfileURLField(label="Instagram")
    present_address = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))
    batch = forms.IntegerField(label="Batch (passout year)", min_value=1950, max_value=2100)

    class Meta:
        model = UserData
        fields = (
            "name", "phone_number", "email_id", "country", "state", "city", "batch",
            "degree", "department", "present_address", "linkedin", "facebook", "instagram",
            "current_status", "job_title", "job_address", "higher_study_uni_name",
            "higher_study_uni_address", "higher_study_field",
        )
        labels = {"name": "Full name", "email_id": "Contact email", "phone_number": "Phone number"}
        widgets = {"present_address": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = self.instance
        # A new profile starts with the account's verified canonical email.
        # Contact edits on existing profiles never change login/reset identity.
        self.fields["email_id"].disabled = profile.pk is None
        # Preserve historical labels on existing records without admitting
        # arbitrary new degree/department values during profile completion.
        if profile.pk:
            for name in ("degree", "department"):
                value = getattr(profile, name)
                field = self.fields[name]
                if value and value not in dict(field.choices):
                    field.choices = [*field.choices, (value, value)]
        self.initial["linkedin"] = profile.linked_in or ""
        self.initial["current_status"] = (
            "job" if profile.in_job else
            "study" if profile.higher_study_uni_name or profile.higher_study_field else "none"
        )
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )

    def clean(self):
        data = super().clean()
        status = data.get("current_status")
        if status != "job":
            data.update(job_title="", job_address="")
        if status != "study":
            data.update(higher_study_uni_name="", higher_study_uni_address="", higher_study_field="")
        return data

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.in_job = self.cleaned_data["current_status"] == "job"
        profile.linked_in = self.cleaned_data["linkedin"]
        if commit:
            profile.save()
        return profile
