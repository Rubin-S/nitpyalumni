"""
Business rules for elections. Views and admin actions call these functions;
each raises ElectionError with a user-facing message when a rule is violated.
"""
import secrets
from functools import wraps

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from elections import notifications
from elections.eligibility import can_nominate, can_vote, eligible_voters
from elections.models import Election, Nomination, Vote, VoterRecord
from web.models import UserData

Phase = Election.Phase


class ElectionError(Exception):
    pass


def atomic_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            with transaction.atomic():
                return function(*args, **kwargs)
        except ValidationError as exc:
            raise ElectionError(" ".join(exc.messages)) from exc
    return wrapped


def _lock_election(election):
    try:
        return Election.objects.select_for_update().get(pk=election.pk)
    except Election.DoesNotExist:
        raise ElectionError("This election is no longer available.")


def _lock_member(userdata):
    if userdata is None:
        raise ElectionError("An eligible alumni account is required.")
    try:
        get_user_model().objects.select_for_update().get(pk=userdata.user_id)
        return UserData.objects.select_for_update().select_related("user").get(pk=userdata.pk)
    except (get_user_model().DoesNotExist, UserData.DoesNotExist):
        raise ElectionError("This alumni account is no longer available.")



def active_nomination(election, userdata):
    return Nomination.objects.filter(
        election=election, candidate=userdata, status__in=Nomination.ACTIVE_STATUSES
    ).select_related("position").first()


@atomic_mutation
def submit_nomination(election, position, userdata, manifesto):
    election = _lock_election(election)
    userdata = _lock_member(userdata)
    if election.phase != Phase.NOMINATIONS_OPEN:
        raise ElectionError("Nominations are not open for this election.")
    if not can_nominate(userdata):
        raise ElectionError("You are not eligible to stand in elections.")
    if position is None or position.election_id != election.pk:
        raise ElectionError("Please choose a valid position.")
    manifesto = (manifesto or "").strip()
    if not manifesto:
        raise ElectionError("Please write a short manifesto.")
    if len(manifesto) > Nomination.MANIFESTO_MAX_LENGTH:
        raise ElectionError(
            f"Manifesto must be at most {Nomination.MANIFESTO_MAX_LENGTH} characters."
        )
    if active_nomination(election, userdata):
        raise ElectionError("You already have an active nomination in this election.")
    try:
        with transaction.atomic():
            return Nomination.objects.create(
                election=election, position=position, candidate=userdata, manifesto=manifesto
            )
    except IntegrityError:
        # Concurrent duplicate submission hit the DB constraint.
        raise ElectionError("You already have an active nomination in this election.")


@atomic_mutation
def withdraw_nomination(nomination, userdata):
    election = _lock_election(nomination.election)
    nomination = Nomination.objects.select_for_update().get(pk=nomination.pk)
    nomination.election = election
    userdata = _lock_member(userdata)
    if nomination.candidate_id != userdata.pk:
        raise ElectionError("You can only withdraw your own nomination.")
    if nomination.status not in Nomination.ACTIVE_STATUSES:
        raise ElectionError("This nomination is not active.")
    if nomination.election.phase not in (Phase.NOMINATIONS_OPEN, Phase.NOMINATIONS_CLOSED):
        raise ElectionError("Nominations can no longer be withdrawn once voting has started.")
    nomination.status = Nomination.Status.WITHDRAWN
    nomination.save(update_fields=["status"])
    return nomination


@atomic_mutation
def review_nomination(nomination, approve):
    """Admin approve/reject. Only allowed before voting starts."""
    election = _lock_election(nomination.election)
    nomination = Nomination.objects.select_for_update().get(pk=nomination.pk)
    nomination.election = election
    if nomination.election.phase not in (Phase.NOMINATIONS_OPEN, Phase.NOMINATIONS_CLOSED):
        raise ElectionError("Nominations can only be reviewed before voting starts.")
    if nomination.status == Nomination.Status.WITHDRAWN:
        raise ElectionError("Withdrawn nominations cannot be reviewed.")
    target = Nomination.Status.APPROVED if approve else Nomination.Status.REJECTED
    if approve and not can_nominate(_lock_member(nomination.candidate)):
        raise ElectionError("This candidate no longer meets election eligibility requirements.")
    if nomination.status == target:
        return nomination
    nomination.status = target
    try:
        with transaction.atomic():
            nomination.save()
    except IntegrityError:
        raise ElectionError("This candidate already has another active nomination.")
    return nomination



def ballot_positions(election):
    """Positions of the election with their approved candidates prefetched."""
    from django.db.models import Prefetch

    return list(
        election.positions.prefetch_related(
            Prefetch(
                "nominations",
                queryset=Nomination.objects.filter(status=Nomination.Status.APPROVED)
                .select_related("candidate")
                .order_by("candidate_snapshot__name", "pk"),
                to_attr="approved_nominations",
            )
        )
    )


def has_voted(election, userdata):
    return VoterRecord.objects.filter(election=election, voter=userdata).exists()


