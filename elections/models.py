import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone


class Election(models.Model):
    class Phase(models.TextChoices):
        DRAFT = "draft", "Draft"
        UPCOMING = "upcoming", "Upcoming"
        NOMINATIONS_OPEN = "nominations_open", "Nominations Open"
        NOMINATIONS_CLOSED = "nominations_closed", "Nominations Closed"
        VOTING_OPEN = "voting_open", "Voting Open"
        CLOSED = "closed", "Voting Closed"

    PHASE_BADGES = {
        Phase.DRAFT: "secondary",
        Phase.UPCOMING: "info",
        Phase.NOMINATIONS_OPEN: "primary",
        Phase.NOMINATIONS_CLOSED: "warning",
        Phase.VOTING_OPEN: "success",
        Phase.CLOSED: "dark",
    }

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_published = models.BooleanField(
        default=False,
        help_text="Unpublished elections are drafts and are hidden from alumni.",
    )
    nomination_start = models.DateTimeField()
    nomination_end = models.DateTimeField()
    voting_start = models.DateTimeField()
    voting_end = models.DateTimeField()
    results_published = models.BooleanField(default=False)
    eligible_voter_count = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Snapshot of eligible voters taken when results are published.",
    )
    voting_open_email_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-voting_start", "-id"]
        constraints = [models.CheckConstraint(
            condition=Q(nomination_start__lt=models.F("nomination_end"))
            & Q(nomination_end__lt=models.F("voting_start"))
            & Q(voting_start__lt=models.F("voting_end")), name="election_timeline_order",
        )]

    def __str__(self):
        return self.title

    def clean(self):
        dates = [self.nomination_start, self.nomination_end, self.voting_start, self.voting_end]
        if any(d is None for d in dates):
            return
        if not self.nomination_start < self.nomination_end:
            raise ValidationError({"nomination_end": "Nomination end must be after nomination start."})
        if not self.nomination_end < self.voting_start:
            raise ValidationError({"voting_start": "Voting cannot start until after nominations have closed."})
        if not self.voting_start < self.voting_end:
            raise ValidationError({"voting_end": "Voting end must be after voting start."})

        original = Election.objects.filter(pk=self.pk).first() if self.pk else None
        if self.is_published and (not original or not original.is_published) and timezone.now() >= self.voting_start:
            raise ValidationError({"voting_start": "Choose a future voting start before publishing the election."})

        if self.pk:
            if original and original.is_frozen:
                fields = ("nomination_start", "nomination_end", "voting_start", "voting_end", "is_published")
                if any(getattr(self, f) != getattr(original, f) for f in fields):
                    raise ValidationError("The election timeline and publication are locked once voting starts.")
                if original.results_published and (
                    not self.results_published or self.eligible_voter_count != original.eligible_voter_count
                ):
                    raise ValidationError("Published results and their turnout snapshot cannot be changed.")
        if self.results_published and self.phase != self.Phase.CLOSED:
            raise ValidationError("Results can only be published after voting closes.")

    @property
    def is_frozen(self):
        return bool(self.results_published or (
            self.is_published and self.voting_start and timezone.now() >= self.voting_start
        ) or (self.pk and self.votes.exists()))

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                Election.objects.select_for_update().filter(pk=self.pk).first()
            self.full_clean()
            return super().save(*args, **kwargs)

    def phase_at(self, when):
        """Phase of this election at the given moment (pure; used for testing)."""
        if not self.is_published:
            return self.Phase.DRAFT
        if when < self.nomination_start:
            return self.Phase.UPCOMING
        if when < self.nomination_end:
            return self.Phase.NOMINATIONS_OPEN
        if when < self.voting_start:
            return self.Phase.NOMINATIONS_CLOSED
        if when < self.voting_end:
            return self.Phase.VOTING_OPEN
        return self.Phase.CLOSED

    @property
    def phase(self):
        return self.phase_at(timezone.now())

    @property
    def phase_label(self):
        return self.Phase(self.phase).label

    @property
    def phase_badge(self):
        return self.PHASE_BADGES[self.phase]


