"""Regression checks for the election integrity issues found in the audit."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import mock, skipUnless

from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from elections import notifications, services
from elections.eligibility import can_vote, eligible_voters
from elections.models import Election, ElectionMail, Nomination, Vote, VoterRecord
from elections.services import ElectionError
from elections.tests import make_alumnus, make_election, fixture_position, approved_nomination, set_phase, Phase


class ElectionIntegrityTests(TestCase):
    def setUp(self):
        self.election = make_election(Phase.VOTING_OPEN)
        self.position = fixture_position(election=self.election, title="President")
        self.nomination = approved_nomination(self.election, self.position, make_alumnus())
        self.voter = make_alumnus()
        self.choices = {self.position.pk: self.nomination.pk}
        mail.outbox.clear()

    def test_fresh_election_and_member_are_checked_before_writing(self):
        User.objects.filter(pk=self.voter.user_id).update(is_active=False)
        with self.assertRaises(ElectionError):
            services.cast_ballot(self.election, self.voter, self.choices)
        self.voter.user.refresh_from_db()
        self.assertFalse(can_vote(self.voter))
        self.assertFalse(eligible_voters().filter(pk=self.voter.pk).exists())
        User.objects.filter(pk=self.voter.user_id).update(is_active=True)
        # Simulate another transaction closing the election before this request acquired its lock.
        Election.objects.filter(pk=self.election.pk).update(voting_end=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ElectionError):
            services.cast_ballot(self.election, self.voter, self.choices)
        self.assertFalse(Vote.objects.exists())

    def test_started_election_records_cannot_be_changed_or_bulk_deleted(self):
        self.election.voting_end += timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.election.save()
        for model, pk in ((Election, self.election.pk), (Nomination, self.nomination.pk)):
            with self.assertRaises(ValidationError), transaction.atomic():
                model.objects.filter(pk=pk).delete()
        self.nomination.manifesto = "Replacement after voting started"
        with self.assertRaises(ValidationError):
            self.nomination.save()

    def test_voter_profile_deletion_cannot_remove_double_vote_protection(self):
        services.cast_ballot(self.election, self.voter, self.choices)
        with self.assertRaises(ProtectedError):
            self.voter.delete()
        self.assertEqual(VoterRecord.objects.count(), 1)
        self.assertEqual(Vote.objects.count(), 1)

    def test_published_results_cannot_reopen_or_change_turnout_snapshot(self):
        services.cast_ballot(self.election, self.voter, self.choices)
        set_phase(self.election, Phase.CLOSED)
        services.publish_results(self.election)
        self.election.refresh_from_db()
        self.election.voting_end = timezone.now()+timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.election.save()
        self.election.refresh_from_db()
        self.election.eligible_voter_count = 999
        with self.assertRaises(ValidationError):
            self.election.save()

    def test_database_rejects_invalid_timeline(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Election.objects.filter(pk=self.election.pk).update(voting_end=self.election.voting_start)

    def test_csrf_required_and_ballot_pages_not_cached(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.voter.user)
        url = f"/elections/{self.election.pk}/vote/"
        self.assertIn("no-store", client.get(url).headers["Cache-Control"])
        self.assertEqual(client.post(url, {"action": "confirm"}).status_code, 403)
        self.assertFalse(Vote.objects.exists())

    @override_settings(DEFAULT_FROM_EMAIL="accounts@nitpyalumni.com", EMAIL_HOST_USER="resend", ELECTION_EMAIL_DAILY_LIMIT=2)
    def test_receipt_canonical_sender_quota_and_uncertain_delivery(self):
        self.voter.email_id = "editable-contact@example.com"
        self.voter.save()
        mail.outbox.clear()
        services.cast_ballot(self.election, self.voter, self.choices)
        receipt = ElectionMail.objects.get(priority=10)
        self.assertEqual(receipt.recipient, self.voter.user.email)
        self.assertEqual(notifications.deliver_pending(), 1)
        self.assertEqual(mail.outbox[0].from_email, "accounts@nitpyalumni.com")
        notifications.queue(self.election, "second", "second@example.com", "Test", "No choices")
        with mock.patch("elections.notifications.EmailMessage.send", side_effect=OSError("private SMTP detail")):
            self.assertEqual(notifications.deliver_pending(), 0)
        self.assertEqual(ElectionMail.objects.filter(status="sending").count(), 1)
        notifications.queue(self.election, "third", "third@example.com", "Test", "No choices")
        self.assertEqual(notifications.deliver_pending(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Vote.objects.count(), 1)

    def test_rollback_does_not_send_receipt_or_keep_partial_ballot(self):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError), transaction.atomic():
                services.cast_ballot(self.election, self.voter, self.choices)
                raise RuntimeError("Rollback fixture")
        self.assertFalse(Vote.objects.exists())
        self.assertFalse(VoterRecord.objects.exists())
        self.assertFalse(ElectionMail.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_expired_announcements_are_not_sent(self):
        services.announce_voting_open(self.election)
        set_phase(self.election, Phase.CLOSED)
        self.assertEqual(notifications.deliver_pending(), 0)
        self.assertFalse(ElectionMail.objects.exclude(status="expired").exists())


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
@override_settings(ELECTION_EMAIL_DAILY_LIMIT=0)
class ConcurrentElectionTests(TransactionTestCase):
    def test_parallel_ballots_record_exactly_one_ballot_and_receipt(self):
        election = make_election(Phase.VOTING_OPEN)
        position = fixture_position(election=election, title="President")
        nomination = approved_nomination(election, position, make_alumnus())
        voter = make_alumnus()
        barrier = Barrier(2)

        def cast(index):
            try:
                barrier.wait(timeout=10)
                services.cast_ballot(election, voter, {position.pk: nomination.pk})
                return "accepted"
            except ElectionError:
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(cast, range(2))), ["accepted", "rejected"])
        self.assertEqual(VoterRecord.objects.count(), 1)
        self.assertEqual(Vote.objects.count(), 1)
        self.assertEqual(ElectionMail.objects.filter(priority=10).count(), 1)
