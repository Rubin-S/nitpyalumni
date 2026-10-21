from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth.models import User
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings

from web.models import UserData
from web.test_security import make_profile


def profile_details(account, **changes):
    data = dict(
        profile_mode="create", name="Test Alumni", phone_number="9876543210",
        email_id=account.email, country="India", state="Puducherry", city="Karaikal",
        batch="2028", degree="B.Tech", department="Electronics and Communication Engineering",
        present_address="Test address", current_status="none",
    )
    data.update(changes)
    return data


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ProfileCompletionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("EC24B1042", "owner@example.com", "SafePass!7392")
        self.client.force_login(self.user)

    def payload(self, **changes):
        return profile_details(self.user, **changes)

    def test_profileless_account_gets_completion_form_without_creating_data(self):
        response = self.client.get("/profile/")
        self.assertContains(response, "Complete your alumni profile")
        self.assertContains(response, self.user.username)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertFalse(UserData.objects.filter(user=self.user).exists())

    def test_completion_creates_only_pending_profile_bound_to_existing_account(self):
        other = make_profile("other")
        original = UserData.objects.values().get(pk=other.pk)
        response = self.client.post("/profile/", self.payload(
            user_id=other.user_id, user=other.user_id, roll_no="CS20B9999",
            email_id="attacker@example.com", account_is_approved="true",
            is_eligible_to_vote="true", is_staff="true", is_superuser="true",
        ))
        self.assertRedirects(response, "/profile/")
        profile = UserData.objects.get(user=self.user)
        self.assertEqual(profile.roll_no, self.user.username)
        self.assertEqual(profile.email_id, self.user.email)
        self.assertFalse(profile.account_is_approved)
        self.assertFalse(profile.is_eligible_to_vote)
        self.assertEqual(UserData.objects.values().get(pk=other.pk), original)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(User.objects.count(), 2)
        self.assertContains(self.client.get("/profile/"), "pending administrator approval")
        self.assertEqual(self.client.get("/chats/").status_code, 403)

    def test_invalid_completion_keeps_submitted_values_and_creates_nothing(self):
        for changes in ({"name": ""}, {"batch": "not-a-year"}, {"current_status": "admin"},
                        {"linkedin": "javascript:alert(1)"}, {"country": "X" * 101},
                        {"degree": "Not a degree"}, {"department": "Not a department"}):
            with self.subTest(changes=changes):
                response = self.client.post("/profile/", self.payload(**changes))
                self.assertContains(response, "Please correct the errors")
                self.assertContains(response, "Test address")
                self.assertFalse(UserData.objects.filter(user=self.user).exists())

    def test_replayed_creation_does_not_overwrite_existing_profile_or_approval(self):
        self.client.post("/profile/", self.payload())
        profile = UserData.objects.get(user=self.user)
        UserData.objects.filter(pk=profile.pk).update(account_is_approved=True)
        original = UserData.objects.values().get(pk=profile.pk)
        self.assertRedirects(self.client.post("/profile/", self.payload(name="Replacement")), "/profile/")
        self.assertEqual(UserData.objects.values().get(pk=profile.pk), original)

    def test_existing_profile_edit_preserves_identity_and_permissions(self):
        profile = make_profile("existing")
        UserData.objects.filter(pk=profile.pk).update(is_eligible_to_vote=True)
        self.client.force_login(profile.user)
        response = self.client.post("/profile/", self.payload(
            profile_mode="edit", roll_no="FAKE", user_id=self.user.pk,
            name="Edited Name", email_id="contact@example.com", account_is_approved="false",
            is_eligible_to_vote="false", current_status="study", higher_study_uni_name="Test University",
            job_title="Discard this inactive field", linkedin="https://example.com/profile",
        ))
        self.assertRedirects(response, "/profile/")
        profile.refresh_from_db()
        self.assertEqual(profile.name, "Edited Name")
        self.assertEqual(profile.roll_no, "existing")
        self.assertEqual(profile.user_id, profile.user.pk)
        self.assertTrue(profile.account_is_approved)
        self.assertTrue(profile.is_eligible_to_vote)
        self.assertEqual(profile.email_id, "contact@example.com")
        self.assertNotEqual(profile.user.email, profile.email_id)
        self.assertEqual(profile.linked_in, "https://example.com/profile")
        self.assertEqual(profile.higher_study_uni_name, "Test University")
        self.assertFalse(profile.in_job)
        self.assertFalse(profile.job_title)

    def test_invalid_edit_does_not_partially_save(self):
        profile = make_profile("existing")
        self.client.force_login(profile.user)
        original = UserData.objects.values().get(pk=profile.pk)
        self.assertContains(self.client.post("/profile/", self.payload(
            profile_mode="edit", name="Changed", batch="invalid")), "Please correct the errors")
        self.assertEqual(UserData.objects.values().get(pk=profile.pk), original)

    def test_home_and_blocked_dms_explain_missing_profile_and_how_to_complete_it(self):
        self.assertContains(self.client.get("/"), "Complete your alumni profile")
        response = self.client.get("/chats/")
        self.assertContains(response, "Complete your alumni profile", status_code=403)
        self.assertContains(response, 'href="/profile/"', status_code=403)

    def test_pending_dms_explain_approval_without_exposing_messages(self):
        profile = make_profile("pending", approved=False)
        self.client.force_login(profile.user)
        self.assertContains(self.client.get("/chats/"), "pending administrator approval", status_code=403)
        api = self.client.get("/chats/undreaddm/")
        self.assertEqual(api.status_code, 403)
        self.assertEqual(api.json(), {"error": "An approved alumni account is required."})

    def test_profile_creation_requires_authentication_and_csrf(self):
        self.assertEqual(Client().post("/profile/", self.payload()).status_code, 302)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post("/profile/", self.payload()).status_code, 403)
        self.assertFalse(UserData.objects.filter(user=self.user).exists())

    def test_profile_creation_accepts_valid_csrf_and_work_status(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        strict.get("/profile/")
        response = strict.post("/profile/", self.payload(
            csrfmiddlewaretoken=strict.cookies["csrftoken"].value,
            current_status="job", job_title="Engineer", higher_study_uni_name="Discard this field",
        ))
        self.assertRedirects(response, "/profile/")
        profile = UserData.objects.get(user=self.user)
        self.assertTrue(profile.in_job)
        self.assertEqual(profile.job_title, "Engineer")
        self.assertFalse(profile.higher_study_uni_name)

    def test_profileless_staff_still_go_to_administration(self):
        staff = User.objects.create_user("staff", is_staff=True)
        self.client.force_login(staff)
        self.assertRedirects(self.client.get("/profile/"), "/admin/", fetch_redirect_response=False)


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ConcurrentProfileCompletionTests(TransactionTestCase):
    def test_concurrent_creation_requests_create_once_without_overwriting(self):
        user = User.objects.create_user("EC24B1042", "owner@example.com", "SafePass!7392")
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(user)
        # Use the same legitimate form twice; the second carries altered details.
        barrier = Barrier(2)

        def submit(index):
            try:
                barrier.wait(timeout=10)
                return clients[index].post("/profile/", profile_details(user, name=f"Submission {index}")).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(submit, (0, 1))), [302, 302])
        self.assertEqual(UserData.objects.filter(user=user).count(), 1)
        profile = UserData.objects.get(user=user)
        self.assertIn(profile.name, ["Submission 0", "Submission 1"])
        self.assertFalse(profile.account_is_approved)
        from django.core import mail
        self.assertEqual(len(mail.outbox), 1, "Only the actual creation should send an application notification")
