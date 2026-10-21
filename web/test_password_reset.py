import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core import mail
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from web.test_security import make_profile


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordRecoveryTests(TestCase):
    password = "NewSafe!7392Recovery"

    def request_link(self, email, **kwargs):
        return self.client.post("/password-reset/", {"email": email}, **kwargs)

    def link(self):
        return re.search(r"https://nitpyalumni\.com(/reset/\S+)", mail.outbox[-1].body)[1]

    def finish(self, link, client=None, password=None):
        client = client or self.client
        response = client.get(link)
        self.assertEqual(response.status_code, 302)
        return client.post(response.url, {
            "new_password1": password or self.password,
            "new_password2": password or self.password,
        })

    def test_login_offers_password_recovery(self):
        self.assertContains(self.client.get("/login/"), 'href="/password-reset/"')

    def test_locked_unusable_account_recovers_without_changing_profile_or_roles(self):
        profile = make_profile("recover", approved=False, active=False)
        user = profile.user
        user.set_unusable_password()
        user.save()
        original_profile = type(profile).objects.values().get(pk=profile.pk)
        self.assertEqual(self.request_link(user.email.upper()).status_code, 302)
        self.assertEqual(mail.outbox[-1].to, [user.email])
        user.refresh_from_db()
        self.assertFalse(user.is_active)  # Requesting alone must never unlock.
        link = self.link()
        response = self.finish(link)
        self.assertRedirects(response, "/password-reset/complete/")
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(self.password))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(type(profile).objects.values().get(pk=profile.pk), original_profile)
        self.assertEqual(authenticate(username=user.email, password=self.password), user)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotContains(Client().get(link), 'name="new_password1"')

    def test_active_account_reset_invalidates_existing_login(self):
        user = User.objects.create_user("active", "active@example.com", "SafePass!7392")
        other = Client()
        other.force_login(user)
        self.request_link(user.email)
        self.finish(self.link())
        other.get("/profile/")
        self.assertNotIn("_auth_user_id", other.session)

    def test_unknown_duplicate_and_profile_contact_emails_do_not_receive_links(self):
        profile = make_profile("identity")
        profile.email_id = "editable@example.com"
        profile.save()
        User.objects.create_user("duplicate", profile.user.email.upper(), "SafePass!7392")
        mail.outbox.clear()
        for email in ("missing@example.com", "editable@example.com", profile.user.email):
            response = self.request_link(email, REMOTE_ADDR="192.0.2.1")
            self.assertRedirects(response, "/password-reset/sent/")
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_email_uses_canonical_https_origin_even_with_different_host(self):
        user = User.objects.create_user("origin", "origin@example.com", "SafePass!7392")
        self.request_link(user.email, HTTP_HOST="other.onrender.com")
        self.assertIn("https://nitpyalumni.com/reset/", mail.outbox[-1].body)
        self.assertNotIn("other.onrender.com", mail.outbox[-1].body)

    def test_expired_and_tampered_links_cannot_unlock_account(self):
        user = User.objects.create_user("expired", "expired@example.com", None, is_active=False)
        self.request_link(user.email)
        link = self.link()
        self.assertNotContains(self.client.get(link.rstrip("/") + "invalid/"), 'name="new_password1"')
        with patch("django.contrib.auth.tokens.PasswordResetTokenGenerator._now", return_value=datetime.now() + timedelta(seconds=3601)):
            self.assertNotContains(self.client.get(link), 'name="new_password1"')
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_legacy_password_is_rejected_without_activating(self):
        user = User.objects.create_user("weak", "weak@example.com", None, is_active=False)
        self.request_link(user.email)
        response = self.finish(self.link(), password="password123")
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())

    def test_repeated_requests_are_throttled_across_clients(self):
        user = User.objects.create_user("limited", "limited@example.com", None)
        self.request_link(user.email)
        Client().post("/password-reset/", {"email": user.email.upper()})
        self.assertEqual(len(mail.outbox), 1)

    def test_ip_limit_applies_even_when_addresses_change(self):
        for i in range(11):
            user = User.objects.create_user(f"flood{i}", f"flood{i}@example.com", None)
            self.request_link(user.email)
        self.assertEqual(len(mail.outbox), 10)

    def test_requests_and_password_submission_require_csrf(self):
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post("/password-reset/", {"email": "someone@example.com"}).status_code, 403)
        user = User.objects.create_user("csrf", "csrf@example.com", None)
        self.request_link(user.email)
        response = strict.get(self.link())
        self.assertEqual(strict.post(response.url, {"new_password1": self.password, "new_password2": self.password}).status_code, 403)

    def test_password_submission_with_csrf_token_and_site_origin_succeeds(self):
        strict = Client(enforce_csrf_checks=True)
        user = User.objects.create_user("csrfok", "csrfok@example.com", None, is_active=False)
        self.request_link(user.email)
        form_url = strict.get(self.link()).url
        strict.get(form_url)
        token = strict.cookies["csrftoken"].value
        data = {"new_password1": self.password, "new_password2": self.password, "csrfmiddlewaretoken": token}
        # A null Origin (what no-referrer caused in Chrome) is rejected...
        self.assertEqual(strict.post(form_url, data, HTTP_ORIGIN="null").status_code, 403)
        # ...while the site's real Origin, sent under same-origin, is accepted.
        response = strict.post(form_url, data, HTTP_ORIGIN="https://www.nitpyalumni.com")
        self.assertRedirects(response, "/password-reset/complete/")
        user.refresh_from_db()
        self.assertTrue(user.check_password(self.password))

    def test_separate_sessions_cannot_redeem_same_link_twice(self):
        user = User.objects.create_user("twice", "twice@example.com", None)
        self.request_link(user.email)
        link = self.link()
        first, second = Client(), Client()
        first_url = first.get(link).url
        second_url = second.get(link).url
        data = {"new_password1": self.password, "new_password2": self.password}
        self.assertRedirects(first.post(first_url, data), "/password-reset/complete/")
        self.assertNotContains(second.post(second_url, data), 'name="new_password1"')

    def test_smtp_failure_does_not_disclose_account_or_exception(self):
        import smtplib
        User.objects.create_user("delivery", "delivery@example.com", None)
        with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=smtplib.SMTPException("private detail")):
            with self.assertLogs("web.password_reset", level="ERROR") as logs:
                response = self.request_link("delivery@example.com")
        self.assertRedirects(response, "/password-reset/sent/")
        self.assertNotIn("private detail", " ".join(logs.output))

    def test_request_limits_expire_and_allow_retry(self):
        user = User.objects.create_user("retry", "retry@example.com", None)
        self.request_link(user.email)
        with patch("web.password_reset.timezone.now", return_value=timezone.now() + timedelta(hours=3)):
            self.request_link(user.email)
        self.assertEqual(len(mail.outbox), 2)

    def test_reset_pages_do_not_leak_referrers_or_allow_caching(self):
        user = User.objects.create_user("headers", "headers@example.com", None)
        self.request_link(user.email)
        response = self.client.get(self.link())
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
        self.assertEqual(self.client.get(response.url).headers["Referrer-Policy"], "same-origin")
        self.assertIn("no-store", response.headers["Cache-Control"])

    @override_settings(EMAIL_HOST_USER="resend", DEFAULT_FROM_EMAIL="accounts@nitpyalumni.com")
    def test_transactional_emails_use_sender_address_not_smtp_login(self):
        profile = make_profile("mailfrom", approved=False)
        self.assertEqual(mail.outbox[-1].from_email, "accounts@nitpyalumni.com")
        profile.account_is_approved = True
        profile.save()
        self.assertEqual(mail.outbox[-1].from_email, "accounts@nitpyalumni.com")
        self.request_link(profile.user.email)
        self.assertEqual(mail.outbox[-1].from_email, "accounts@nitpyalumni.com")

    @override_settings(PASSWORD_RESET_TRUST_RENDER_PROXY=True)
    def test_render_clients_do_not_share_the_proxy_ip_limit(self):
        for i in range(11):
            user = User.objects.create_user(f"proxy{i}", f"proxy{i}@example.com", None)
            self.request_link(user.email, HTTP_CF_CONNECTING_IP=f"192.0.2.{i + 1}", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(len(mail.outbox), 11)

    @override_settings(PASSWORD_RESET_TRUST_RENDER_PROXY=False)
    def test_untrusted_forwarding_headers_do_not_bypass_ip_limit(self):
        for i in range(11):
            user = User.objects.create_user(f"spoof{i}", f"spoof{i}@example.com", None)
            self.request_link(user.email, HTTP_CF_CONNECTING_IP=f"192.0.2.{i + 1}", HTTP_X_FORWARDED_FOR=f"192.0.2.{i + 1}")
        self.assertEqual(len(mail.outbox), 10)


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL row locks")
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ConcurrentPasswordRecoveryTests(TransactionTestCase):
    def simultaneously(self, action):
        barrier = Barrier(2)

        def run(index):
            try:
                barrier.wait(timeout=10)
                return action(index)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, range(2)))

    def test_concurrent_submissions_only_redeem_once(self):
        user = User.objects.create_user("concurrent", "concurrent@example.com", None, is_active=False)
        self.client.post("/password-reset/", {"email": user.email})
        link = re.search(r"https://nitpyalumni\.com(/reset/\S+)", mail.outbox[-1].body)[1]
        clients = [Client(), Client()]
        urls = [client.get(link).url for client in clients]

        def submit(index):
            password = f"Concurrent!Safe{index}7392"
            return clients[index].post(urls[index], {
                "new_password1": password, "new_password2": password,
            }).status_code

        self.assertEqual(sorted(self.simultaneously(submit)), [200, 302])
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(any(user.check_password(f"Concurrent!Safe{i}7392") for i in range(2)))
        self.assertEqual(User.objects.count(), 1)

    def test_concurrent_request_limits_allow_only_one_sender(self):
        from web.password_reset import consume_reset_limit
        results = self.simultaneously(lambda index: consume_reset_limit("race@example.com", f"192.0.2.{index + 1}"))
        self.assertEqual(sorted(results), [False, True])
