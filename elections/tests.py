import os
from datetime import timedelta
from unittest import mock

from django.contrib import admin
from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import models
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from elections import notifications, services
from elections.eligibility import can_nominate, can_vote, eligible_voters
from elections.models import Election, ElectionMail, Nomination, Position, Vote, VoterRecord
from elections.notifications import VOTING_OPEN_BATCH_SIZE
from elections.services import ElectionError
from web.models import UserData

# Never hit the external geocoding API from tests.
os.environ.pop("GEOCODING_API_KEY", None)

Phase = Election.Phase

# Day offsets (nomination_start, nomination_end, voting_start, voting_end)
# that put "now" inside the given phase.
PHASE_OFFSETS = {
    Phase.UPCOMING: (1, 2, 3, 4),
    Phase.NOMINATIONS_OPEN: (-1, 1, 2, 3),
    Phase.NOMINATIONS_CLOSED: (-2, -1, 1, 2),
    Phase.VOTING_OPEN: (-3, -2, -1, 1),
    Phase.CLOSED: (-4, -3, -2, -1),
}


def phase_dates(phase):
    now = timezone.now()
    ns, ne, vs, ve = (now + timedelta(days=d) for d in PHASE_OFFSETS[phase])
    return {"nomination_start": ns, "nomination_end": ne, "voting_start": vs, "voting_end": ve}


def make_election(phase=Phase.NOMINATIONS_OPEN, published=True, title="Alumni Elections 2026"):
    election = Election(title=title, is_published=published, **phase_dates(phase))
    Election.objects.bulk_create([election])
    return election


def set_phase(election, phase):
    for field, value in phase_dates(phase).items():
        setattr(election, field, value)
    # Simulate passage of time in fixtures, bypassing production timeline locks.
    Election.objects.filter(pk=election.pk).update(**phase_dates(phase))
    election.refresh_from_db()
    return election


_counter = {"n": 0}


def make_alumnus(name=None, approved=True, eligible=True):
    _counter["n"] += 1
    n = _counter["n"]
    username = f"CS20B{n:04d}"
    user = User.objects.create(username=username, email=f"{username.lower()}@example.com")
    return UserData.objects.create(
        user=user, roll_no=username, name=name or f"Alumnus {n}", phone_number="9999999999",
        country="India", state="Puducherry", city="Karaikal", batch=2020, department="CSE",
        degree="B.Tech", email_id=f"{username.lower()}@example.com", present_address="Karaikal",
        account_is_approved=approved, is_eligible_to_vote=eligible,
    )


def fixture_position(**kwargs):
    # Seed a pre-existing ballot without mutating a live election.
    obj = Position(**kwargs)
    Position.objects.bulk_create([obj])
    return obj


def fixture_nomination(**kwargs):
    obj = Nomination(**kwargs)
    Nomination.objects.bulk_create([obj])
    return obj


def approved_nomination(election, position, candidate, manifesto="Vote for me"):
    return fixture_nomination(
        election=election, position=position, candidate=candidate,
        manifesto=manifesto, status=Nomination.Status.APPROVED,
    )


# --------------------------------------------------------------------------- #
# Model / phase
# --------------------------------------------------------------------------- #

class ElectionPhaseTests(TestCase):
    def setUp(self):
        self.base = timezone.now()
        d = timedelta(days=1)
        self.election = Election(
            title="E", is_published=True,
            nomination_start=self.base, nomination_end=self.base + d,
            voting_start=self.base + 2 * d, voting_end=self.base + 3 * d,
        )

    def test_phase_boundaries(self):
        e, b, d = self.election, self.base, timedelta(days=1)
        s = timedelta(seconds=1)
        self.assertEqual(e.phase_at(b - s), Phase.UPCOMING)
        self.assertEqual(e.phase_at(b), Phase.NOMINATIONS_OPEN)
        self.assertEqual(e.phase_at(b + d - s), Phase.NOMINATIONS_OPEN)
        self.assertEqual(e.phase_at(b + d), Phase.NOMINATIONS_CLOSED)
        self.assertEqual(e.phase_at(b + 2 * d), Phase.VOTING_OPEN)
        self.assertEqual(e.phase_at(b + 3 * d - s), Phase.VOTING_OPEN)
        self.assertEqual(e.phase_at(b + 3 * d), Phase.CLOSED)

    def test_unpublished_is_draft(self):
        self.election.is_published = False
        self.assertEqual(self.election.phase_at(self.base + timedelta(days=2)), Phase.DRAFT)

    def test_clean_accepts_valid_dates(self):
        self.election.clean()

    def test_clean_rejects_bad_order(self):
        self.election.voting_start = self.base  # before nomination_end
        with self.assertRaises(ValidationError):
            self.election.clean()
        self.election.voting_start = self.base + timedelta(days=5)  # after voting_end
        with self.assertRaises(ValidationError):
            self.election.clean()


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #

