from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from elections import services
from elections.decorators import approved_alumni_required
from elections.eligibility import can_nominate, can_vote
from elections.models import Election, Nomination, VoterRecord
from elections.services import ElectionError

Phase = Election.Phase
ACTIVE_PHASES = (Phase.NOMINATIONS_OPEN, Phase.NOMINATIONS_CLOSED, Phase.VOTING_OPEN)


def _get_published_election(election_id):
    return get_object_or_404(Election, pk=election_id, is_published=True)


def _detail_redirect(election):
    return redirect("elections:election_detail", election_id=election.pk)


@login_required
@approved_alumni_required
def election_list(request):
    elections = list(Election.objects.filter(is_published=True))
    voted_ids = set()
    if request.userdata:
        voted_ids = set(
            VoterRecord.objects.filter(voter=request.userdata).values_list("election_id", flat=True)
        )
    for election in elections:
        election.user_has_voted = election.pk in voted_ids

    return render(request, "elections/election_list.html", {
        "active": [e for e in elections if e.phase in ACTIVE_PHASES],
        "upcoming": [e for e in elections if e.phase == Phase.UPCOMING],
        "past": [e for e in elections if e.phase == Phase.CLOSED],
        "is_eligible": can_vote(request.userdata),
        "is_staff_preview": request.user.is_staff and not request.userdata,
    })


@login_required
@approved_alumni_required
def election_detail(request, election_id):
    election = _get_published_election(election_id)
    userdata = request.userdata
    phase = election.phase
    eligible = can_vote(userdata)
    my_nomination = services.active_nomination(election, userdata) if userdata else None
    voted = services.has_voted(election, userdata) if userdata else False
    positions = services.ballot_positions(election)
    has_approved_candidates = any(p.approved_nominations for p in positions)

    return render(request, "elections/election_detail.html", {
        "election": election,
        "phase": phase,
        "Phase": Phase,
        "positions": positions,
        "is_eligible": eligible,
        "my_nomination": my_nomination,
        "has_voted": voted,
        "can_nominate_now": (
            can_nominate(userdata) and phase == Phase.NOMINATIONS_OPEN
            and my_nomination is None and bool(positions)
        ),
        "can_withdraw_now": (
            my_nomination is not None
            and phase in (Phase.NOMINATIONS_OPEN, Phase.NOMINATIONS_CLOSED)
        ),
        "can_vote_now": eligible and phase == Phase.VOTING_OPEN and not voted and has_approved_candidates,
        "is_staff_preview": request.user.is_staff and not userdata,
    })


@login_required
@approved_alumni_required
def nominate(request, election_id):
    election = _get_published_election(election_id)
    userdata = request.userdata
    if not userdata:
        messages.error(request, "Staff accounts cannot nominate in elections. Please log in with an alumni account.")
        return _detail_redirect(election)

    if election.phase != Phase.NOMINATIONS_OPEN:
        messages.error(request, "Nominations are not open for this election.")
        return _detail_redirect(election)
    if not can_nominate(userdata):
        messages.error(request, "You are not eligible to stand in elections.")
        return _detail_redirect(election)
    if services.active_nomination(election, userdata):
        messages.info(request, "You already have an active nomination in this election.")
        return _detail_redirect(election)

    positions = list(election.positions.all())
    if not positions:
        messages.error(request, "This election does not have any positions open for nomination.")
        return _detail_redirect(election)

    form = {"position": "", "manifesto": ""}

    if request.method == "POST":
        form["position"] = request.POST.get("position", "")
        form["manifesto"] = request.POST.get("manifesto", "")
        position = next((p for p in positions if str(p.pk) == form["position"]), None)
        try:
            services.submit_nomination(election, position, userdata, form["manifesto"])
        except ElectionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                "Your nomination has been submitted and is awaiting approval by the alumni committee.",
            )
            return _detail_redirect(election)

    return render(request, "elections/nominate.html", {
        "election": election,
        "positions": positions,
        "form": form,
        "max_length": Nomination.MANIFESTO_MAX_LENGTH,
    })


@login_required
@approved_alumni_required
@require_POST
def withdraw(request, election_id):
    election = _get_published_election(election_id)
    nomination = services.active_nomination(election, request.userdata)
    if nomination is None:
        messages.error(request, "You have no active nomination in this election.")
        return _detail_redirect(election)
    try:
        services.withdraw_nomination(nomination, request.userdata)
    except ElectionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Your nomination has been withdrawn.")
    return _detail_redirect(election)


def _parse_selections(post, positions):
    """Read {position_id: nomination_id} from POST; blank/'skip' means skipped."""
    selections = {}
    for position in positions:
        raw = (post.get(f"position_{position.pk}") or "").strip()
        if raw in ("", "skip"):
            continue
        try:
            selections[position.pk] = int(raw)
        except ValueError:
            raise ElectionError("Your ballot contains an invalid selection.")
    return selections


@login_required
@approved_alumni_required
def ballot(request, election_id):
    election = _get_published_election(election_id)
    userdata = request.userdata
    if not userdata:
        messages.error(request, "Staff accounts cannot vote in elections. Please log in with an alumni account.")
        return _detail_redirect(election)

    try:
        services.check_can_cast(election, userdata)
    except ElectionError as exc:
        messages.error(request, str(exc))
        return _detail_redirect(election)

    positions = services.ballot_positions(election)
    selections = {}

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            selections = _parse_selections(request.POST, positions)
            if action == "confirm":
                services.cast_ballot(election, userdata, selections)
                messages.success(
                    request, "Your vote has been recorded. Thank you for voting!"
                )
                return _detail_redirect(election)
            if action != "edit":
                # action == "review" (default): show the confirmation page.
                chosen = dict(
                    (pos.pk, nom)
                    for pos, nom in services.resolve_selections(election, selections)
                )
                return render(request, "elections/ballot_confirm.html", {
                    "election": election,
                    "rows": [{"position": p, "nomination": chosen.get(p.pk)} for p in positions],
                })
        except ElectionError as exc:
            messages.error(request, str(exc))
            if services.has_voted(election, userdata):
                return _detail_redirect(election)

    return render(request, "elections/ballot.html", {
        "election": election,
        "rows": [
            {"position": p, "candidates": p.approved_nominations, "selected": selections.get(p.pk)}
            for p in positions
        ],
    })


@login_required
@approved_alumni_required
def results(request, election_id):
    election = _get_published_election(election_id)
    if not election.results_published:
        messages.info(request, "Results for this election have not been published yet.")
        return _detail_redirect(election)
    try:
        tally_results = services.tally(election)
    except ElectionError as exc:
        messages.error(request, str(exc))
        return _detail_redirect(election)
    return render(request, "elections/results.html", {
        "election": election,
        "results": tally_results,
        "turnout": services.turnout(election),
    })
