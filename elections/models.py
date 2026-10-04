import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
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

        if self.pk and self.votes.exists():
            original = Election.objects.filter(pk=self.pk).first()
            if original:
                if not self.is_published:
                    raise ValidationError({"is_published": "Cannot un-publish an election that already has cast votes."})
                if self.nomination_start != original.nomination_start or self.nomination_end != original.nomination_end:
                    raise ValidationError("Cannot modify nomination dates after votes have been cast.")
                if self.voting_start != original.voting_start:
                    raise ValidationError({"voting_start": "Cannot modify voting start date after votes have been cast."})

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
            election = self.election
            voting_started = (
                election.phase in (Election.Phase.VOTING_OPEN, Election.Phase.CLOSED)
                or election.votes.exists()
            )
            if voting_started:
                if self.pk is None:
                    raise ValidationError("Cannot add new positions once voting has started.")
                original = Position.objects.filter(pk=self.pk).first()
                if original and original.title != self.title:
                    raise ValidationError({"title": "Cannot rename positions once voting has started."})

    def delete(self, *args, **kwargs):
        if self.election_id:
            election = self.election
            voting_started = (
                election.phase in (Election.Phase.VOTING_OPEN, Election.Phase.CLOSED)
                or election.votes.exists()
            )
            if voting_started:
                raise ValidationError("Cannot delete positions once voting has started.")
        super().delete(*args, **kwargs)


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
    manifesto = models.TextField(max_length=MANIFESTO_MAX_LENGTH)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    review_note = models.CharField(
        max_length=500, blank=True,
        help_text="Optional note included in the email sent to the candidate.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position__order", "candidate__name"]
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
        return f"{self.candidate.name} for {self.position.title} [{self.get_status_display()}]"

    def clean(self):
        if self.position_id and self.election_id and self.position.election_id != self.election_id:
            raise ValidationError({"position": "Position does not belong to this election."})

        if self.pk:
            orig = Nomination.objects.filter(pk=self.pk).values("status").first()
            if orig and orig["status"] != self.status:
                voting_started = (
                    self.election.phase in (Election.Phase.VOTING_OPEN, Election.Phase.CLOSED)
                    or self.election.votes.exists()
                )
                if voting_started:
                    raise ValidationError("Nominations cannot be approved or rejected after voting has started.")

    def delete(self, *args, **kwargs):
        if self.election_id:
            voting_started = (
                self.election.phase in (Election.Phase.VOTING_OPEN, Election.Phase.CLOSED)
                or self.election.votes.exists()
            )
            if voting_started:
                raise ValidationError("Cannot delete nominations once voting has started.")
        super().delete(*args, **kwargs)

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

        super().save(*args, **kwargs)

        # Same pattern as the rest of the project: emails are sent from save().
        if is_new:
            notifications.notify_staff_new_nomination(self)
        elif status_changed and self.status in (self.Status.APPROVED, self.Status.REJECTED):
            notifications.notify_candidate_status(self)


class VoterRecord(models.Model):
    """Records THAT a member voted in an election. Stores nothing about the choices."""

    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="voter_records")
    voter = models.ForeignKey(
        "web.UserData", on_delete=models.CASCADE, related_name="voter_records"
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
    primary key, so a vote cannot be linked back to a VoterRecord.
    PROTECT stops deleting elections/positions/candidates that hold votes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="votes")
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name="votes")
    nomination = models.ForeignKey(Nomination, on_delete=models.PROTECT, related_name="votes")

    def __str__(self):
        return "Anonymous vote"
