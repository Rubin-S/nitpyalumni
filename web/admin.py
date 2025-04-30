from django.contrib import admin
from django.http import HttpResponse
import csv
from .models import UserData, JobPosting, Talk, DonateBook

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
    actions = [export_as_csv]

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

# Customizing admin site titles
admin.site.site_header = "NITPY Alumni"
admin.site.site_title = "NITPY Alumni Admin Portal"
admin.site.index_title = "Welcome to NITPY Alumni Admin"