def resolve_selections(election, selections):
    """
    Validate {position_id: nomination_id} against the election.
    Returns a list of (Position, Nomination) pairs. Skipped positions are omitted.
    """
    selections = {pos: nom for pos, nom in selections.items() if nom}
    if not selections:
        raise ElectionError("Please select a candidate for at least one position.")

    positions = {p.pk: p for p in election.positions.all()}
    nominations = {
        n.pk: n
        for n in Nomination.objects.filter(
            pk__in=selections.values(), election=election, status=Nomination.Status.APPROVED
        ).select_related("candidate")
    }
    resolved = []
    for pos_id, nom_id in selections.items():
        position = positions.get(pos_id)
        nomination = nominations.get(nom_id)
        if position is None:
            raise ElectionError("Your ballot contains an invalid position.")
        if nomination is None or nomination.position_id != pos_id:
            raise ElectionError(f"Invalid candidate selected for {position.title}.")
        resolved.append((position, nomination))
    resolved.sort(key=lambda pair: (pair[0].order, pair[0].pk))
    return resolved


def check_can_cast(election, userdata):
    if election.phase != Phase.VOTING_OPEN:
        raise ElectionError("Voting is not open for this election.")
    if not can_vote(userdata):
        raise ElectionError("You are not eligible to vote in elections.")
    if has_voted(election, userdata):
        raise ElectionError("You have already voted in this election.")
    if not election.positions.exists():
        raise ElectionError("This election has no positions to vote for.")
    if not Nomination.objects.filter(election=election, status=Nomination.Status.APPROVED).exists():
        raise ElectionError("This election has no approved candidates to vote for.")


@atomic_mutation
def cast_ballot(election, userdata, selections):
    """
    Record a secret ballot. The VoterRecord and the anonymous Vote rows are
    written in one transaction; the unique (election, voter) constraint
    makes double voting impossible even under concurrent requests.
    """
    election = _lock_election(election)
    userdata = _lock_member(userdata)
    check_can_cast(election, userdata)
    resolved = resolve_selections(election, selections)

    votes = [
        Vote(election=election, position=position, nomination=nomination)
        for position, nomination in resolved
    ]
    # Shuffle so insertion order does not mirror ballot order.
    secrets.SystemRandom().shuffle(votes)

    # Recheck the clock after validation, immediately before the ballot write.
    if election.phase != Phase.VOTING_OPEN:
        raise ElectionError("Voting has closed. Your ballot was not recorded.")
    try:
        with transaction.atomic():
            VoterRecord.objects.create(election=election, voter=userdata)
            Vote.objects.bulk_create(votes)
    except IntegrityError:
        raise ElectionError("You have already voted in this election.")

    notifications.send_vote_receipt(election, userdata)



def tally(election):
    """
    Per-position results. Only available once voting has closed.
    Returns a list of dicts:
        {"position", "candidates": [{"nomination", "votes", "is_winner"}], "total", "is_tie"}
    """
    if election.phase != Phase.CLOSED:
        raise ElectionError("Results are hidden until voting closes.")

    counts = dict(
        Vote.objects.filter(election=election)
        .values_list("nomination")
        .annotate(n=Count("id"))
    )
    results = []
    for position in election.positions.all():
        nominations = (
            Nomination.objects.filter(position=position)
            .filter(Q(status=Nomination.Status.APPROVED) | Q(pk__in=list(counts)))
            .select_related("candidate")
        )
        candidates = sorted(
            ({"nomination": n, "votes": counts.get(n.pk, 0)} for n in nominations),
            key=lambda c: (-c["votes"], c["nomination"].candidate_name),
        )
        top = candidates[0]["votes"] if candidates else 0
        winners = [c for c in candidates if top > 0 and c["votes"] == top]
        for c in candidates:
            c["is_winner"] = c in winners
        results.append({
            "position": position,
            "candidates": candidates,
            "total": sum(c["votes"] for c in candidates),
            "is_tie": len(winners) > 1,
        })
    return results


def turnout(election):
    voted = election.voter_records.count()
    eligible = election.eligible_voter_count
    if eligible is None:
        eligible = eligible_voters().count()
    eligible = max(eligible, voted)
    percent = min(100.0, round(100 * voted / eligible, 1)) if eligible else 0
    return {"voted": voted, "eligible": eligible, "percent": percent}


@atomic_mutation
def publish_results(election):
    election = _lock_election(election)
    if election.phase != Phase.CLOSED:
        raise ElectionError("Results can only be published after voting closes.")
    if election.results_published:
        raise ElectionError("Results are already published.")
    voted = election.voter_records.count()
    count = eligible_voters().count()
    election.eligible_voter_count = max(count, voted)
    election.results_published = True
    election.save(update_fields=["eligible_voter_count", "results_published"])
    return election



@atomic_mutation
def announce_voting_open(election):
    """Queue one announcement per canonical recipient; safe to resume sending."""
    election = _lock_election(election)
    if election.phase != Phase.VOTING_OPEN:
        raise ElectionError("The announcement can only be sent while voting is open.")
    if election.voting_open_email_sent_at:
        raise ElectionError("The voting-open announcement was already sent.")
    recipients = sorted(
        {e.strip().lower() for e in eligible_voters().values_list("user__email", flat=True) if e and e.strip()}
    )
    if not recipients:
        raise ElectionError("No eligible voters with a valid email address were found.")
    queued = notifications.email_voting_open(election, recipients)
    election.voting_open_email_sent_at = timezone.now()
    election.save(update_fields=["voting_open_email_sent_at"])
    return len(recipients), queued
