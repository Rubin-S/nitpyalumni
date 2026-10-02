from django.contrib import admin
from django.http import HttpResponse
import csv
from .models import (
    UserData, JobPosting, Talk, DonateBook, Website,
    GuestHouseBookingRequest, CardApplicationRequest, GetTranscriptRequest
)

# Universal export as CSV action
def export_as_csv(modeladmin, request, queryset):
    meta = modeladmin.model._meta
    field_names = [field.name for field in meta.fields]

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename={meta}.csv'
    writer = csv.writer(response)

    writer.writerow(field_names)
    for obj in queryset:
        writer.writerow([getattr(obj, field) for field in field_names])

    return response

export_as_csv.short_description = "Export Selected as CSV"

# UserData Admin
@admin.register(UserData)
class UserDataAdmin(admin.ModelAdmin):
    list_display = ('user', 'roll_no', 'name', 'account_is_approved', 'batch', 'department', 'in_job')
    list_filter = ('account_is_approved', 'batch', 'department', 'in_job', 'country', 'state', 'city')
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

    actions = [export_as_csv, approve_selected]
    
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
