"""Election eligibility for individual checks and recipient queries."""
from web.models import UserData


def can_vote(userdata) -> bool:
    """Return True if this alumni profile may vote in elections."""
    return bool(
        userdata is not None
        and userdata.user.is_active
        and userdata.account_is_approved
        and userdata.is_eligible_to_vote
    )


def can_nominate(userdata) -> bool:
    """Candidates must meet the same bar as voters."""
    return can_vote(userdata)


def eligible_voters():
    """Queryset of every alumni profile for which ``can_vote`` is True."""
    return UserData.objects.filter(
        account_is_approved=True, is_eligible_to_vote=True, user__is_active=True,
    )
