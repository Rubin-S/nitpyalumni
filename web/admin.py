from django.contrib import admin
from django.db import transaction
from django.http import HttpResponse
import csv

from web.csv_safe import safe_row
from .models import (
    UserData, JobPosting, Talk, DonateBook, Website,
    GuestHouseBookingRequest, CardApplicationRequest, GetTranscriptRequest
)

# Universal export as CSV action
def export_as_csv(modeladmin, request, queryset):
    meta = modeladmin.model._meta
    field_names = [field.name for field in meta.fields]

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{meta.model_name}.csv"'
    writer = csv.writer(response)

    writer.writerow(field_names)
    for obj in queryset:
        writer.writerow(safe_row([getattr(obj, field) for field in field_names]))

    return response

export_as_csv.short_description = "Export Selected as CSV"

# UserData Admin
@admin.register(UserData)
class UserDataAdmin(admin.ModelAdmin):
    list_display = ('user', 'roll_no', 'name', 'account_is_approved', 'is_eligible_to_vote', 'batch', 'department', 'in_job')
    list_filter = ('account_is_approved', 'is_eligible_to_vote', 'batch', 'department', 'in_job', 'country', 'state', 'city')
    search_fields = ('user__username', 'name', 'roll_no', 'email_id', 'phone_number')
    ordering = ('batch', 'department', 'name')

    @admin.action(description="Approve selected users and send approval email")
    def approve_selected(modeladmin, request, queryset):
        unapproved = queryset.filter(account_is_approved=False)
        count = 0
        for profile in unapproved:
            profile.account_is_approved = True
            profile.save()
            count += 1
        modeladmin.message_user(request, f"{count} alumni account(s) approved and notified.")

    @admin.action(description="Mark selected as eligible to vote")
    @transaction.atomic
    def mark_eligible_to_vote(modeladmin, request, queryset):
        # queryset.update() bypasses UserData.save() (no geocoding / emails).
        skipped = queryset.filter(account_is_approved=False).count()
        count = 0
        for profile in queryset.select_for_update().filter(account_is_approved=True, is_eligible_to_vote=False):
            UserData.objects.filter(pk=profile.pk).update(is_eligible_to_vote=True)
            modeladmin.log_change(request, profile, "Election voting eligibility granted.")
            count += 1
        modeladmin.message_user(
            request,
            f"{count} alumni marked eligible to vote. {skipped} skipped (account not approved).",
        )

    @admin.action(description="Revoke voting eligibility for selected")
    @transaction.atomic
    def revoke_voting_eligibility(modeladmin, request, queryset):
        count = 0
        for profile in queryset.select_for_update().filter(is_eligible_to_vote=True):
            UserData.objects.filter(pk=profile.pk).update(is_eligible_to_vote=False)
            modeladmin.log_change(request, profile, "Election voting eligibility revoked.")
            count += 1
        modeladmin.message_user(request, f"Voting eligibility revoked for {count} alumni.")

    actions = [export_as_csv, approve_selected, mark_eligible_to_vote, revoke_voting_eligibility]
    
# JobPosting Admin
@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ('job_title', 'job_company', 'job_location', 'is_approved', 'posted_by')
    list_filter = ('is_approved', 'job_company', 'job_location')
    search_fields = ('job_title', 'job_company', 'job_location', 'posted_by__username')
    ordering = ('-id',)
    actions = [export_as_csv]

# Talk Admin
@admin.register(Talk)
class TalkAdmin(admin.ModelAdmin):
    list_display = ('user', 'topic', 'venue', 'datetime')
    list_filter = ('venue', 'datetime')
    search_fields = ('user__username', 'topic', 'venue', 'current_position')
    ordering = ('-datetime',)
    actions = [export_as_csv]

# DonateBook Admin
@admin.register(DonateBook)
class DonateBookAdmin(admin.ModelAdmin):
    list_display = ('booktitle', 'user', 'is_approved')
    list_filter = ('is_approved',)
    search_fields = ('booktitle', 'user__username', 'user__email')
    actions = [export_as_csv]

@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'content')
    search_fields = ('name', 'user__roll_no', 'user__user__username')
    list_filter = ('user__batch', 'user__department')
    ordering = ('name',)

# GuestHouseBookingRequest Admin
@admin.register(GuestHouseBookingRequest)
class GuestHouseBookingRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'get_name', 'type_of_room', 'datetime_in', 'datetime_out')
    list_filter = ('type_of_room', 'datetime_in', 'datetime_out')
    search_fields = ('user__username', 'userdata__name', 'reason_of_visit')
    ordering = ('-datetime_in',)
    actions = [export_as_csv]

    @admin.display(description='Alumni Name')
    def get_name(self, obj):
        return obj.userdata.name if obj.userdata else obj.user.get_full_name()

# CardApplicationRequest Admin
@admin.register(CardApplicationRequest)
class CardApplicationRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'get_name', 'reason', 'utr_transaction_number')
    list_filter = ('reason',)
    search_fields = ('user__username', 'userdata__name', 'utr_transaction_number')
    actions = [export_as_csv]

    @admin.display(description='Alumni Name')
    def get_name(self, obj):
        return obj.userdata.name if obj.userdata else obj.user.get_full_name()

# GetTranscriptRequest Admin
@admin.register(GetTranscriptRequest)
class GetTranscriptRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'get_name', 'requested_on')
    list_filter = ('requested_on',)
    search_fields = ('user__username', 'userdata__name')
    ordering = ('-requested_on',)
    actions = [export_as_csv]

    @admin.display(description='Alumni Name')
    def get_name(self, obj):
        return obj.userdata.name if obj.userdata else obj.user.get_full_name()
# Customizing admin site titles
admin.site.site_header = "NITPY Alumni"
admin.site.site_title = "NITPY Alumni Admin Portal"
admin.site.index_title = "Welcome to NITPY Alumni Admin"