class Position(models.Model):
    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="positions")
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["election", "title"], name="unique_position_title_per_election"
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.election.title})"

    def clean(self):
        super().clean()
        if self.title:
            self.title = self.title.strip()
        if self.election_id:
            election = Election.objects.get(pk=self.election_id)
            original = Position.objects.filter(pk=self.pk).first() if self.pk else None
            if original and original.election_id != self.election_id:
                raise ValidationError("Positions cannot be moved to another election.")
            voting_started = election.is_frozen
            if voting_started:
                if self.pk is None:
                    raise ValidationError("Cannot add new positions once voting has started.")
                if original and any(getattr(original, f) != getattr(self, f) for f in ("title", "description", "order")):
                    raise ValidationError("Cannot change positions once voting has started.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            Election.objects.select_for_update().get(pk=self.election_id)
            self.full_clean()
            return super().save(*args, **kwargs)

class Nomination(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    ACTIVE_STATUSES = (Status.PENDING, Status.APPROVED)
    MANIFESTO_MAX_LENGTH = 3000

    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="nominations")
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="nominations")
    candidate = models.ForeignKey(
        "web.UserData", on_delete=models.CASCADE, related_name="nominations"
    )
    candidate_snapshot = models.JSONField(default=dict, editable=False)
    manifesto = models.TextField(max_length=MANIFESTO_MAX_LENGTH)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    review_note = models.CharField(
        max_length=500, blank=True,
        help_text="Optional note included in the email sent to the candidate.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position__order", "id"]
        constraints = [
            # One *active* nomination per person per election;
            # withdrawn/rejected nominees may nominate again.
            models.UniqueConstraint(
                fields=["election", "candidate"],
                condition=Q(status__in=["pending", "approved"]),
                name="one_active_nomination_per_election",
            ),
        ]

    def __str__(self):
        return f"{self.candidate_name} for {self.position.title} [{self.get_status_display()}]"

    @property
    def candidate_name(self):
        return self.candidate_snapshot.get("name", self.candidate.name)

    @property
    def candidate_department(self):
        return self.candidate_snapshot.get("department", self.candidate.department)

    @property
    def candidate_batch(self):
        return self.candidate_snapshot.get("batch", self.candidate.batch)

    @property
    def candidate_roll_no(self):
        return self.candidate_snapshot.get("roll_no", self.candidate.roll_no)

    def clean(self):
        if self.position_id and self.election_id and self.position.election_id != self.election_id:
            raise ValidationError({"position": "Position does not belong to this election."})

        orig = Nomination.objects.filter(pk=self.pk).first() if self.pk else None
        if orig and orig.candidate_snapshot != self.candidate_snapshot:
            raise ValidationError("A nomination's submitted candidate identity cannot be changed.")
        if orig and any(getattr(orig, f) != getattr(self, f) for f in ("election_id", "position_id", "candidate_id")):
            raise ValidationError("The candidate, election and position of a nomination cannot be reassigned.")
        if self.election_id and Election.objects.get(pk=self.election_id).is_frozen:
            if not orig or any(getattr(orig, f) != getattr(self, f) for f in ("status", "manifesto")):
                raise ValidationError("Nominations cannot be changed after voting has started.")

    def save(self, *args, **kwargs):
        # Imported lazily to avoid a circular import (notifications -> models).
        from elections import notifications

        is_new = self.pk is None
        old_status = None
        if not is_new:
            old_status = (
                Nomination.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
        status_changed = not is_new and old_status != self.status
        if status_changed and self.status in (self.Status.APPROVED, self.Status.REJECTED):
            self.reviewed_at = timezone.now()
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"reviewed_at"}

        with transaction.atomic():
            Election.objects.select_for_update().get(pk=self.election_id)
            if is_new:
                self.candidate_snapshot = {
                    "name": self.candidate.name, "department": self.candidate.department,
                    "batch": self.candidate.batch, "roll_no": self.candidate.roll_no,
                }
            self.full_clean()
            super().save(*args, **kwargs)
            if is_new:
                notifications.notify_staff_new_nomination(self)
            elif status_changed and self.status in (self.Status.APPROVED, self.Status.REJECTED):
                notifications.notify_candidate_status(self)


class VoterRecord(models.Model):
    """Records THAT a member voted in an election. Stores nothing about the choices."""

    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="voter_records")
    voter = models.ForeignKey(
        "web.UserData", on_delete=models.PROTECT, related_name="voter_records"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["election", "voter"], name="one_ballot_per_voter"),
        ]

    def __str__(self):
        return f"{self.voter.name} voted in {self.election.title}"


class Vote(models.Model):
    """
    One anonymous choice on a secret ballot.

    Deliberately has NO voter reference, NO timestamp, and a random UUID
    primary key. There is no application-level voter/choice link. Database
    operators and transaction logs remain trusted; this is not cryptographic anonymity.
    PROTECT stops deleting elections/positions/candidates that hold votes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="votes")
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name="votes")
    nomination = models.ForeignKey(Nomination, on_delete=models.PROTECT, related_name="votes")

    def __str__(self):
        return "Anonymous vote"


@receiver(pre_delete, sender=Election)
@receiver(pre_delete, sender=Position)
@receiver(pre_delete, sender=Nomination)
def protect_started_election(sender, instance, using, **kwargs):
    # Signals also cover admin bulk deletion and cascades, which bypass delete().
    pk = instance.pk if sender is Election else instance.election_id
    election = Election.objects.using(using).select_for_update().filter(pk=pk).first()
    if election and election.is_frozen:
        raise ValidationError("Cannot delete election records once voting has started.")


class ElectionMail(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Queued"
        SENDING = "sending", "Delivery uncertain — review before retrying"
        SENT = "sent", "Accepted by mail service"
        EXPIRED = "expired", "Voting closed before announcement was sent"

    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="mail")
    event_key = models.CharField(max_length=64, unique=True)
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField()
    priority = models.PositiveSmallIntegerField(default=20)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["priority", "created_at", "pk"]
        indexes = [models.Index(fields=["status", "priority", "created_at"])]