class EligibilityTests(TestCase):
    def test_can_vote_truth_table(self):
        self.assertFalse(can_vote(None))
        self.assertFalse(can_vote(make_alumnus(approved=False, eligible=True)))
        self.assertFalse(can_vote(make_alumnus(approved=True, eligible=False)))
        self.assertFalse(can_vote(make_alumnus(approved=False, eligible=False)))
        self.assertTrue(can_vote(make_alumnus(approved=True, eligible=True)))

    def test_can_nominate_matches_can_vote(self):
        self.assertTrue(can_nominate(make_alumnus()))
        self.assertFalse(can_nominate(make_alumnus(eligible=False)))

    def test_eligible_voters_queryset_matches_can_vote(self):
        people = [
            make_alumnus(approved=a, eligible=e) for a in (True, False) for e in (True, False)
        ]
        expected = {p.pk for p in people if can_vote(p)}
        self.assertEqual(set(eligible_voters().values_list("pk", flat=True)), expected)

    def test_new_userdata_defaults_to_not_eligible(self):
        user = User.objects.create(username="XX99X9999")
        ud = UserData.objects.create(
            user=user, roll_no="XX99X9999", name="New", phone_number="1", country="IN",
            state="PY", city="KKL", batch=2024, department="ECE", email_id="n@example.com",
            present_address="x",
        )
        self.assertFalse(ud.is_eligible_to_vote)


# --------------------------------------------------------------------------- #
# Nominations
# --------------------------------------------------------------------------- #

