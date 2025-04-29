from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
recipient_list=['naveenraj.r@nitpy.ac.in', 'gupta.ojas.27@gmail.com']
# Utility function to send email
def send_creation_email(subject, message):
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=recipient_list,
        fail_silently=False,
    )


class UserData(models.Model):
    account_is_approved = models.BooleanField(default=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    roll_no = models.CharField(max_length=25)
    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    batch = models.IntegerField()
    department = models.CharField(max_length=100)
    email_id = models.EmailField()
    facebook = models.URLField(blank=True, null=True)
    instagram = models.URLField(blank=True, null=True)
    in_job = models.BooleanField(default=False)
    present_address = models.TextField()
    job_title = models.CharField(max_length=255, blank=True, null=True)
    higher_study_uni_name = models.CharField(max_length=255, blank=True, null=True)
    higher_study_uni_address = models.CharField(max_length=255, blank=True, null=True)
    higher_study_field = models.CharField(max_length=255, blank=True, null=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            send_creation_email(f"New User {self.name} has applied for alumni account", f"A new user named: {self.name}, phone number: {self.phone_number} has applied. Kindly check admin panel to approve or reject the request")

    def __str__(self):
        return f"{self.name} ({self.roll_no})"


class JobPosting(models.Model):
    is_approved = models.BooleanField(default=False)
    job_title = models.CharField(max_length=255)
    job_company = models.CharField(max_length=255)
    job_location = models.CharField(max_length=255)
    posted_by = models.ForeignKey(User, on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            send_creation_email(f"New job titled: {self.job_title} is added by {self.posted_by.username}", f"Kindly consider approving or rejecting it in admin panel")

    def __str__(self):
        return f"{self.job_title} at {self.job_company}"


class Talk(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    current_position = models.TextField()
    short_bio = models.TextField()
    topic = models.TextField()
    datetime = models.DateTimeField()
    venue = models.CharField(max_length=255)
    extra_text = models.TextField()
    is_approved = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            send_creation_email(f"New talk titled: {self.topic} is added by {self.user.username}", f"Kindly consider approving or rejecting it in admin panel")

    def __str__(self):
        return f"Talk on {self.topic} by {self.user.username}"


class GuestHouseBookingRequest(models.Model):
    ROOM_CHOICES = [
        ('Single', 'Single'),
        ('Double', 'Double'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    userdata = models.ForeignKey('UserData', on_delete=models.CASCADE, blank=True, null=True)
    type_of_room = models.CharField(max_length=10, choices=ROOM_CHOICES)
    reason_of_visit = models.TextField()
    datetime_in = models.DateTimeField()
    datetime_out = models.DateTimeField()

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.userdata:
            self.userdata = UserData.objects.filter(user=self.user).first()
        super().save(*args, **kwargs)
        if is_new:
            send_creation_email(f"New guest house booking by: {self.userdata.name}", f"Kindly consider approving or rejecting it in admin panel")

    def __str__(self):
        return f"{self.user.username} - {self.type_of_room} Room Booking"


class CardApplicationRequest(models.Model):
    REASON_CHOICES = [
        ('First Application', 'First Application'),
        ('Card Lost', 'Card Lost'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    userdata = models.ForeignKey('UserData', on_delete=models.CASCADE, blank=True, null=True)
    reason = models.CharField(max_length=50, choices=REASON_CHOICES)
    utr_transaction_number = models.CharField(max_length=100)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.userdata:
            self.userdata = UserData.objects.filter(user=self.user).first()
        super().save(*args, **kwargs)
        if is_new:
            send_creation_email(f"New Card Application request by: {self.userdata.name}", f"Kindly consider approving or rejecting it in admin panel")

    def __str__(self):
        return f"{self.user.username} - {self.reason}"


class GetTranscriptRequest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    userdata = models.ForeignKey('UserData', on_delete=models.CASCADE, blank=True, null=True)
    requested_on = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.userdata:
            self.userdata = UserData.objects.filter(user=self.user).first()
        super().save(*args, **kwargs)
        if is_new:
            send_creation_email(f"New Transcript request by: {self.userdata.name}", f"Kindly consider approving or rejecting it in admin panel")

    def __str__(self):
        return f"{self.user.username} - Transcript Request"
