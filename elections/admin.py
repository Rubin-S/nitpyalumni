import csv

from web.csv_safe import safe_row

from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils.html import format_html, format_html_join

from elections import services
from elections.models import Election, Nomination, Position, VoterRecord
from elections.services import ElectionError

# NOTE: Vote is intentionally NOT registered, so individual (anonymous) votes
# are never browsable from the admin. Use the tally on the Election page.


class PositionInline(admin.TabularInline):
    model = Position
    extra = 1
    fields = ("title", "description", "order")

    def has_add_permission(self, request, obj=None):
        if obj and (obj.phase in (Election.Phase.VOTING_OPEN, Election.Phase.CLOSED) or obj.votes.exists()):
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and (obj.phase in (Election.Phase.VOTING_OPEN, Election.Phase.CLOSED) or obj.votes.exists()):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and (obj.phase in (Election.Phase.VOTING_OPEN, Election.Phase.CLOSED) or obj.votes.exists()):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = (
        "title", "phase_display", "is_published", "nomination_start", "nomination_end",
        "voting_start", "voting_end", "results_published",
    )
    list_filter = ("is_published", "results_published")
    search_fields = ("title",)
    inlines = [PositionInline]
    readonly_fields = (
        "phase_display", "results_published", "eligible_voter_count",
        "voting_open_email_sent_at", "created_at", "turnout_summary", "results_summary",
    )
    fieldsets = (
        (None, {"fields": ("title", "description", "is_published", "phase_display")}),
        ("Timeline", {
            "fields": ("nomination_start", "nomination_end", "voting_start", "voting_end"),
            "description": "Phases change automatically based on these dates (server time: Asia/Kolkata).",
        }),
        ("Results", {
            "fields": (
                "results_published", "eligible_voter_count", "voting_open_email_sent_at",
                "turnout_summary", "results_summary",
            ),
        }),
        ("Meta", {"fields": ("created_at",), "classes": ("collapse",)}),
    )
    actions = [
        "publish_results", "email_voters_voting_open", "reset_voting_open_announcement",
        "export_turnout_csv",
    ]

    @admin.display(description="Phase")
    def phase_display(self, obj):
        if obj.pk is None:
            return "-"
        return obj.phase_label

    @admin.display(description="Turnout")
    def turnout_summary(self, obj):
        if obj.pk is None:
            return "-"
        t = services.turnout(obj)
        return f"{t['voted']} voted / {t['eligible']} eligible ({t['percent']}%)"

    @admin.display(description="Tally")
    def results_summary(self, obj):
        if obj.pk is None:
            return "-"
        try:
            results = services.tally(obj)
        except ElectionError:
            return "Tallies are hidden until voting closes."
        blocks = []
        for row in results:
            items = format_html_join(
                "",
                "<li>{}{} ({}) - <strong>{}</strong> vote(s){}</li>",
                (
                    (
                        c["nomination"].candidate.name,
                        "" if c["nomination"].status == Nomination.Status.APPROVED
                        else f" [{c['nomination'].get_status_display()}]",
                        c["nomination"].candidate.roll_no,
                        c["votes"],
                        " - TIE" if c["is_winner"] and row["is_tie"]
                        else (" - WINNER" if c["is_winner"] else ""),
                    )
                    for c in row["candidates"]
                ),
            )
            blocks.append(format_html(
                "<p><strong>{}</strong> ({} vote(s))</p><ul>{}</ul>",
                row["position"].title, row["total"], items or "No candidates",
            ))
        return format_html_join("", "{}", ((b,) for b in blocks)) or "No positions."

    @admin.action(description="Publish results (voting must be closed)")
    def publish_results(self, request, queryset):
        for election in queryset:
            try:
                services.publish_results(election)
            except ElectionError as exc:
                self.message_user(request, f"{election.title}: {exc}", messages.ERROR)
            else:
                self.message_user(request, f"{election.title}: results published.")

    @admin.action(description="Email all eligible voters that voting is open")
    def email_voters_voting_open(self, request, queryset):
        for election in queryset:
            try:
                recipients, batches = services.announce_voting_open(election)
            except ElectionError as exc:
                self.message_user(request, f"{election.title}: {exc}", messages.ERROR)
            else:
                self.message_user(
                    request,
                    f"{election.title}: announcement sent to {recipients} voter(s) in {batches} email(s).",
                )

    @admin.action(description="Reset voting-open announcement flag (allows re-sending)")
    def reset_voting_open_announcement(self, request, queryset):
        updated = queryset.update(voting_open_email_sent_at=None)
        self.message_user(request, f"Announcement flag reset for {updated} election(s).")

    @admin.action(description="Export turnout (who voted, no choices) as CSV")
    def export_turnout_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=election_turnout.csv"
        writer = csv.writer(response)
        writer.writerow(["election", "roll_no", "name", "batch", "department"])
        records = VoterRecord.objects.filter(election__in=queryset).select_related(
            "election", "voter"
        ).order_by("election__title", "voter__name")
        for r in records:
            writer.writerow(safe_row([r.election.title, r.voter.roll_no, r.voter.name, r.voter.batch, r.voter.department]))
        return response


@admin.register(Nomination)
class NominationAdmin(admin.ModelAdmin):
    list_display = ("candidate", "position", "election", "status", "created_at", "reviewed_at")
    list_filter = ("status", "election")
    search_fields = ("candidate__name", "candidate__roll_no", "position__title", "election__title")
    list_select_related = ("candidate", "position", "election")
    readonly_fields = (
        "election", "position", "candidate", "manifesto", "status", "created_at", "reviewed_at",
    )
    fields = readonly_fields + ("review_note",)
    actions = ["approve_nominations", "reject_nominations"]

    def has_add_permission(self, request):
        # Nominations come from alumni through the site.
        return False

    def _review(self, request, queryset, approve):
        done = 0
        for nomination in queryset.select_related("election", "candidate", "position"):
            try:
                services.review_nomination(nomination, approve=approve)
                done += 1
            except ElectionError as exc:
                self.message_user(request, f"{nomination.candidate.name}: {exc}", messages.ERROR)
        verb = "approved" if approve else "rejected"
        if done:
            self.message_user(request, f"{done} nomination(s) {verb}; candidates notified by email.")

    @admin.action(description="Approve selected nominations (emails candidate)")
    def approve_nominations(self, request, queryset):
        self._review(request, queryset, approve=True)

    @admin.action(description="Reject selected nominations (emails candidate)")
    def reject_nominations(self, request, queryset):
        self._review(request, queryset, approve=False)


@admin.register(VoterRecord)
class VoterRecordAdmin(admin.ModelAdmin):
    """Read-only audit of WHO voted. Choices are not stored here."""
    list_display = ("voter", "election")
    list_filter = ("election",)
    search_fields = ("voter__name", "voter__roll_no")
    list_select_related = ("voter", "election")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