class NominationServiceTests(TestCase):
    def setUp(self):
        self.election = make_election(Phase.NOMINATIONS_OPEN)
        self.president = fixture_position(election=self.election, title="President", order=1)
        self.secretary = fixture_position(election=self.election, title="Secretary", order=2)
        self.alice = make_alumnus("Alice")
        mail.outbox.clear()

    def test_submit_nomination_success_emails_staff(self):
        with self.captureOnCommitCallbacks(execute=True):
            nom = services.submit_nomination(self.election, self.president, self.alice, " My plan ")
        self.assertEqual(nom.status, Nomination.Status.PENDING)
        self.assertEqual(nom.manifesto, "My plan")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Alice", mail.outbox[0].subject)

    def test_only_during_nomination_window(self):
        for phase in (Phase.UPCOMING, Phase.NOMINATIONS_CLOSED, Phase.VOTING_OPEN, Phase.CLOSED):
            set_phase(self.election, phase)
            with self.assertRaises(ElectionError):
                services.submit_nomination(self.election, self.president, self.alice, "x")

    def test_ineligible_cannot_nominate(self):
        bob = make_alumnus("Bob", eligible=False)
        with self.assertRaises(ElectionError):
            services.submit_nomination(self.election, self.president, bob, "x")

    def test_empty_or_too_long_manifesto_rejected(self):
        with self.assertRaises(ElectionError):
            services.submit_nomination(self.election, self.president, self.alice, "   ")
        with self.assertRaises(ElectionError):
            services.submit_nomination(
                self.election, self.president, self.alice,
                "x" * (Nomination.MANIFESTO_MAX_LENGTH + 1),
            )

    def test_position_from_other_election_rejected(self):
        other = make_election(Phase.NOMINATIONS_OPEN, title="Other")
        other_pos = fixture_position(election=other, title="Treasurer")
        with self.assertRaises(ElectionError):
            services.submit_nomination(self.election, other_pos, self.alice, "x")

    def test_one_active_nomination_per_election(self):
        services.submit_nomination(self.election, self.president, self.alice, "x")
        with self.assertRaises(ElectionError):
            services.submit_nomination(self.election, self.secretary, self.alice, "y")

    def test_withdraw_then_renominate(self):
        nom = services.submit_nomination(self.election, self.president, self.alice, "x")
        services.withdraw_nomination(nom, self.alice)
        nom.refresh_from_db()
        self.assertEqual(nom.status, Nomination.Status.WITHDRAWN)
        again = services.submit_nomination(self.election, self.secretary, self.alice, "y")
        self.assertEqual(again.position, self.secretary)

    def test_cannot_withdraw_others_nomination(self):
        nom = services.submit_nomination(self.election, self.president, self.alice, "x")
        with self.assertRaises(ElectionError):
            services.withdraw_nomination(nom, make_alumnus("Mallory"))

    def test_cannot_withdraw_once_voting_open(self):
        nom = services.submit_nomination(self.election, self.president, self.alice, "x")
        set_phase(self.election, Phase.VOTING_OPEN)
        nom.refresh_from_db()
        with self.assertRaises(ElectionError):
            services.withdraw_nomination(nom, self.alice)

    def test_review_sends_candidate_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            nom = services.submit_nomination(self.election, self.president, self.alice, "x")
        notifications.deliver_pending()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.review_nomination(nom, approve=True)
        nom.refresh_from_db()
        self.assertEqual(nom.status, Nomination.Status.APPROVED)
        self.assertIsNotNone(nom.reviewed_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.alice.email_id])
        self.assertIn("approved", mail.outbox[0].subject)

        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.review_nomination(nom, approve=False)
        self.assertIn("rejected", mail.outbox[0].subject)

    def test_review_not_allowed_during_voting(self):
        nom = services.submit_nomination(self.election, self.president, self.alice, "x")
        set_phase(self.election, Phase.VOTING_OPEN)
        nom.refresh_from_db()
        with self.assertRaises(ElectionError):
            services.review_nomination(nom, approve=True)


# --------------------------------------------------------------------------- #
# Ballots
# --------------------------------------------------------------------------- #

