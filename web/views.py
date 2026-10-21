import json
from functools import wraps
import hashlib
import os
import re
import ipaddress
import logging
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.db import DatabaseError, transaction
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
from django.db.models import Q, Prefetch
from django.http import JsonResponse, HttpResponseForbidden, Http404
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.utils.timezone import now
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from web.access import approved_alumni_required
from web.forms import AlumniProfileForm
from web import messaging
from web import throttle

from web.models import (
    UserData, DirectMessage, DonateBook, JobPosting, Talk, Website,
    GuestHouseBookingRequest, CardApplicationRequest, GetTranscriptRequest
)
from web.helper.cf import CloudflareDNSManager

logger = logging.getLogger(__name__)

# Model column limits; longer input would raise a database error (HTTP 500).
PROFILE_FIELD_LIMITS = {
    "name": 255, "phone_number": 20, "country": 100, "state": 100, "city": 100,
    "department": 100, "degree": 50, "present_address": 2000, "job_title": 255,
    "job_address": 500, "higher_study_uni_name": 255,
    "higher_study_uni_address": 255, "higher_study_field": 255, "email_id": 254,
}
_http_url = URLValidator(schemes=["http", "https"])


def clean_social_url(value, label):
    """Return a safe http(s) URL or "" ; rejects javascript:/data: and junk."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    if len(value) > 200:
        raise ValidationError(f"{label} link is too long.")
    try:
        _http_url(value)
    except ValidationError:
        raise ValidationError(f"Please enter a valid {label} link (https://...).")
    return value


def check_profile_lengths(values):
    for field, limit in PROFILE_FIELD_LIMITS.items():
        value = values.get(field)
        if value and len(value) > limit:
            label = field.replace("_", " ")
            raise ValidationError(f"{label.capitalize()} must be at most {limit} characters.")


def clean_batch(raw):
    try:
        batch = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValidationError("Please select a valid batch.")
    if not 1950 <= batch <= 2100:
        raise ValidationError("Please select a valid batch.")
    return batch


def client_ip(request):
    """Trusted client IP, or None (then per-IP limits are skipped)."""
    from web.auth_backend import _client_ip
    return _client_ip(request)

def index(request):
    if request.user.is_authenticated:
        user = UserData.objects.filter(user=request.user).first()
        if user is None:
            if request.user.is_staff:
                return redirect("/admin/")
            return render(request, "home.html", {"missing_alumni_profile": True})
        is_approved = user.account_is_approved
        return render(request, "student_dash.html", context={"user": user, "is_approved": is_approved})
    return render(request, "home.html")
def vam(request):
    return render(request, "vision_and_mission.html")
def dm(request):
    return render(request, "director_message.html")

def login_view(request):
    if request.user.is_authenticated:
        return redirect("/")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        password = request.POST.get("password") or ""

        user_auth = authenticate(request, username=email, password=password)

        if user_auth is not None:
            login(request, user_auth)
            return redirect("/")

        if getattr(request, "login_throttled", False):
            messages.error(
                request,
                "Too many failed sign-in attempts. Please wait 15 minutes or reset your password.",
            )
            return render(request, "login.html", status=429)

        # Keep the response identical for unknown emails and bad passwords.
        messages.error(request, "Invalid email or password. Please try again.")

    return render(request, "login.html")


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("/")

    if request.method != "POST":
        return render(request, "signup.html")

    signup_ip = client_ip(request)
    if signup_ip is not None and not throttle.consume(
            "signup-ip", signup_ip, settings.SIGNUP_LIMIT_PER_IP_PER_HOUR, 3600):
        messages.error(request, "Too many sign-up attempts from your network. Please try again later.")
        return redirect("signup")

    try:
        name = (request.POST.get("name") or "").strip()
        roll_no = (request.POST.get("roll_no") or "").strip().upper()
        phone_number = (request.POST.get("phone_number") or "").strip()
        raw_email = (request.POST.get("email_id") or "").strip()
        email_id = User.objects.normalize_email(raw_email)
        country = (request.POST.get("country") or "").strip()
        state = (request.POST.get("state") or "").strip()
        city = (request.POST.get("city") or "").strip()
        batch_raw = (request.POST.get("batch") or "").strip()
        degree = (request.POST.get("degree") or "").strip()
        department = (request.POST.get("department") or "").strip()
        present_address = (request.POST.get("present_address") or "").strip()
        linked_id = (request.POST.get("linkedin") or "").strip()
        facebook = (request.POST.get("facebook") or "").strip()
        instagram = (request.POST.get("instagram") or "").strip()
        current_status = (request.POST.get("current_status") or "").strip()
        job_title = (request.POST.get("job_title") or "").strip()
        job_address = (request.POST.get("job_address") or "").strip()
        higher_study_uni_name = (request.POST.get("higher_study_uni_name") or "").strip()
        higher_study_uni_address = (request.POST.get("higher_study_uni_address") or "").strip()
        higher_study_field = (request.POST.get("higher_study_field") or "").strip()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""

        required_values = (
            name,
            roll_no,
            phone_number,
            email_id,
            country,
            state,
            city,
            batch_raw,
            degree,
            department,
            present_address,
            current_status,
            password1,
            password2,
        )
        if not all(required_values):
            raise ValidationError("Please complete all required fields.")

        if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z]\d{4}", roll_no):
            raise ValidationError("User not valid.")

        validate_email(email_id)
        check_profile_lengths({
            "name": name, "phone_number": phone_number, "country": country,
            "state": state, "city": city, "department": department, "degree": degree,
            "present_address": present_address, "job_title": job_title,
            "job_address": job_address, "higher_study_uni_name": higher_study_uni_name,
            "higher_study_uni_address": higher_study_uni_address,
            "higher_study_field": higher_study_field, "email_id": email_id,
        })
        linked_id = clean_social_url(linked_id, "LinkedIn")
        facebook = clean_social_url(facebook, "Facebook")
        instagram = clean_social_url(instagram, "Instagram")
        batch = clean_batch(batch_raw)

        if current_status not in {"job", "study", "none"}:
            raise ValidationError("Please select a valid current status.")

        if password1 != password2:
            raise ValidationError("Passwords do not match.")

        if User.objects.filter(username=roll_no).exists():
            raise ValidationError("Roll number already registered.")

        if User.objects.filter(email__iexact=email_id).exists():
            raise ValidationError("Email already registered.")

        name_parts = name.split()
        candidate_user = User(
            username=roll_no,
            email=email_id,
            first_name=name_parts[0],
            last_name=" ".join(name_parts[1:]),
        )
        validate_password(password1, user=candidate_user)

        # User and UserData must be created together or not at all.
        with transaction.atomic():
            user = User.objects.create_user(
                username=roll_no,
                email=email_id,
                password=password1,
                first_name=candidate_user.first_name,
                last_name=candidate_user.last_name,
            )

            UserData.objects.create(
                user=user,
                roll_no=roll_no,
                name=name,
                phone_number=phone_number,
                country=country,
                state=state,
                city=city,
                batch=batch,
                department=department,
                degree=degree,
                email_id=email_id,
                linked_in=linked_id,
                facebook=facebook,
                instagram=instagram,
                in_job=(current_status == "job"),
                present_address=present_address,
                job_title=job_title if current_status == "job" else None,
                job_address=job_address if current_status == "job" else None,
                higher_study_uni_name=(
                    higher_study_uni_name if current_status == "study" else None
                ),
                higher_study_uni_address=(
                    higher_study_uni_address if current_status == "study" else None
                ),
                higher_study_field=(
                    higher_study_field if current_status == "study" else None
                ),
            )

        messages.success(
            request, "Account created successfully! Please wait for approval."
        )
        return redirect("login")

    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("signup")
    except Exception:
        logger.exception("Unexpected error while creating alumni account")
        messages.error(
            request,
            "We could not create your account. Please try again or contact support.",
        )
        return redirect("signup")


@login_required
def alumni_map(request):
    current_user = UserData.objects.filter(user=request.user).first()
    if not current_user or not current_user.account_is_approved:
        return redirect('/')

    south = request.GET.get('south')
    west = request.GET.get('west')
    north = request.GET.get('north')
    east = request.GET.get('east')
    search_query = request.GET.get('search', '').strip()

    messaging_only = request.GET.get("messaging") == "1"
    alumni_queryset = UserData.objects.filter(account_is_approved=True).select_related("user")
    if messaging_only:
        alumni_queryset = alumni_queryset.filter(user__is_active=True).exclude(user=request.user)

    # Filter by bounding box if provided
    if not messaging_only and all([south, west, north, east]):
        try:
            s_val = Decimal(south)
            w_val = Decimal(west)
            n_val = Decimal(north)
            e_val = Decimal(east)
            alumni_queryset = alumni_queryset.filter(
                lat__gte=s_val,
                lat__lte=n_val,
                lng__gte=w_val,
                lng__lte=e_val
            )
        except Exception:
            pass

    if search_query:
        alumni_queryset = alumni_queryset.filter(
            Q(roll_no__icontains=search_query) |
            Q(name__icontains=search_query) |
            Q(country__icontains=search_query) |
            Q(phone_number__icontains=search_query) |
            Q(state__icontains=search_query) |
            Q(city__icontains=search_query) |
            Q(batch__icontains=search_query) |
            Q(department__icontains=search_query) |
            Q(degree__icontains=search_query) |
            Q(email_id__icontains=search_query) |
            Q(present_address__icontains=search_query) |
            Q(job_title__icontains=search_query) |
            Q(job_address__icontains=search_query) |
            Q(higher_study_uni_name__icontains=search_query) |
            Q(higher_study_uni_address__icontains=search_query) |
            Q(higher_study_field__icontains=search_query)
        )

    # AJAX response for map-based query
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        alumni_data = [{
            'id': a.user.pk,
            'name': a.name,
            'batch': a.batch,
            'department': a.department,
            'job_title': a.job_title,
            'lat': a.lat,
            'lng': a.lng,
            'can_message': a.user.is_active and a.user_id != request.user.pk
        } for a in alumni_queryset]

        return JsonResponse({'alumni': alumni_data})

    # Regular HTML page render
    return render(request, 'alumni_map.html', {
        'alumni_list': alumni_queryset, 'messaging_only': messaging_only,
    })



@login_required
def guest_house_booking_request(request):
    current_user = UserData.objects.filter(user=request.user).first()
    if not current_user or not current_user.account_is_approved:
        return redirect('/')
    if request.method == 'POST':
        type_of_room = request.POST.get('type_of_room')
        reason_of_visit = request.POST.get('reason_of_visit')
        datetime_in = request.POST.get('datetime_in')
        datetime_out = request.POST.get('datetime_out')

        GuestHouseBookingRequest.objects.create(
            user=request.user,
            type_of_room=type_of_room,
            reason_of_visit=reason_of_visit,
            datetime_in=datetime_in,
            datetime_out=datetime_out
        )
        messages.success(request, 'Your guest house booking request has been submitted successfully.')
        return redirect('guest_house_booking')

    return render(request, 'guest_house_booking.html')

@login_required
def card_application_request(request):
    current_user = UserData.objects.filter(user=request.user).first()
    if not current_user or not current_user.account_is_approved:
        return redirect('/')
    context = {
        "name": current_user.name,
        "roll": current_user.roll_no,
        "department": current_user.department,
        "year": current_user.batch,
        "card_template_url": "https://raw.githubusercontent.com/Ojas1024/nitpyalumni_images/refs/heads/main/alumni%20id%202-Recovered_page-0001.jpg"
    }

    return render(request, 'card_application.html', context=context)

@login_required
def get_transcript_request(request):
    current_user = UserData.objects.filter(user=request.user).first()
    if not current_user or not current_user.account_is_approved:
        return redirect('/')
    if request.method == 'POST':
        GetTranscriptRequest.objects.create(
            user=request.user,
        )
        messages.success(request, 'Your transcript request has been submitted successfully.')
        return redirect('get_transcript')

    return render(request, 'get_transcript.html')

@require_http_methods(["GET", "POST"])
def auth_logout(request):
    # Only a CSRF-protected POST signs out; a GET logout lets any site sign
    # users out. Old links/bookmarks get a confirmation button instead.
    if request.method != "POST":
        if not request.user.is_authenticated:
            return redirect('login')
        return render(request, "logout_confirm.html")
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('login')

@login_required
@approved_alumni_required()
@require_http_methods(["GET", "POST"])
def contact_alumni(request, user_id):
    receiver = _chat_peer(request, user_id)
    try:
        if request.method == 'POST':
            subject = " ".join((request.POST.get('subject') or "").split())
            message = (request.POST.get('message') or "").strip()
            if not 1 <= len(subject) <= 150 or not 1 <= len(message) <= 5000:
                messages.error(request, "Please enter a subject (max 150 characters) and a message (max 5000 characters).")
                return redirect('alumni_map')
            # Each send uses the site's shared email quota and reputation.
            if not throttle.consume("contact-email", str(request.user.pk),
                                    settings.CONTACT_EMAIL_LIMIT_PER_USER_PER_DAY, 86400):
                messages.error(request, "You have reached today's limit for contact emails. Please try again tomorrow or use chat.")
                return redirect('alumni_map')

            # Render HTML email
            html_content = render_to_string('email/contact_email.html', {
                'subject': subject,
                'message': message,
                'sender': request.user
            })

            email = EmailMessage(
                subject=f"New Message: {subject}",
                body=html_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[receiver.email_id],
            )
            email.content_subtype = "html"
            email.send()
            messages.success(request, "Your Message is sent successfully")

            return redirect('alumni_map')
        return redirect(f'/chat/{receiver.user.id}/')
    except Exception:
        logger.exception("Contact email could not be sent")
        messages.error(request, "Your message could not be sent. Please try again later.")
        return redirect('/')

@login_required
def add_job_posting(request):
    current_user = UserData.objects.filter(user=request.user).first()
    if not current_user or not current_user.account_is_approved:
        return redirect('/')
    if request.method == 'POST':
        job_title = request.POST.get('job_title')
        job_company = request.POST.get('job_company')
        job_location = request.POST.get('job_location')

        JobPosting.objects.create(
            job_title=job_title,
            job_company=job_company,
            job_location=job_location,
            posted_by=request.user
        )
        messages.success(request, 'Your job is added successfully for review')
        return redirect('/')

    return render(request, 'add_job_posting.html')

@login_required
def all_jobs_view(request):
    query = request.GET.get('q', '')

    jobs = JobPosting.objects.filter(
        is_approved=True
    ).filter(
        Q(job_title__icontains=query) | 
        Q(job_company__icontains=query) | 
        Q(job_location__icontains=query)
    ).select_related('posted_by')\
     .prefetch_related(
        Prefetch('posted_by__userdata', queryset=UserData.objects.all())
     ).order_by('-id')

    paginator = Paginator(jobs, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'all_jobs.html', {'page_obj': page_obj, 'query': query})

from django import forms

class TalkForm(forms.ModelForm):
    class Meta:
        model = Talk
        fields = ['current_position', 'short_bio', 'topic', 'datetime', 'venue', 'extra_text']
        widgets = {
            'datetime': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

@login_required
def volunteer_talk_view(request):
    current_user = UserData.objects.filter(user=request.user).first()
    if not current_user or not current_user.account_is_approved:
        return redirect('/')
    if request.method == 'POST':
        form = TalkForm(request.POST)
        if form.is_valid():
            talk = form.save(commit=False)
            talk.user = request.user
            talk.save()
            messages.success(request, "You will be informed soon about the approval of this talk.")
            return redirect('volunteer_talk')
    else:
        form = TalkForm()
    return render(request, 'volunteer_talk.html', {'form': form})

@login_required
def all_talks_view(request):
    query = request.GET.get('q', '')

    talks = Talk.objects.select_related('user')\
        .filter(is_approved=True)\
        .filter(
            Q(topic__icontains=query) |
            Q(user__userdata__name__icontains=query) |
            Q(current_position__icontains=query) |
            Q(short_bio__icontains=query)
        )\
        .prefetch_related(
            Prefetch('user__userdata', queryset=UserData.objects.all())
        )\
        .order_by('-datetime')

    paginator = Paginator(talks, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'all_talks.html', {'page_obj': page_obj, 'query': query})

@login_required
def donate_book_view(request):
    current_user = UserData.objects.filter(user=request.user).first()
    if not current_user or not current_user.account_is_approved:
        return redirect('/')
    if request.method == 'POST':
        booktitle = request.POST.get('booktitle', '').strip()

        if not booktitle:
            messages.error(request, "Book title cannot be empty.")
        else:
            book = DonateBook(booktitle=booktitle, user=request.user)
            book.save()
            messages.success(request, "Thank you for your donation request. It will be reviewed shortly.")
            return redirect('/')

    return render(request, 'donate_book.html')

# Profile completion and edits share validation and preserve account ownership.
@login_required
@require_http_methods(["GET", "POST"])
def profile_view(request):
    with transaction.atomic():
        # Lock the parent account even when its profile does not exist yet.
        # Concurrent completion requests must not create or overwrite two profiles.
        account = User.objects.select_for_update().get(pk=request.user.pk)
        profile = UserData.objects.select_for_update().filter(user=account).first()
        is_new = profile is None
        if is_new and account.is_staff:
            return redirect('/admin/')
        if request.method == "POST" and not is_new and request.POST.get("profile_mode") == "create":
            messages.info(request, "Your alumni profile has already been submitted.")
            return redirect("profile")
        if is_new:
            profile = UserData(
                user=account, roll_no=account.username, email_id=account.email,
                name=account.get_full_name(), account_is_approved=False,
                is_eligible_to_vote=False,
            )
        form = AlumniProfileForm(request.POST if request.method == "POST" else None, instance=profile)
        if request.method == "POST":
            if is_new and request.POST.get("profile_mode") != "create":
                form.is_valid()
                form.add_error(None, "Please reload this page before completing your profile.")
            elif form.is_valid():
                form.save()
                messages.success(request, (
                    "Your alumni profile has been submitted and is pending administrator approval."
                    if is_new else "Your profile has been updated successfully."
                ))
                return redirect("profile")
    return render(request, "profile.html", {
        "form": form, "user_data": profile, "is_new_profile": is_new,
        "is_approved": profile.account_is_approved,
    })


# New messages use PostgreSQL. Legacy MongoDB is opt-in for history recovery.
_mongo_db = None


def get_chat_db():
    if settings.CHAT_BACKEND == "postgres":
        return None
    global _mongo_db
    if _mongo_db is not None:
        return _mongo_db
    mongo_uri = os.environ.get("MONGODB_URI", "")
    if not mongo_uri:
        raise PyMongoError("Legacy messaging configuration is unavailable")
    _mongo_db = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)["ChatDB"]
    return _mongo_db


def chat_backend_errors(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except (PyMongoError, DatabaseError):
            # Database exceptions may contain credentials/URIs; never expose them.
            logger.warning("Messaging database unavailable")
            return JsonResponse({"error": "Messaging is temporarily unavailable."}, status=503)
    return wrapper


def _chat_peer(request, user_id):
    try:
        peer_id = int(user_id)
    except (TypeError, ValueError):
        raise Http404
    if peer_id <= 0 or peer_id > 9223372036854775807 or peer_id == request.user.pk:
        raise Http404
    return get_object_or_404(
        UserData.objects.select_related("user"), user_id=peer_id,
        account_is_approved=True, user__is_active=True,
    )


def get_chat_key(uid1, uid2):
    # Retain the legacy storage key so existing conversations remain readable.
    # This is only an index hint. Authorization always checks both participants.
    h1 = hashlib.md5(uid1.encode()).hexdigest()
    h2 = hashlib.md5(uid2.encode()).hexdigest()
    return str(int(h1, 16) ^ int(h2, 16))


def _conversation_query(sender_id, recipient_id):
    return {
        "chat_key": get_chat_key(sender_id, recipient_id),
        "$or": [
            {"sender_id": sender_id, "receiver_id": recipient_id},
            {"sender_id": recipient_id, "receiver_id": sender_id},
        ],
    }


def _message_payload(message):
    # Do not return arbitrary MongoDB fields to the client.
    return {key: str(message["_id"]) if key == "_id" else message.get(key)
            for key in ("_id", "sender_id", "receiver_id", "text", "datetime_sent", "is_seen", "seen_time")}


def update_user_metadata(user_id, other_user_id):
    db = get_chat_db()
    result = db.UserMetaData.update_one(
        {"user_id": user_id, "chats.other_user_id": other_user_id},
        {"$set": {"chats.$.last_message_time": now()}},
    )
    if result.matched_count == 0:
        db.UserMetaData.update_one(
            {"user_id": user_id},
            {"$push": {"chats": {"other_user_id": other_user_id, "last_message_time": now()}}},
            upsert=True,
        )


def _chat_list(request, db):
    if db is None:
        return messaging.inbox(request.user)
    user_id = str(request.user.pk)
    metadata = db.UserMetaData.find_one({"user_id": user_id}) or {}
    chats = metadata.get("chats", [])
    # Treat legacy Mongo metadata as untrusted; identity comes from SQL.
    peer_ids = {int(c["other_user_id"]) for c in chats
                if isinstance(c.get("other_user_id"), str)
                and c["other_user_id"].isascii() and c["other_user_id"].isdigit()
                and len(c["other_user_id"]) <= 18}
    profiles = {p.user_id: p for p in UserData.objects.filter(
        user_id__in=peer_ids, account_is_approved=True, user__is_active=True,
    ).exclude(user=request.user)}
    result = []
    seen = set()
    for chat in sorted(chats, key=lambda c: str(c.get("last_message_time", "")), reverse=True):
        try:
            peer_id = int(chat.get("other_user_id", ""))
        except (ValueError, TypeError):
            continue
        if peer_id not in profiles or peer_id in seen:
            continue
        seen.add(peer_id)
        result.append({
            "other_user_id": str(peer_id), "name": profiles[peer_id].name,
            "last_message_time": chat.get("last_message_time"),
            "has_unseen": db.Chats.count_documents({
                **_conversation_query(user_id, str(peer_id)),
                "sender_id": str(peer_id), "receiver_id": user_id, "is_seen": False,
            }) > 0,
        })
    return result


@login_required
@approved_alumni_required(api=True)
@require_GET
@chat_backend_errors
def undread_dm(request):
    db = get_chat_db()
    if db is None:
        count = DirectMessage.objects.filter(
            receiver=request.user, is_seen=False, sender__is_active=True,
            sender__userdata__account_is_approved=True,
        ).exclude(sender=request.user).count()
        return JsonResponse({"count": count})
    approved_ids = [str(pk) for pk in UserData.objects.filter(
        account_is_approved=True, user__is_active=True,
    ).exclude(user=request.user).values_list("user_id", flat=True)]
    count = db.Chats.count_documents({
        "receiver_id": str(request.user.pk), "sender_id": {"$in": approved_ids}, "is_seen": False,
    })
    return JsonResponse({"count": count})


@login_required
@approved_alumni_required()
@require_GET
@chat_backend_errors
def chats(request):
    db = get_chat_db()
    return render(request, "chats.html", {
        "chats": _chat_list(request, db),
        "name": request.userdata.name,
    })


@login_required
@approved_alumni_required()
@require_GET
def chat_view(request, user_id):
    peer = _chat_peer(request, user_id)
    return render(request, "chat.html", {"other_user_id": str(peer.user_id), "rc": peer})


@login_required
@approved_alumni_required(api=True)
@require_GET
@chat_backend_errors
def load_messages(request, user_id):
    peer = _chat_peer(request, user_id)
    try:
        offset = int(request.GET.get("offset", 0))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid message offset."}, status=400)
    if not 0 <= offset <= 100000:
        return JsonResponse({"error": "Invalid message offset."}, status=400)
    db = get_chat_db()
    if db is None:
        rows = list(messaging.conversation(request.user.pk, peer.user_id)
                    .order_by("-datetime_sent", "-pk")[offset:offset + 20])
        if offset == 0:
            rows.reverse()
        return JsonResponse({"messages": [messaging.payload(row) for row in rows]})
    query = _conversation_query(str(request.user.pk), str(peer.user_id))
    rows = list(db.Chats.find(query).sort("datetime_sent", -1).skip(offset).limit(20))
    # Older pages are prepended by the UI, newest first; initial page oldest first.
    if offset == 0:
        rows.reverse()
    return JsonResponse({"messages": [_message_payload(row) for row in rows]})


@login_required
@approved_alumni_required(api=True)
@require_POST
@chat_backend_errors
def update_messages(request, user_id):
    peer = _chat_peer(request, user_id)
    db = get_chat_db()
    if db is None:
        with transaction.atomic():
            rows = list(DirectMessage.objects.select_for_update().filter(
                sender=peer.user, receiver=request.user, is_seen=False,
            ).order_by("datetime_sent", "pk")[:100])
            if rows:
                seen_time = now()
                DirectMessage.objects.filter(pk__in=[row.pk for row in rows]).update(
                    is_seen=True, seen_time=seen_time,
                )
                for row in rows:
                    row.is_seen, row.seen_time = True, seen_time
        return JsonResponse({"messages": [messaging.payload(row) for row in rows]})
    query = {**_conversation_query(str(request.user.pk), str(peer.user_id)),
             "sender_id": str(peer.user_id), "receiver_id": str(request.user.pk), "is_seen": False}
    rows = list(db.Chats.find(query).sort("datetime_sent", 1).limit(100))
    if rows:
        seen_time = now()
        db.Chats.update_many({**query, "_id": {"$in": [row["_id"] for row in rows]}},
                             {"$set": {"is_seen": True, "seen_time": seen_time}})
        for row in rows:
            row.update(is_seen=True, seen_time=seen_time)
    return JsonResponse({"messages": [_message_payload(row) for row in rows]})


@login_required
@approved_alumni_required(api=True)
@require_POST
@chat_backend_errors
def add_message(request, user_id):
    peer = _chat_peer(request, user_id)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
        return JsonResponse({"error": "Message must contain between 1 and 4000 characters."}, status=400)
    db = get_chat_db()
    if db is None:
        row = DirectMessage.objects.create(sender=request.user, receiver=peer.user, text=text.strip())
        return JsonResponse({"status": "success", "message": messaging.payload(row)})
    sender_id, recipient_id = str(request.user.pk), str(peer.user_id)
    message = {
        "chat_key": get_chat_key(sender_id, recipient_id),
        "sender_id": sender_id, "receiver_id": recipient_id, "text": text.strip(),
        "datetime_sent": now(), "is_seen": False, "seen_time": None,
    }
    message["_id"] = db.Chats.insert_one(message).inserted_id
    update_user_metadata(sender_id, recipient_id)
    update_user_metadata(recipient_id, sender_id)
    return JsonResponse({"status": "success", "message": _message_payload(message)})


@login_required
@approved_alumni_required(api=True)
@require_GET
@chat_backend_errors
def chats_partial(request):
    db = get_chat_db()
    return JsonResponse({"chats": _chat_list(request, db), "name": request.userdata.name})


def web_dev_team(req):
    return render(req, "web_dev_team.html")


# 20/06/2025

# views.py



def get_cf_manager():
    api_token = os.environ.get("CF_API_TOKEN", "")
    zone_id = os.environ.get("CF_ZONE_ID", "")
    if not api_token or not zone_id:
        return None
    return CloudflareDNSManager(zone_id, api_token)

RESERVED_SUBDOMAINS = {
    'www', 'admin', 'api', 'mail', 'smtp', 'pop', 'imap', 'ftp',
    'portal', 'root', 'static', 'assets', 'dev', 'test', 'help', 'support',
    'login', 'signup', 'auth', 'dashboard', 'status', 'healthz', 'cname'
}
SUBDOMAIN_REGEX = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

def validate_subdomain_and_content(name, record_type, content):
    name_clean = (name or '').strip().lower()
    if not SUBDOMAIN_REGEX.match(name_clean):
        return None, None, None, "Subdomain must be 1-63 lowercase alphanumeric characters and may contain hyphens."
    if name_clean in RESERVED_SUBDOMAINS:
        return None, None, None, f"'{name_clean}' is a reserved subdomain name."

    record_type_clean = (record_type or '').strip().upper()
    if record_type_clean not in {'A', 'AAAA', 'CNAME'}:
        return None, None, None, "Invalid record type. Must be A, AAAA, or CNAME."

    content_clean = (content or '').strip()
    if not content_clean:
        return None, None, None, "Content cannot be empty."

    if record_type_clean == 'A':
        try:
            ipaddress.IPv4Address(content_clean)
        except ValueError:
            return None, None, None, "Invalid IPv4 address for A record (e.g. 192.0.2.1)."
    elif record_type_clean == 'AAAA':
        try:
            ipaddress.IPv6Address(content_clean)
        except ValueError:
            return None, None, None, "Invalid IPv6 address for AAAA record (e.g. 2001:db8::1)."
    elif record_type_clean == 'CNAME':
        if not re.match(r'^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$', content_clean):
            return None, None, None, "Invalid target domain for CNAME record (e.g. yourname.github.io)."

    return name_clean, record_type_clean, content_clean, None

@login_required
def manage_website_view(request):
    """
    Shows current website info (if any) and handles creation, update, and deletion.
    Secured: Ensures user can only edit/delete THEIR OWN website.
    """
    user_data = UserData.objects.filter(user=request.user).first()
    if not user_data or not user_data.account_is_approved:
        return redirect('/')
    website = Website.objects.filter(user=user_data).first()
    cf_manager = get_cf_manager()
    if cf_manager is None:
        return render(request, "manage_website.html", {
            "dns_unavailable": True, "website": website, "user": user_data,
        })

    if request.method == "POST":
        action = request.POST.get("action")

        # Prevent tampering: only work on the logged-in user's website.
        website = Website.objects.filter(user=user_data).first()

        if action == "create":
            if website:
                return render(request, "manage_website.html", {
                    "error": "You already have a website.",
                    "website": website,
                    "user": user_data
                })
            name = request.POST.get("name")
            record_type = request.POST.get("record_type")
            content = request.POST.get("content")

            clean_name, clean_type, clean_content, val_err = validate_subdomain_and_content(name, record_type, content)
            if val_err:
                return render(request, "manage_website.html", {
                    "error": val_err,
                    "website": website,
                    "user": user_data
                })

            if Website.objects.filter(name=clean_name).exists():
                return render(request, "manage_website.html", {
                    "error": "Subdomain already exists.",
                    "website": website,
                    "user": user_data
                })

            cf_response = cf_manager.create_record(clean_type, clean_name, clean_content)
            if not cf_response.get("success"):
                err_msg = cf_response.get('errors', [{}])[0].get('message', 'Unknown DNS error')
                return render(request, "manage_website.html", {
                    "error": f"DNS Error: {err_msg}",
                    "website": website,
                    "user": user_data
                })

            Website.objects.create(user=user_data, name=clean_name, content=clean_content)
            return redirect("manage_website")

        elif action == "update":
            if not website:
                return render(request, "manage_website.html", {
                    "error": "You do not have a website to update.",
                    "website": website,
                    "user": user_data
                })

            new_name = request.POST.get("name")
            record_type = request.POST.get("record_type")
            new_content = request.POST.get("content")

            clean_name, clean_type, clean_content, val_err = validate_subdomain_and_content(new_name, record_type, new_content)
            if val_err:
                return render(request, "manage_website.html", {
                    "error": val_err,
                    "website": website,
                    "user": user_data
                })

            if clean_name != website.name and Website.objects.filter(name=clean_name).exists():
                return render(request, "manage_website.html", {
                    "error": "Subdomain already exists.",
                    "website": website,
                    "user": user_data
                })

            search = cf_manager.search_records(name=website.name + ".nitpyalumni.com")
            records = search.get("result", [])
            if records:
                record_id = records[0]["id"]
                cf_manager.delete_record(record_id)

            cf_response = cf_manager.create_record(clean_type, clean_name, clean_content)
            if not cf_response.get("success"):
                err_msg = cf_response.get('errors', [{}])[0].get('message', 'Unknown DNS error')
                return render(request, "manage_website.html", {
                    "error": f"DNS Error: {err_msg}",
                    "website": website,
                    "user": user_data
                })

            website.name = clean_name
            website.content = clean_content
            website.save()
            return redirect("manage_website")

        elif action == "delete":
            if not website:
                return render(request, "manage_website.html", {
                    "error": "You do not have a website to delete.",
                    "website": None,
                    "user": user_data
                })

            search = cf_manager.search_records(name=website.name + ".nitpyalumni.com")
            records = search.get("result", [])
            if records:
                record_id = records[0]["id"]
                cf_manager.delete_record(record_id)

            website.delete()
            return redirect("manage_website")

    current_record_type = 'A'
    if website and website.content:
        if ':' in website.content:
            current_record_type = 'AAAA'
        elif any(c.isalpha() for c in website.content):
            current_record_type = 'CNAME'
        else:
            current_record_type = 'A'

    return render(request, "manage_website.html", {
        "website": website,
        "user": user_data,
        "current_record_type": current_record_type
    })


# Custom Error Handlers
def custom_bad_request(request, exception=None):
    return render(request, 'error.html', {'error_message': 'Bad Request', 'error_code': 400}, status=400)

def custom_permission_denied(request, exception=None):
    return render(request, 'error.html', {'error_message': "You're not authorized", 'error_code': 403}, status=403)

def custom_page_not_found(request, exception=None):
    return render(request, 'error.html', {'error_message': 'Page Not Found', 'error_code': 404}, status=404)

def custom_server_error(request):
    return render(request, 'error.html', {'error_message': '500 Server Error', 'error_code': 500}, status=500)
