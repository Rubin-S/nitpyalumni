"""
Email notifications for elections.

All sends use fail_silently=True, matching the rest of the project, so an SMTP
problem never blocks a nomination or a vote.
"""
import os

from django.conf import settings
from django.core.mail import EmailMessage, get_connection, send_mail
from django.utils import timezone

from web.models import send_creation_email

SITE_URL = os.environ.get("SITE_URL", "https://nitpyalumni.com").rstrip("/")
VOTING_OPEN_BATCH_SIZE = 50


def election_url(election):
    return f"{SITE_URL}/elections/{election.pk}/"


def notify_staff_new_nomination(nomination):
    send_creation_email(
        f"New election nomination by: {nomination.candidate.name}",
        f"{nomination.candidate.name} ({nomination.candidate.roll_no}) has nominated themselves "
        f"for '{nomination.position.title}' in '{nomination.election.title}'. "
        f"Kindly approve or reject it in the admin panel.",
    )


def notify_candidate_status(nomination):
    approved = nomination.status == nomination.Status.APPROVED
    verdict = "approved" if approved else "rejected"
    lines = [
        f"Hi {nomination.candidate.name},",
        "",
        f"Your nomination for '{nomination.position.title}' in '{nomination.election.title}' "
        f"has been {verdict}.",
    ]
    if nomination.review_note:
        lines += ["", f"Note from the alumni committee: {nomination.review_note}"]
    lines += ["", f"Election details: {election_url(nomination.election)}"]
    send_mail(
        subject=f"Your election nomination has been {verdict}",
        message="\n".join(lines),
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[nomination.candidate.email_id],
        fail_silently=True,
    )


def send_vote_receipt(election, userdata):
    """Confirms THAT the member voted. Never includes the choices."""
    send_mail(
        subject=f"Your vote in '{election.title}' has been recorded",
        message=(
            f"Hi {userdata.name},\n\n"
            f"This confirms that your ballot in '{election.title}' has been recorded. "
            f"Your choices are secret and are not stored against your name.\n\n"
            f"If you did not cast this vote, contact the alumni committee immediately."
        ),
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[userdata.email_id],
        fail_silently=True,
    )


def email_voting_open(election, recipients):
    """
    Announce that voting is open, using one SMTP connection and BCC batches,
    so N voters cost ceil(N / VOTING_OPEN_BATCH_SIZE) messages.
    Returns the number of messages sent.
    """
    local_end = timezone.localtime(election.voting_end)
    subject = f"Voting is now open: {election.title}"
    body = (
        f"Dear alumni,\n\n"
        f"Voting is now open for '{election.title}'.\n"
        f"Voting closes on {local_end:%d %b %Y, %I:%M %p} ({settings.TIME_ZONE}).\n\n"
        f"Cast your vote: {election_url(election)}\n\n"
        f"- NITPY Alumni Committee"
    )
    connection = get_connection(fail_silently=False)
    messages = [
        EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.EMAIL_HOST_USER,
            to=[settings.EMAIL_HOST_USER],
            bcc=recipients[i:i + VOTING_OPEN_BATCH_SIZE],
            connection=connection,
        )
        for i in range(0, len(recipients), VOTING_OPEN_BATCH_SIZE)
    ]
    sent_count = 0
    if messages:
        sent_count = connection.send_messages(messages)
    return sent_count
