import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, SimpleTestCase, override_settings
from django.urls import reverse

from web.models import DirectMessage, UserData


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SecurityAccountTests(TestCase):
    def test_password_validation_rejects_all_legacy_credentials(self):
        user = User(username="EC20B1234", email="someone@example.com")
        with self.assertRaises(ValidationError):
            validate_password("adminpassword123", user)

    def test_legacy_passwords_cannot_authenticate_including_admin(self):
        for password in ("password123", "adminpassword123"):
            user = User.objects.create_superuser(password, password + "@example.com", password)
            self.assertIsNone(authenticate(username=user.username, password=password))
            response = self.client.post("/admin/login/", {"username": user.username, "password": password})
            self.assertNotIn("_auth_user_id", self.client.session)
            self.assertEqual(response.status_code, 200)

    def test_preexisting_session_with_legacy_password_is_rejected(self):
        user = User.objects.create_superuser("legacy", "legacy@example.com", "password123")
        self.client.force_login(user)
        response = self.client.get("/admin/")
        self.assertRedirects(response, "/admin/login/?next=/admin/", fetch_redirect_response=False)

    def test_preexisting_strong_session_survives_until_explicit_lockdown(self):
        user = User.objects.create_superuser("secure", "secure@example.com", "SafePass!7392")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_mutable_profile_email_cannot_be_used_as_login_alias(self):
        owner = make_profile("owner")
        owner.email_id = "unverified@example.com"
        owner.save()
        self.assertIsNone(authenticate(username="unverified@example.com", password="SafePass!7392"))
        self.client.post(reverse("login"), {"email": "unverified@example.com", "password": "SafePass!7392"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ambiguous_identity_fails_closed(self):
        User.objects.create_user("first", "same@example.com", "SafePass!7392")
        User.objects.create_user("second", "same@example.com", "SafePass!7392")
        self.assertIsNone(authenticate(username="same@example.com", password="SafePass!7392"))

    def test_canonical_email_and_username_remain_case_insensitive(self):
        user = User.objects.create_user("EC20A0001", "owner@example.com", "SafePass!7392")
        for identifier in ("ec20a0001", "OWNER@EXAMPLE.COM"):
            self.assertEqual(authenticate(username=identifier, password="SafePass!7392"), user)

    def test_lockdown_is_dry_run_then_locks_weak_accounts_and_all_sessions(self):
        weak = User.objects.create_superuser("weak", "weak@example.com", "password123")
        strong = User.objects.create_superuser("strong", "strong@example.com", "SafePass!7392")
        self.client.force_login(strong)
        output = io.StringIO()
        call_command("security_lockdown", stdout=output)
        weak.refresh_from_db()
        self.assertTrue(weak.is_active)
        self.assertTrue(weak.is_superuser)
        self.assertTrue(Session.objects.exists())
        self.assertIn(str(weak.pk), output.getvalue())
        self.assertNotIn(weak.email, output.getvalue())
        call_command("security_lockdown", apply=True, stdout=io.StringIO())
        weak.refresh_from_db()
        strong.refresh_from_db()
        self.assertFalse(weak.has_usable_password())
        self.assertFalse(weak.is_active)
        self.assertFalse(weak.is_staff)
        self.assertFalse(weak.is_superuser)
        self.assertTrue(strong.is_superuser)
        self.assertTrue(strong.check_password("SafePass!7392"))
        self.assertFalse(Session.objects.exists())
        call_command("security_lockdown", apply=True, stdout=io.StringIO())
        self.assertFalse(Session.objects.exists())

    def test_lockdown_can_revoke_reviewed_privileged_account_without_deleting_data(self):
        profile = make_profile("reviewed")
        user = profile.user
        user.is_staff = user.is_superuser = True
        user.save()
        call_command("security_lockdown", apply=True, revoke_user=[user.pk], stdout=io.StringIO())
        user.refresh_from_db()
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_active)
        self.assertTrue(UserData.objects.filter(pk=profile.pk).exists())


def make_profile(name, approved=True, active=True):
    user = User.objects.create_user(name, name + "@example.com", "SafePass!7392", is_active=active)
    return UserData.objects.create(
        user=user, roll_no=name, name=name, email_id=user.email, batch=2020,
        phone_number="123", country="India", state="Puducherry", city="Karaikal",
        department="CSE", present_address="Test", account_is_approved=approved,
    )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MessagingSecurityTests(TestCase):
    def setUp(self):
        self.sender = make_profile("sender")
        self.recipient = make_profile("recipient")
        self.client.force_login(self.sender.user)

    def peer_url(self, name, peer=None):
        return reverse(name, args=[peer or self.recipient.user_id])

    def test_contact_email_cannot_bypass_recipient_approval_or_activity(self):
        from django.core import mail
        for profile in (make_profile("pending", approved=False), make_profile("inactive", active=False), self.sender):
            mail.outbox.clear()
            response = self.client.post(reverse("contact_alumni", args=[profile.user_id]), {"subject": "Hello", "message": "Test"})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(len(mail.outbox), 0)

    def test_approved_peer_contact_email_still_works(self):
        from django.core import mail
        mail.outbox.clear()
        response = self.client.post(reverse("contact_alumni", args=[self.recipient.user_id]), {"subject": "Hello", "message": "Test"})
        self.assertRedirects(response, reverse("alumni_map"), fetch_redirect_response=False)
        self.assertEqual(mail.outbox[0].to, [self.recipient.email_id])

    def test_all_chat_endpoints_reject_pending_and_profileless_accounts(self):
        for user in (make_profile("pending", approved=False).user, User.objects.create_user("staff", is_staff=True)):
            self.client.force_login(user)
            for name in ("chats", "chats_partial", "undreaddm", "chat_view", "load_messages", "update_messages", "add_message"):
                with self.subTest(user=user.username, endpoint=name):
                    url = self.peer_url(name) if name in ("chat_view", "load_messages", "update_messages", "add_message") else reverse(name)
                    response = self.client.post(url, data=json.dumps({"text": "hello"}), content_type="application/json") if name in ("add_message", "update_messages") else self.client.get(url)
                    self.assertEqual(response.status_code, 403)

    @patch("web.views.get_chat_db")
    def test_every_peer_endpoint_rejects_unapproved_inactive_and_self_recipient(self, mongo):
        mongo.return_value = Mock()
        for profile in (make_profile("pending", approved=False), make_profile("inactive", active=False), self.sender):
            for name in ("chat_view", "load_messages", "update_messages", "add_message"):
                with self.subTest(peer=profile.name, endpoint=name):
                    url = self.peer_url(name, profile.user_id)
                    response = self.client.post(url, data=json.dumps({"text": "hello"}), content_type="application/json") if name in ("update_messages", "add_message") else self.client.get(url)
                    self.assertIn(response.status_code, (400, 404))

    @patch("web.views.get_chat_db")
    def test_messages_are_scoped_to_both_participants_not_only_chat_hash(self, mongo):
        from web.views import get_chat_key
        # A hash collision/corrupt legacy record must not expose a third party's message.
        key = get_chat_key(str(self.sender.user_id), str(self.recipient.user_id))
        records = [
            {"_id": 1, "chat_key": key, "sender_id": str(self.sender.user_id), "receiver_id": str(self.recipient.user_id), "text": "ours", "datetime_sent": "2026-01-01", "is_seen": False},
            {"_id": 2, "chat_key": key, "sender_id": "999", "receiver_id": "998", "text": "private", "datetime_sent": "2026-01-01", "is_seen": False},
        ]
        mongo.return_value.Chats.find.side_effect = lambda query: MemoryCursor([r.copy() for r in records if matches(r, query)])
        response = self.client.get(self.peer_url("load_messages"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m["text"] for m in response.json()["messages"]], ["ours"])
        self.assertNotIn("chat_key", response.json()["messages"][0])

    @patch("web.views.get_chat_db")
    def test_bad_json_and_non_text_messages_return_400(self, mongo):
        mongo.return_value = Mock()
        for body in ("{", "[]", "null", '{"text":42}', '{"text":{}}', '{"text":""}', json.dumps({"text": "x" * 4001})):
            with self.subTest(body=body[:30]):
                response = self.client.post(self.peer_url("add_message"), data=body, content_type="application/json")
                self.assertEqual(response.status_code, 400)

    @patch("web.views.get_chat_db")
    def test_invalid_offsets_return_400(self, mongo):
        mongo.return_value = Mock()
        for offset in ("x", "-1", "1000000000000"):
            response = self.client.get(self.peer_url("load_messages"), {"offset": offset})
            self.assertEqual(response.status_code, 400)

    def test_invalid_peer_is_404_instead_of_server_error(self):
        response = self.client.get(reverse("chat_view", args=["not-a-user"]))
        self.assertEqual(response.status_code, 404)

    def test_marking_messages_read_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(self.peer_url("update_messages")).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.sender.user)
        self.assertEqual(client.post(self.peer_url("update_messages")).status_code, 403)

    @patch("web.views.get_chat_db", return_value=None)
    def test_new_messages_are_persisted_in_postgres_without_mongo(self, mongo):
        response = self.client.post(self.peer_url("add_message"), data=json.dumps({"text": "hello"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        stored = DirectMessage.objects.get(sender=self.sender.user, receiver=self.recipient.user)
        self.assertEqual(stored.text, "hello")
        self.assertEqual(response.json()["message"]["_id"], str(stored.pk))

    @patch("web.views.get_chat_db")
    def test_mongo_failure_is_controlled_503(self, mongo):
        from pymongo.errors import ServerSelectionTimeoutError
        mongo.side_effect = ServerSelectionTimeoutError("private connection string")
        response = self.client.get(self.peer_url("load_messages"))
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private connection string", status_code=503)

    @patch("web.views.get_chat_db")
    def test_html_message_is_stored_as_text(self, mongo):
        mongo.return_value = Mock()
        payload = '<img src=x onerror="alert(1)">'
        response = self.client.post(self.peer_url("add_message"), data=json.dumps({"text": payload}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        stored = mongo.return_value.Chats.insert_one.call_args.args[0]
        self.assertEqual(stored["text"], payload)
        self.assertEqual(stored["sender_id"], str(self.sender.user_id))
        self.assertEqual(stored["receiver_id"], str(self.recipient.user_id))


def matches(row, query):
    for key, value in query.items():
        if key == "$or":
            if not any(matches(row, part) for part in value):
                return False
        elif key == "$and":
            if not all(matches(row, part) for part in value):
                return False
        elif row.get(key) != value:
            return False
    return True


class MemoryCursor(list):
    def sort(self, *args):
        return self

    def skip(self, offset):
        return MemoryCursor(self[offset:])

    def limit(self, count):
        return MemoryCursor(self[:count])


class BuildSafetyTests(SimpleTestCase):
    def test_repeated_builds_cannot_provision_accounts_or_import_backups(self):
        # Exercise the real shell script. External executables are recording stubs,
        # so old privileged/import commands fail without touching an actual database.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "build.sh"
            script.write_text((settings.BASE_DIR / "build.sh").read_text())
            (root / "backup_userdata.csv").write_text("malicious backup")
            (root / "pip").write_text("#!/bin/sh\nexit 0\n")
            (root / "python").write_text(
                '#!/bin/sh\ncase "$*" in\n'
                '"manage.py collectstatic --no-input"|"manage.py migrate --no-input") exit 0;;\n'
                '*) echo "Unexpected database/account operation" >&2; exit 97;;\nesac\n'
            )
            for executable in ("pip", "python"):
                (root / executable).chmod(0o700)
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"], "DJANGO_SUPERUSER_USERNAME": "claimed", "DJANGO_SUPERUSER_PASSWORD": "supplied", "NAVEEN_RAJ_PASSWORD": "supplied"}
            for _ in range(2):
                result = subprocess.run(["bash", str(script)], cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


class RepositoryDataSafetyTests(SimpleTestCase):
    def test_guard_rejects_credentials_in_source_without_echoing_values(self):
        from scripts.check_repository_data import find_violations
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "settings.py").write_text('EMAIL_HOST_' + 'PASSWORD = "synthetic-do-not-use"\n')
            (root / "views.py").write_text('uri = "mongodb' + '+srv://test:synthetic@localhost/db"\n')
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            self.assertEqual(find_violations(root), ["settings.py", "views.py"])

    def test_guard_rejects_tracked_data_even_when_ignored(self):
        from scripts.check_repository_data import find_violations
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            for name, content in {
                "backup_userdata.csv": "name,email_id,phone_number\nSynthetic,test@example.com,123\n",
                "server.log": "synthetic log",
                "db.sqlite3": "synthetic database",
                "cached.pyc": "synthetic bytecode",
                ".env": "SECRET_KEY=synthetic",
                ".env.example": "SECRET_KEY=",
                "README.md": "public instructions",
            }.items():
                (root / name).write_text(content)
            subprocess.run(["git", "-C", str(root), "add", "-f", "."], check=True)
            (root / ".gitignore").write_text("*.csv\n*.log\n.env\n*.sqlite3\n")
            violations = find_violations(root)
            self.assertEqual(set(violations), {"backup_userdata.csv", "server.log", "db.sqlite3", "cached.pyc", ".env"})

    def test_guard_detects_renamed_personal_data_csv(self):
        from scripts.check_repository_data import find_violations
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "export.csv").write_text("id,name,email_id,phone_number\n1,Synthetic,test@example.com,123\n")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            self.assertEqual(find_violations(root), ["export.csv"])
