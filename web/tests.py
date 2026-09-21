from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import UserData


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AuthenticationFlowTests(TestCase):
    password = "StrongPass!2026"

    def signup_payload(self, **overrides):
        data = {
            "name": "Test Alumni",
            "roll_no": "EC20A0001",
            "phone_number": "9876543210",
            "email_id": "alumni@example.com",
            "country": "India",
            "state": "Puducherry",
            "city": "Karaikal",
            "batch": "2024",
            "degree": "B.Tech",
            "department": "Electronics and Communication Engineering",
            "present_address": "Karaikal, Puducherry",
            "linkedin": "",
            "facebook": "",
            "instagram": "",
            "current_status": "none",
            "job_title": "",
            "job_address": "",
            "higher_study_uni_name": "",
            "higher_study_uni_address": "",
            "higher_study_field": "",
            "password1": self.password,
            "password2": self.password,
        }
        data.update(overrides)
        return data

    def create_account(
        self,
        username="EC20A0001",
        email="alumni@example.com",
        approved=False,
    ):
        user = User.objects.create_user(
            username=username,
            email=email,
            password=self.password,
            first_name="Test",
            last_name="Alumni",
        )
        UserData.objects.create(
            user=user,
            roll_no=username,
            name="Test Alumni",
            phone_number="9876543210",
            country="India",
            state="Puducherry",
            city="Karaikal",
            batch=2024,
            department="Electronics and Communication Engineering",
            degree="B.Tech",
            email_id=email,
            in_job=False,
            present_address="Karaikal, Puducherry",
            account_is_approved=approved,
        )
        return user

    def login(self, email="alumni@example.com", password=None):
        return self.client.post(
            reverse("login"),
            {"email": email, "password": password or self.password},
        )

    def test_signup_page_loads(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)

    def test_valid_signup_creates_user_and_pending_profile(self):
        response = self.client.post(reverse("signup"), self.signup_payload())

        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(username="EC20A0001")
        self.assertEqual(user.email, "alumni@example.com")
        self.assertTrue(user.check_password(self.password))

        profile = UserData.objects.get(user=user)
        self.assertEqual(profile.roll_no, "EC20A0001")
        self.assertFalse(profile.account_is_approved)
        self.assertEqual(profile.degree, "B.Tech")
        self.assertEqual(len(mail.outbox), 1)

    def test_created_account_can_log_in_with_email_and_password(self):
        self.client.post(reverse("signup"), self.signup_payload())

        response = self.login()

        self.assertRedirects(response, "/")
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            User.objects.get(email="alumni@example.com").id,
        )

        dashboard = self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertTemplateUsed(dashboard, "student_dash.html")

    def test_wrong_password_does_not_create_session(self):
        self.create_account()

        response = self.login(password="DefinitelyWrongPassword")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_duplicate_roll_number_is_rejected(self):
        self.create_account()

        response = self.client.post(
            reverse("signup"),
            self.signup_payload(email_id="second@example.com"),
        )

        self.assertRedirects(response, reverse("signup"))
        self.assertEqual(User.objects.filter(username="EC20A0001").count(), 1)
        self.assertFalse(User.objects.filter(email="second@example.com").exists())

    def test_duplicate_email_is_rejected(self):
        self.create_account()

        response = self.client.post(
            reverse("signup"),
            self.signup_payload(roll_no="EC20A0002"),
        )

        self.assertRedirects(response, reverse("signup"))
        self.assertEqual(User.objects.filter(email="alumni@example.com").count(), 1)
        self.assertFalse(User.objects.filter(username="EC20A0002").exists())

    def test_invalid_roll_number_is_rejected(self):
        response = self.client.post(
            reverse("signup"),
            self.signup_payload(roll_no="INVALID"),
        )

        self.assertRedirects(response, reverse("signup"))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(UserData.objects.count(), 0)

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(
            reverse("signup"),
            self.signup_payload(password2="DifferentPass!2026"),
        )

        self.assertRedirects(response, reverse("signup"))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(UserData.objects.count(), 0)

    def test_unapproved_user_is_blocked_then_approved_user_gets_access(self):
        user = self.create_account(approved=False)
        self.login()

        blocked = self.client.get(reverse("alumni_map"))
        self.assertRedirects(blocked, "/")

        profile = UserData.objects.get(user=user)
        profile.account_is_approved = True
        profile.save()

        allowed = self.client.get(reverse("alumni_map"))
        self.assertEqual(allowed.status_code, 200)
        self.assertTemplateUsed(allowed, "alumni_map.html")

    def test_anonymous_user_is_redirected_from_protected_page(self):
        response = self.client.get(reverse("alumni_map"))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("alumni_map")}',
        )

    def test_weak_password_is_rejected(self):
        response = self.client.post(
            reverse("signup"),
            self.signup_payload(password1="password", password2="password"),
        )

        self.assertRedirects(response, reverse("signup"))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(UserData.objects.count(), 0)

    def test_required_server_side_fields_are_enforced(self):
        response = self.client.post(
            reverse("signup"),
            self.signup_payload(name=""),
        )

        self.assertRedirects(response, reverse("signup"))
        self.assertEqual(User.objects.count(), 0)

    def test_email_is_normalized_and_login_is_case_insensitive(self):
        response = self.client.post(
            reverse("signup"),
            self.signup_payload(email_id=" Alumni@EXAMPLE.COM "),
        )

        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(username="EC20A0001")
        self.assertEqual(user.email, "Alumni@example.com")

        login_response = self.login(email="alumni@example.com")
        self.assertRedirects(login_response, "/")
        self.assertIn("_auth_user_id", self.client.session)

    @patch("web.views.UserData.objects.create", side_effect=RuntimeError("profile failure"))
    def test_profile_failure_rolls_back_user_creation(self, _mock_create):
        response = self.client.post(reverse("signup"), self.signup_payload())

        self.assertRedirects(response, reverse("signup"))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(UserData.objects.count(), 0)


    def test_logout_ends_authenticated_session(self):
        self.create_account()
        self.login()
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.get(reverse("logout"))

        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)
