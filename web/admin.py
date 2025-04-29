from django.contrib import admin
from .models import UserData, JobPosting, Talk

@admin.register(UserData)
class UserDataAdmin(admin.ModelAdmin):
    list_display = ('user', 'roll_no', 'name', 'account_is_approved', 'batch', 'department', 'in_job')
    list_filter = ('account_is_approved', 'batch', 'department', 'in_job', 'country', 'state', 'city')
    search_fields = ('user__username', 'name', 'roll_no', 'email_id', 'phone_number')
    ordering = ('batch', 'department', 'name')

@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ('job_title', 'job_company', 'job_location', 'is_approved', 'posted_by')
    list_filter = ('is_approved', 'job_company', 'job_location')
    search_fields = ('job_title', 'job_company', 'job_location', 'posted_by__username')
    ordering = ('-id',)

@admin.register(Talk)
class TalkAdmin(admin.ModelAdmin):
    list_display = ('user', 'topic', 'venue', 'datetime')
    list_filter = ('venue', 'datetime')
    search_fields = ('user__username', 'topic', 'venue', 'current_position')
    ordering = ('-datetime',)



from django.contrib import admin

# Change admin site header and title
admin.site.site_header = "NITPY Alumni"
admin.site.site_title = "NITPY Alumni Admin Portal"
admin.site.index_title = "Welcome to NITPY Alumni Admin"