class BallotServiceTests(TestCase):
    def setUp(self):
        self.election = make_election(Phase.VOTING_OPEN)
        self.president = fixture_position(election=self.election, title="President", order=1)
        self.secretary = fixture_position(election=self.election, title="Secretary", order=2)
        self.cand_p1 = approved_nomination(self.election, self.president, make_alumnus("Priya"))
        self.cand_p2 = approved_nomination(self.election, self.president, make_alumnus("Pranav"))
        self.cand_s1 = approved_nomination(self.election, self.secretary, make_alumnus("Sara"))
        self.voter = make_alumnus("Voter")
        mail.outbox.clear()

    def test_cast_full_ballot(self):
        services.cast_ballot(self.election, self.voter, {
            self.president.pk: self.cand_p1.pk, self.secretary.pk: self.cand_s1.pk,
        })
        self.assertEqual(VoterRecord.objects.filter(election=self.election).count(), 1)
        self.assertEqual(Vote.objects.filter(election=self.election).count(), 2)

    def test_skipping_positions_allowed(self):
        services.cast_ballot(self.election, self.voter, {self.president.pk: self.cand_p2.pk})
        self.assertEqual(Vote.objects.count(), 1)

    def test_empty_ballot_rejected(self):
        with self.assertRaises(ElectionError):
            services.cast_ballot(self.election, self.voter, {})
        self.assertFalse(VoterRecord.objects.exists())

    def test_only_while_voting_open(self):
        for phase in (Phase.NOMINATIONS_OPEN, Phase.NOMINATIONS_CLOSED, Phase.CLOSED):
            set_phase(self.election, phase)
            with self.assertRaises(ElectionError):
                services.cast_ballot(self.election, self.voter, {self.president.pk: self.cand_p1.pk})
        self.assertFalse(Vote.objects.exists())

    def test_ineligible_cannot_vote(self):
        for person in (make_alumnus(eligible=False), make_alumnus(approved=False)):
            with self.assertRaises(ElectionError):
                services.cast_ballot(self.election, person, {self.president.pk: self.cand_p1.pk})
        self.assertFalse(Vote.objects.exists())

    def test_candidate_for_wrong_position_rejected(self):
        with self.assertRaises(ElectionError):
            services.cast_ballot(self.election, self.voter, {self.president.pk: self.cand_s1.pk})
        self.assertFalse(VoterRecord.objects.exists())

    def test_unapproved_candidate_rejected(self):
        pending = fixture_nomination(
            election=self.election, position=self.president,
            candidate=make_alumnus("Pending"), manifesto="x",
        )
        with self.assertRaises(ElectionError):
            services.cast_ballot(self.election, self.voter, {self.president.pk: pending.pk})

    def test_position_from_other_election_rejected(self):
        other = make_election(Phase.VOTING_OPEN, title="Other")
        other_pos = fixture_position(election=other, title="Treasurer")
        other_nom = approved_nomination(other, other_pos, make_alumnus())
        with self.assertRaises(ElectionError):
            services.cast_ballot(self.election, self.voter, {other_pos.pk: other_nom.pk})

    def test_double_voting_blocked(self):
        services.cast_ballot(self.election, self.voter, {self.president.pk: self.cand_p1.pk})
        with self.assertRaises(ElectionError):
            services.cast_ballot(self.election, self.voter, {self.president.pk: self.cand_p2.pk})
        self.assertEqual(VoterRecord.objects.count(), 1)
        self.assertEqual(Vote.objects.count(), 1)

    def test_double_voting_blocked_by_db_constraint_under_race(self):
        """Even if the pre-check is bypassed (concurrent request), the DB constraint wins."""
        services.cast_ballot(self.election, self.voter, {self.president.pk: self.cand_p1.pk})
        with mock.patch.object(services, "has_voted", return_value=False):
            with self.assertRaises(ElectionError):
                services.cast_ballot(self.election, self.voter, {self.president.pk: self.cand_p2.pk})
        self.assertEqual(VoterRecord.objects.count(), 1)
        self.assertEqual(Vote.objects.count(), 1)

    def test_receipt_email_has_no_choices(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.cast_ballot(self.election, self.voter, {self.president.pk: self.cand_p1.pk})
        self.assertEqual(len(mail.outbox), 1)
        receipt = mail.outbox[0]
        self.assertEqual(receipt.to, [self.voter.email_id])
        for name in ("Priya", "Pranav", "Sara"):
            self.assertNotIn(name, receipt.body)
            self.assertNotIn(name, receipt.subject)


class SecrecyTests(TestCase):
    def test_vote_model_has_no_link_to_voter_and_no_timestamp(self):
        for field in Vote._meta.get_fields():
            self.assertNotIsInstance(field, (models.DateTimeField, models.DateField), field.name)
            if field.is_relation:
                self.assertNotIn(field.related_model, (User, UserData), field.name)
        self.assertIsInstance(Vote._meta.pk, models.UUIDField)

    def test_vote_not_registered_in_admin(self):
        self.assertNotIn(Vote, admin.site._registry)


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #

class ResultsTests(TestCase):
    def setUp(self):
        self.election = make_election(Phase.VOTING_OPEN)
        self.president = fixture_position(election=self.election, title="President", order=1)
        self.secretary = fixture_position(election=self.election, title="Secretary", order=2)
        self.p1 = approved_nomination(self.election, self.president, make_alumnus("Priya"))
        self.p2 = approved_nomination(self.election, self.president, make_alumnus("Pranav"))
        self.s1 = approved_nomination(self.election, self.secretary, make_alumnus("Sara"))
        self.s2 = approved_nomination(self.election, self.secretary, make_alumnus("Sam"))
        # President: Priya 2, Pranav 1. Secretary: Sara 1, Sam 1 (tie).
        ballots = [
            {self.president.pk: self.p1.pk, self.secretary.pk: self.s1.pk},
            {self.president.pk: self.p1.pk, self.secretary.pk: self.s2.pk},
            {self.president.pk: self.p2.pk},
        ]
        for b in ballots:
            services.cast_ballot(self.election, make_alumnus(), b)

    def test_tally_hidden_until_closed(self):
        with self.assertRaises(ElectionError):
            services.tally(self.election)

    def test_winner_and_tie(self):
        set_phase(self.election, Phase.CLOSED)
        president, secretary = services.tally(self.election)
        self.assertEqual(president["total"], 3)
        self.assertFalse(president["is_tie"])
        top = president["candidates"][0]
        self.assertEqual((top["nomination"], top["votes"], top["is_winner"]), (self.p1, 2, True))
        self.assertFalse(president["candidates"][1]["is_winner"])

        self.assertTrue(secretary["is_tie"])
        self.assertTrue(all(c["is_winner"] for c in secretary["candidates"]))

    def test_publish_results_requires_closed_and_snapshots_turnout(self):
        with self.assertRaises(ElectionError):
            services.publish_results(self.election)
        set_phase(self.election, Phase.CLOSED)
        services.publish_results(self.election)
        self.election.refresh_from_db()
        self.assertTrue(self.election.results_published)
        snapshot = eligible_voters().count()
        self.assertEqual(self.election.eligible_voter_count, snapshot)

        # Later eligibility changes must not alter published turnout.
        make_alumnus()
        t = services.turnout(self.election)
        self.assertEqual(t, {
            "voted": 3, "eligible": snapshot, "percent": round(100 * 3 / snapshot, 1),
        })

        with self.assertRaises(ElectionError):
            services.publish_results(self.election)


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #

class ElectionViewTests(TestCase):
    def setUp(self):
        self.election = make_election(Phase.NOMINATIONS_OPEN)
        self.president = fixture_position(election=self.election, title="President", order=1)
        self.alice = make_alumnus("Alice")
        self.detail_url = reverse("elections:election_detail", args=[self.election.pk])

    def login(self, userdata):
        self.client.force_login(userdata.user)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("elections:election_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_unapproved_redirected_home(self):
        self.login(make_alumnus(approved=False))
        response = self.client.get(reverse("elections:election_list"))
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_list_groups_elections_and_hides_drafts(self):
        make_election(Phase.UPCOMING, title="Future Election")
        make_election(Phase.CLOSED, title="Past Election")
        make_election(Phase.VOTING_OPEN, published=False, title="Secret Draft")
        self.login(self.alice)
        response = self.client.get(reverse("elections:election_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([e.title for e in response.context["active"]], [self.election.title])
        self.assertEqual([e.title for e in response.context["upcoming"]], ["Future Election"])
        self.assertEqual([e.title for e in response.context["past"]], ["Past Election"])
        self.assertNotContains(response, "Secret Draft")

    def test_draft_detail_404(self):
        draft = make_election(Phase.VOTING_OPEN, published=False)
        self.login(self.alice)
        response = self.client.get(reverse("elections:election_detail", args=[draft.pk]))
        self.assertEqual(response.status_code, 404)

    def test_ineligible_sees_banner_and_no_actions(self):
        self.login(make_alumnus(eligible=False))
        response = self.client.get(self.detail_url)
        self.assertContains(response, "You are not eligible to vote in elections")
        self.assertNotContains(response, "Nominate yourself")
        response = self.client.get(reverse("elections:nominate", args=[self.election.pk]))
        self.assertRedirects(response, self.detail_url, fetch_redirect_response=False)

    def test_full_happy_path(self):
        # 1. Nominate
        self.login(self.alice)
        self.assertContains(self.client.get("/"), 'href="/elections/"')
        response = self.client.get(self.detail_url)
        self.assertContains(response, "Nominate yourself")
        response = self.client.get(reverse("elections:nominate", args=[self.election.pk]))
        self.assertContains(response, "Submit nomination")
        self.assertContains(response, "President")
        response = self.client.post(
            reverse("elections:nominate", args=[self.election.pk]),
            {"position": str(self.president.pk), "manifesto": "Build a stronger alumni network"},
        )
        self.assertRedirects(response, self.detail_url, fetch_redirect_response=False)
        nomination = Nomination.objects.get(candidate=self.alice)
        self.assertEqual(nomination.status, Nomination.Status.PENDING)

        # 2. Admin approves, voting opens
        services.review_nomination(nomination, approve=True)
        set_phase(self.election, Phase.VOTING_OPEN)

        # 3. Voter reviews, then confirms
        voter = make_alumnus("Voter")
        self.login(voter)
        ballot_url = reverse("elections:ballot", args=[self.election.pk])
        response = self.client.get(ballot_url)
        self.assertContains(response, "Alice")
        field = f"position_{self.president.pk}"
        response = self.client.post(ballot_url, {"action": "review", field: str(nomination.pk)})
        self.assertContains(response, "Submit my vote")
        self.assertFalse(VoterRecord.objects.exists())

        # "Change choices" returns to the pre-filled ballot
        response = self.client.post(ballot_url, {"action": "edit", field: str(nomination.pk)})
        self.assertContains(response, "Review my ballot")
        self.assertContains(response, f'value="{nomination.pk}" checked')

        response = self.client.post(ballot_url, {"action": "confirm", field: str(nomination.pk)})
        self.assertRedirects(response, self.detail_url, fetch_redirect_response=False)
        self.assertTrue(VoterRecord.objects.filter(voter=voter).exists())
        self.assertEqual(Vote.objects.filter(nomination=nomination).count(), 1)

        # 4. Cannot vote again
        response = self.client.get(ballot_url)
        self.assertRedirects(response, self.detail_url, fetch_redirect_response=False)
        self.assertContains(self.client.get(self.detail_url), "You have voted")

        # 5. Results hidden until published
        set_phase(self.election, Phase.CLOSED)
        results_url = reverse("elections:results", args=[self.election.pk])
        self.assertRedirects(self.client.get(results_url), self.detail_url, fetch_redirect_response=False)
        services.publish_results(self.election)
        response = self.client.get(results_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")
        self.assertContains(response, "Winner")

    def test_ballot_with_tampered_value_rejected(self):
        approved_nomination(self.election, self.president, make_alumnus("Cand"))
        set_phase(self.election, Phase.VOTING_OPEN)
        self.login(self.alice)
        response = self.client.post(
            reverse("elections:ballot", args=[self.election.pk]),
            {"action": "confirm", f"position_{self.president.pk}": "not-a-number"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(VoterRecord.objects.exists())

    def test_withdraw_view(self):
        nom = services.submit_nomination(self.election, self.president, self.alice, "x")
        self.login(self.alice)
        withdraw_url = reverse("elections:withdraw", args=[self.election.pk])
        self.assertEqual(self.client.get(withdraw_url).status_code, 405)
        self.client.post(withdraw_url)
        nom.refresh_from_db()
        self.assertEqual(nom.status, Nomination.Status.WITHDRAWN)


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #

class AdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser("admin", "admin@example.com", "pw")
        self.client.force_login(self.admin_user)
        self.election = make_election(Phase.VOTING_OPEN)
        self.position = fixture_position(election=self.election, title="President")
        self.candidate = approved_nomination(self.election, self.position, make_alumnus("Priya"))
        self.changelist = reverse("admin:elections_election_changelist")

    def run_action(self, action, url=None, pks=None):
        return self.client.post(url or self.changelist, {
            "action": action,
            "_selected_action": [str(pk) for pk in (pks or [self.election.pk])],
        }, follow=True)

    def test_tally_hidden_in_admin_until_closed(self):
        services.cast_ballot(self.election, make_alumnus(), {self.position.pk: self.candidate.pk})
        change_url = reverse("admin:elections_election_change", args=[self.election.pk])
        response = self.client.get(change_url)
        self.assertContains(response, "Tallies are hidden until voting closes.")
        set_phase(self.election, Phase.CLOSED)
        response = self.client.get(change_url)
        self.assertNotContains(response, "Tallies are hidden")
        self.assertContains(response, "WINNER")

    def test_publish_results_action(self):
        self.run_action("publish_results")
        self.election.refresh_from_db()
        self.assertFalse(self.election.results_published)  # still voting
        set_phase(self.election, Phase.CLOSED)
        self.run_action("publish_results")
        self.election.refresh_from_db()
        self.assertTrue(self.election.results_published)

    def test_email_voters_voting_open_batches_and_only_once(self):
        voters = [make_alumnus() for _ in range(55)]
        make_alumnus(eligible=False)
        make_alumnus(approved=False)
        self.run_action("email_voters_voting_open")
        queued = ElectionMail.objects.filter(election=self.election, priority=30)
        self.assertEqual(queued.count(), eligible_voters().count())
        self.assertEqual(set(queued.values_list("recipient", flat=True)),
                         set(eligible_voters().values_list("user__email", flat=True)))
        self.run_action("email_voters_voting_open")
        self.assertEqual(queued.count(), eligible_voters().count())

    def test_email_voters_refused_outside_voting(self):
        set_phase(self.election, Phase.NOMINATIONS_OPEN)
        mail.outbox.clear()
        self.run_action("email_voters_voting_open")
        self.assertEqual(len(mail.outbox), 0)

    def test_nomination_approve_action(self):
        set_phase(self.election, Phase.NOMINATIONS_CLOSED)
        pending = fixture_nomination(
            election=self.election, position=self.position,
            candidate=make_alumnus("Pending"), manifesto="x",
        )
        self.run_action(
            "approve_nominations", url=reverse("admin:elections_nomination_changelist"),
            pks=[pending.pk],
        )
        pending.refresh_from_db()
        self.assertEqual(pending.status, Nomination.Status.APPROVED)

    def test_mark_eligible_action_skips_unapproved(self):
        approved = make_alumnus(eligible=False)
        unapproved = make_alumnus(approved=False, eligible=False)
        self.run_action(
            "mark_eligible_to_vote", url=reverse("admin:web_userdata_changelist"),
            pks=[approved.pk, unapproved.pk],
        )
        approved.refresh_from_db()
        unapproved.refresh_from_db()
        self.assertTrue(approved.is_eligible_to_vote)
        self.assertFalse(unapproved.is_eligible_to_vote)

        self.run_action(
            "revoke_voting_eligibility", url=reverse("admin:web_userdata_changelist"),
            pks=[approved.pk],
        )
        approved.refresh_from_db()
        self.assertFalse(approved.is_eligible_to_vote)

    def test_turnout_csv_contains_names_not_choices(self):
        voter = make_alumnus("Visible Voter")
        services.cast_ballot(self.election, voter, {self.position.pk: self.candidate.pk})
        response = self.run_action("export_turnout_csv")
        body = response.content.decode()
        self.assertIn("Visible Voter", body)
        self.assertNotIn("Priya", body)

    def test_announce_voting_open_raises_if_no_recipients(self):
        UserData.objects.all().update(is_eligible_to_vote=False)
        with self.assertRaises(ElectionError) as ctx:
            services.announce_voting_open(self.election)
        self.assertIn("No eligible voters", str(ctx.exception))
        self.assertIsNone(self.election.voting_open_email_sent_at)

    def test_email_voting_open_uses_localtime(self):
        make_alumnus()
        mail.outbox.clear()
        services.announce_voting_open(self.election)
        queued = ElectionMail.objects.filter(election=self.election, priority=30).first()
        body = queued.body
        expected_time = f"{timezone.localtime(self.election.voting_end):%d %b %Y, %I:%M %p}"
        self.assertIn(expected_time, body)

    def test_staff_preview_mode(self):
        # Staff user without UserData can view election list, detail, and results in preview mode
        staff = User.objects.create_user("staff_member", "staff@example.com", "pw", is_staff=True)
        self.client.force_login(staff)

        list_resp = self.client.get(reverse("elections:election_list"))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, "Administrator Preview Mode")

        detail_resp = self.client.get(reverse("elections:election_detail", args=[self.election.pk]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "Administrator Preview Mode")
        self.assertNotContains(detail_resp, "Cast your vote")

        # Staff cannot nominate or vote
        nom_resp = self.client.get(reverse("elections:nominate", args=[self.election.pk]))
        self.assertRedirects(nom_resp, reverse("elections:election_detail", args=[self.election.pk]), fetch_redirect_response=False)

        vote_resp = self.client.get(reverse("elections:ballot", args=[self.election.pk]))
        self.assertRedirects(vote_resp, reverse("elections:election_detail", args=[self.election.pk]), fetch_redirect_response=False)

    def test_cannot_modify_election_dates_after_votes_exist(self):
        voter = make_alumnus("Voter")
        services.cast_ballot(self.election, voter, {self.position.pk: self.candidate.pk})

        self.election.voting_start = timezone.now() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.election.clean()

    def test_check_can_cast_rejects_empty_election(self):
        empty_election = make_election(Phase.VOTING_OPEN, title="Empty")
        voter = make_alumnus("Voter2")
        with self.assertRaises(ElectionError) as ctx:
            services.check_can_cast(empty_election, voter)
        self.assertIn("no positions", str(ctx.exception))

        pos = fixture_position(election=empty_election, title="Chair")
        with self.assertRaises(ElectionError) as ctx:
            services.check_can_cast(empty_election, voter)
        self.assertIn("no approved candidates", str(ctx.exception))

    def test_position_guards_when_voting_started(self):
        # Cannot add new positions once voting is open
        new_pos = Position(election=self.election, title="Treasurer")
        with self.assertRaises(ValidationError) as ctx:
            new_pos.clean()
        self.assertIn("Cannot add new positions", str(ctx.exception))

        # Cannot rename existing positions once voting is open
        self.position.title = "Executive President"
        with self.assertRaises(ValidationError):
            self.position.clean()

        # Cannot delete positions once voting is open
        with self.assertRaises(ValidationError):
            self.position.delete()

    def test_nomination_guards_when_voting_started(self):
        # Cannot approve or reject a nomination once voting has started
        nom = fixture_nomination(
            election=self.election, position=self.position, candidate=make_alumnus("Late"),
            manifesto="Hi", status=Nomination.Status.PENDING,
        )
        nom.status = Nomination.Status.APPROVED
        with self.assertRaises(ValidationError):
            nom.clean()

        # Cannot delete nomination once voting has started
        with self.assertRaises(ValidationError):
            nom.delete()

    def test_announce_voting_open_smtp_failure_handling(self):
        make_alumnus()
        services.announce_voting_open(self.election)
        with mock.patch("elections.notifications.get_connection") as mock_conn:
            mock_conn.return_value.open.side_effect = OSError("private provider detail")
            self.assertEqual(notifications.deliver_pending(), 0)
        self.assertTrue(ElectionMail.objects.filter(status=ElectionMail.Status.PENDING).exists())
        self.election.refresh_from_db()
        self.assertIsNotNone(self.election.voting_open_email_sent_at)

    def test_reset_voting_open_announcement_action_removed(self):
        self.assertNotIn("reset_voting_open_announcement",
                         admin.site._registry[Election].get_actions(
                             type("Request", (), {"user": self.admin_user, "GET": {}})()))

    def test_turnout_caps_at_100_when_eligible_reduced(self):
        voter = make_alumnus("Active Voter")
        services.cast_ballot(self.election, voter, {self.position.pk: self.candidate.pk})
        # Set snapshot of eligible to 0 or less than voted
        self.election.eligible_voter_count = 0
        t = services.turnout(self.election)
        self.assertEqual(t["voted"], 1)
        self.assertEqual(t["eligible"], 1)
        self.assertEqual(t["percent"], 100.0)

