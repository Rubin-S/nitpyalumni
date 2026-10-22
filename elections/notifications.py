"""Durable mail without ballot choices. SMTP runs only after database commit."""
import hashlib
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage, get_connection
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from web import throttle

logger = logging.getLogger(__name__)


def election_url(election):
    return f"{settings.PASSWORD_RESET_ORIGIN}/elections/{election.pk}/"


def queue(election, event, recipient, subject, body, priority=20):
    from elections.models import ElectionMail
    recipient = (recipient or "").strip().lower()
    try:
        validate_email(recipient)
    except ValidationError:
        logger.error("Election notification has no valid canonical recipient; administrator review required.")
        return 0
    _, created = ElectionMail.objects.get_or_create(
        event_key=hashlib.sha256(f"{event}:{recipient}".encode()).hexdigest(),
        defaults={"election": election, "recipient": recipient,
                  "subject": " ".join(subject.splitlines())[:255], "body": body, "priority": priority},
    )
    return int(created)


def _deliver_after_commit():
    transaction.on_commit(lambda: deliver_pending(limit=1), robust=True)


def notify_staff_new_nomination(nomination):
    from web.models import recipient_list
    for recipient in set(recipient_list):
        queue(nomination.election, f"nomination-created:{nomination.pk}", recipient,
              f"New election nomination by: {nomination.candidate_name}",
              f"{nomination.candidate_name} ({nomination.candidate_roll_no}) has nominated themselves "
              f"for '{nomination.position.title}' in '{nomination.election.title}'. "
              "Review the nomination in the admin panel.")
    _deliver_after_commit()


def notify_candidate_status(nomination):
    verdict = "approved" if nomination.status == nomination.Status.APPROVED else "rejected"
    body = (f"Hi {nomination.candidate_name},\n\nYour nomination for '{nomination.position.title}' "
            f"in '{nomination.election.title}' has been {verdict}.\n")
    if nomination.review_note:
        body += f"\nNote from the alumni committee: {nomination.review_note}\n"
    body += f"\nElection details: {election_url(nomination.election)}"
    queue(nomination.election, f"nomination-review:{nomination.pk}:{nomination.reviewed_at.isoformat()}",
          nomination.candidate.user.email, f"Your election nomination has been {verdict}", body)
    _deliver_after_commit()


def send_vote_receipt(election, userdata):
    queue(election, f"vote-receipt:{election.pk}:{userdata.pk}", userdata.user.email,
          f"Your vote in '{election.title}' has been recorded",
          f"Hi {userdata.name},\n\nThis confirms that your ballot in '{election.title}' has been recorded. "
          "Your choices are not included in this email or stored against your name in the portal.\n\n"
          "If you did not cast this vote, contact the alumni committee immediately.", priority=10)
    _deliver_after_commit()


def email_voting_open(election, recipients):
    end = timezone.localtime(election.voting_end)
    body = (f"Dear alumni,\n\nVoting is now open for '{election.title}'.\n"
            f"Voting closes on {end:%d %b %Y, %I:%M %p} ({settings.TIME_ZONE}).\n\n"
            f"Cast your vote: {election_url(election)}\n\nNITPY Alumni Committee")
    count = sum(queue(election, f"voting-open:{election.pk}", recipient,
                      f"Voting is now open: {election.title}", body, priority=30)
                for recipient in recipients)
    _deliver_after_commit()
    return count


def deliver_pending(limit=20, election_ids=None):
    """Bounded, shared UTC-day budget; uncertain sends require human review."""
    from elections.models import ElectionMail
    sent = 0
    daily_limit = max(0, settings.ELECTION_EMAIL_DAILY_LIMIT)
    day = timezone.now().strftime("%Y-%m-%d")
    connection = None
    try:
        if daily_limit == 0:
            return 0
        ElectionMail.objects.filter(status=ElectionMail.Status.PENDING, priority=30,
                                    election__voting_end__lte=timezone.now()).update(status=ElectionMail.Status.EXPIRED)
        if not ElectionMail.objects.filter(status=ElectionMail.Status.PENDING).exists():
            return 0
        if throttle.is_limited("election-mail-day", day, daily_limit, 86400):
            return 0
        connection = get_connection(fail_silently=False)
        connection.open()
        for _ in range(min(max(0, limit), daily_limit)):
            with transaction.atomic():
                pending = ElectionMail.objects.filter(
                    status=ElectionMail.Status.PENDING,
                ).exclude(priority=30, election__voting_end__lte=timezone.now())
                if election_ids is not None:
                    pending = pending.filter(election_id__in=election_ids)
                mail = pending.select_for_update(skip_locked=True, of=("self",)).first()
                if mail is None:
                    break
                if not throttle.consume("election-mail-day", day, daily_limit, 86400):
                    break
                mail.status = ElectionMail.Status.SENDING
                mail.save(update_fields=["status"])
            accepted = EmailMessage(mail.subject, mail.body, settings.DEFAULT_FROM_EMAIL,
                                    to=[mail.recipient], connection=connection).send(fail_silently=False)
            if accepted != 1:
                raise RuntimeError("Mail service did not confirm acceptance")
            ElectionMail.objects.filter(pk=mail.pk).update(status=ElectionMail.Status.SENT, sent_at=timezone.now())
            sent += 1
    except Exception:
        logger.error("Election mail delivery paused; inspect queued/uncertain notifications and provider quota.")
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                logger.error("Election SMTP connection could not close cleanly.")
    return sent
