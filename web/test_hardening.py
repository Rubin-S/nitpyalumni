"""Tests for the production security hardening pass."""
import csv
import io
from unittest.mock import patch

from django.conf import settings
from django.contrib.admin.sites import site as admin_site
from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from web.admin import export_as_csv
from web.csv_safe import safe_cell
from web.models import PasswordResetThrottle, UserData
from web.views import clean_social_url

PASSWORD = "Str0ng!Alumni#2026"


def make_alumni(username="EC20A0001", email="alumni@example.com", approved=True, name="Test Alumni"):
    user = User.objects.create_user(username=username, email=email, password=PASSWORD)
    UserData.objects.create(
        user=user, roll_no=username, name=name, phone_number="9876543210",
        country="India", state="Puducherry", city="Karaikal", batch=2024,
        department="ECE", degree="B.Tech", email_id=email, present_address="Karaikal",
        account_is_approved=approved,
    )
    return user


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    LOGIN_FAILURE_LIMIT_PER_ACCOUNT=3, LOGIN_FAILURE_LIMIT_PER_IP=5,
)
class LoginBruteForceTests(TestCase):
    def setUp(self):
        make_alumni()

    def fail(self, email="alumni@example.com", client=None, **extra):
        return (client or self.client).post(
            reverse("login"), {"email": email, "password": "wrong-password"}, **extra,
        )

    def test_account_locks_after_repeated_failures_even_with_correct_password(self):
        for _ in range(3):
            self.assertEqual(self.fail().status_code, 200)
        response = self.client.post(reverse("login"), {"email": "alumni@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Too many failed sign-in attempts", status_code=429)

    def test_lock_applies_to_username_and_any_case(self):
        for _ in range(3):
            self.fail(email="ec20a0001")
        response = self.client.post(reverse("login"), {"email": "EC20A0001", "password": PASSWORD})
        self.assertEqual(response.status_code, 429)

    def test_admin_login_is_throttled_by_same_backend(self):
        User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        for _ in range(3):
            self.client.post("/admin/login/", {"username": "boss", "password": "nope"})
        self.client.post("/admin/login/", {"username": "boss", "password": PASSWORD})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ip_limit_blocks_spraying_across_accounts(self):
        for i in range(5):
            self.fail(email=f"user{i}@example.com")
        response = self.client.post(reverse("login"), {"email": "alumni@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 429)

    def test_other_users_unaffected_and_normal_login_still_works(self):
        make_alumni("EC20A0002", "other@example.com")
        for _ in range(3):
            self.fail()
        response = self.client.post(reverse("login"), {"email": "other@example.com", "password": PASSWORD})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_unknown_and_known_accounts_respond_identically_before_lock(self):
        known = self.fail()
        unknown = self.fail(email="nobody@example.com")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertContains(known, "Invalid email or password")
        self.assertContains(unknown, "Invalid email or password")

    def test_throttle_keys_do_not_store_raw_identifiers(self):
        self.fail()
        for key in PasswordResetThrottle.objects.values_list("key", flat=True):
            self.assertNotIn("alumni", key)
            self.assertEqual(len(key), 40)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class LogoutCsrfTests(TestCase):
    def test_get_does_not_log_out(self):
        user = make_alumni()
        self.client.force_login(user)
        response = self.client.get(reverse("logout"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)

    def test_post_requires_csrf_token(self):
        user = make_alumni()
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        response = client.post(reverse("logout"))
        self.assertEqual(response.status_code, 403)
        self.assertIn("_auth_user_id", client.session)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ProfileInputValidationTests(TestCase):
    def setUp(self):
        self.user = make_alumni()
        self.client.force_login(self.user)

    def payload(self, **overrides):
        data = {
            "name": "Test Alumni", "phone_number": "9876543210", "email_id": "alumni@example.com",
            "country": "India", "state": "Puducherry", "city": "Karaikal", "batch": "2024",
            "degree": "B.Tech", "department": "ECE", "present_address": "Karaikal",
            "linkedin": "", "facebook": "", "instagram": "", "current_status": "none",
        }
        data.update(overrides)
        return data

    def test_javascript_url_is_rejected(self):
        self.client.post(reverse("profile"), self.payload(linkedin="javascript:alert(document.cookie)"))
        self.assertIn(UserData.objects.get(user=self.user).linked_in, (None, ""))

    def test_bare_domain_gets_https(self):
        self.client.post(reverse("profile"), self.payload(linkedin="linkedin.com/in/someone"))
        self.assertEqual(UserData.objects.get(user=self.user).linked_in, "https://linkedin.com/in/someone")

    def test_invalid_batch_does_not_500(self):
        response = self.client.post(reverse("profile"), self.payload(batch="abc"))
        self.assertRedirects(response, reverse("profile"))
        self.assertEqual(UserData.objects.get(user=self.user).batch, 2024)

    def test_overlong_field_does_not_500(self):
        response = self.client.post(reverse("profile"), self.payload(phone_number="1" * 50))
        self.assertRedirects(response, reverse("profile"))
        self.assertEqual(UserData.objects.get(user=self.user).phone_number, "9876543210")

    def test_invalid_email_rejected(self):
        self.client.post(reverse("profile"), self.payload(email_id="not-an-email"))
        self.assertEqual(UserData.objects.get(user=self.user).email_id, "alumni@example.com")

    def test_valid_update_still_saves(self):
        self.client.post(reverse("profile"), self.payload(city="Chennai", linkedin="https://www.linkedin.com/in/x"))
        profile = UserData.objects.get(user=self.user)
        self.assertEqual(profile.city, "Chennai")
        self.assertEqual(profile.linked_in, "https://www.linkedin.com/in/x")


class SocialUrlTests(SimpleTestCase):
    def test_rejects_dangerous_schemes(self):
        from django.core.exceptions import ValidationError
        for value in ("javascript:alert(1)", "data:text/html,<script>", "vbscript:x", "https://", "ftp://x.com"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                clean_social_url(value, "LinkedIn")

    def test_empty_is_allowed(self):
        self.assertEqual(clean_social_url("  ", "LinkedIn"), "")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SIGNUP_LIMIT_PER_IP_PER_HOUR=2)
class SignupRateLimitTests(TestCase):
    def test_signup_attempts_are_limited_per_ip(self):
        for _ in range(2):
            self.client.post(reverse("signup"), {"name": ""})
        response = self.client.post(reverse("signup"), {"name": ""}, follow=True)
        self.assertContains(response, "Too many sign-up attempts")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CONTACT_EMAIL_LIMIT_PER_USER_PER_DAY=2,
)
class ContactEmailLimitTests(TestCase):
    def setUp(self):
        self.sender = make_alumni()
        self.receiver = make_alumni("EC20A0002", "receiver@example.com")
        self.client.force_login(self.sender)
        mail.outbox.clear()

    def send(self, **data):
        payload = {"subject": "Hello", "message": "Hi there"}
        payload.update(data)
        return self.client.post(reverse("contact_alumni", args=[self.receiver.pk]), payload)

    def test_daily_limit(self):
        for _ in range(3):
            self.send()
        self.assertEqual(len(mail.outbox), 2)

    def test_empty_or_overlong_input_rejected(self):
        self.send(subject="")
        self.send(message="x" * 5001)
        self.assertEqual(len(mail.outbox), 0)

    def test_message_html_is_escaped(self):
        self.send(message="<script>alert(1)</script>")
        self.assertNotIn("<script>", mail.outbox[0].body)


class CsvInjectionTests(TestCase):
    def test_safe_cell(self):
        self.assertEqual(safe_cell("=HYPERLINK(\"http://x\")"), "'=HYPERLINK(\"http://x\")")
        self.assertEqual(safe_cell("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(safe_cell("+91 98765-43210"), "+91 98765-43210")
        self.assertEqual(safe_cell("Alice"), "Alice")
        self.assertEqual(safe_cell(2024), 2024)

    def test_admin_export_neutralises_formula_names(self):
        make_alumni(name="=cmd|' /C calc'!A0")
        response = export_as_csv(admin_site._registry[UserData], None, UserData.objects.all())
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        name_index = rows[0].index("name")
        self.assertTrue(rows[1][name_index].startswith("'="))


class SecurityHeaderTests(TestCase):
    def test_headers_present(self):
        response = self.client.get(reverse("login"))
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertIn("object-src 'none'", response["Content-Security-Policy"])
        self.assertIn("geolocation=()", response["Permissions-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")

    def test_no_wildcard_trusted_origin(self):
        self.assertFalse(any("*" in origin for origin in settings.CSRF_TRUSTED_ORIGINS))

    def test_third_party_onrender_origin_rejected(self):
        user = make_alumni()
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get(reverse("profile"))
        token = client.cookies["csrftoken"].value
        response = client.post(
            reverse("logout"), {"csrfmiddlewaretoken": token},
            HTTP_ORIGIN="https://evil.onrender.com", HTTP_HOST="nitpyalumni.com",
            **{"wsgi.url_scheme": "https"},
        )
        self.assertEqual(response.status_code, 403)

    def test_cdn_assets_pinned_with_sri(self):
        import re
        from pathlib import Path
        for path in Path(settings.BASE_DIR, "templates").rglob("*.html"):
            for tag in re.findall(r"<(?:script|link)[^>]+(?:unpkg|jsdelivr)[^>]*>", path.read_text()):
                with self.subTest(path=path.name):
                    self.assertIn("integrity=", tag)
                    self.assertNotIn("unpkg.com/leaflet/", tag)


@override_settings(PASSWORD_RESET_TRUST_RENDER_PROXY=True, LOGIN_FAILURE_LIMIT_PER_IP=2,
                   LOGIN_FAILURE_LIMIT_PER_ACCOUNT=100)
class RenderProxyIpTests(TestCase):
    def test_shared_proxy_address_is_never_ip_limited(self):
        make_alumni()
        for i in range(4):
            self.client.post(reverse("login"), {"email": f"x{i}@example.com", "password": "bad"})
        response = self.client.post(reverse("login"), {"email": "alumni@example.com", "password": PASSWORD})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_cloudflare_client_ip_is_limited(self):
        make_alumni()
        for i in range(2):
            self.client.post(reverse("login"), {"email": f"x{i}@example.com", "password": "bad"},
                             HTTP_CF_CONNECTING_IP="203.0.113.9")
        blocked = self.client.post(reverse("login"), {"email": "alumni@example.com", "password": PASSWORD},
                                   HTTP_CF_CONNECTING_IP="203.0.113.9")
        self.assertEqual(blocked.status_code, 429)
        other = self.client.post(reverse("login"), {"email": "alumni@example.com", "password": PASSWORD},
                                 HTTP_CF_CONNECTING_IP="198.51.100.7")
        self.assertRedirects(other, "/", fetch_redirect_response=False)
