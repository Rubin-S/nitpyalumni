import json
import hashlib
import os
import re
import ipaddress
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
from django.db.models import Q, Prefetch
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.utils.timezone import now
from pymongo import MongoClient

from web.models import (
    UserData, DonateBook, JobPosting, Talk, Website,
    GuestHouseBookingRequest, CardApplicationRequest, GetTranscriptRequest
)
from web.helper.cf import CloudflareDNSManager
def index(request):
    if request.user.is_authenticated:
        user = UserData.objects.filter(user=request.user).first()
        if user is None:
            if request.user.is_staff:
                return redirect("/admin/")
            return render(request, "home.html")
        is_approved = user.account_is_approved
        return render(request, "student_dash.html", context={"user": user, "is_approved": is_approved})
    return render(request, "home.html")
def vam(request):
    return render(request, "vision_and_mission.html")
def dm(request):
    return render(request, "director_message.html")

def login_view(request):
    if request.user.is_authenticated:
        return redirect('/')
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        try:
            user = User.objects.get(email=email)
            user_auth = authenticate(username=user.username, password=password)

            if user_auth is not None:
                login(request, user_auth)
                return redirect('/')  # Redirect to home page or dashboard
            else:
                messages.error(request, "Invalid email or password. Please try again.")

        except User.DoesNotExist:
            messages.error(request, "No user found with this email address.")

    return render(request, 'login.html')
def signup_view(request):
    try:
        if request.user.is_authenticated:
            return redirect('/')

        if request.method == 'POST':
            # Get form data
            name = request.POST.get('name')
            roll_no = request.POST.get('roll_no', '').strip().upper()
            pattern = r'^[A-Z]{2}\d{2}[A-Z]{1}\d{4}$'
            if not re.match(pattern, roll_no):
                messages.error(request, "User not valid")
                return redirect('signup')
            phone_number = request.POST.get('phone_number')
            email_id = request.POST.get('email_id')
            country = request.POST.get('country')
            state = request.POST.get('state')
            city = request.POST.get('city')
            batch = request.POST.get('batch')
            degree = request.POST.get('degree')
            department = request.POST.get('department')
            present_address = request.POST.get('present_address')
            linked_id = request.POST.get('linkedin') or ""
            facebook = request.POST.get('facebook') or ""
            instagram = request.POST.get('instagram') or ""
            current_status = request.POST.get('current_status')
            job_title = request.POST.get('job_title') or ""
            job_address = request.POST.get('job_address') or ""
            higher_study_uni_name = request.POST.get('higher_study_uni_name') or ""
            higher_study_uni_address = request.POST.get('higher_study_uni_address') or ""
            higher_study_field = request.POST.get('higher_study_field') or ""
            password1 = request.POST.get('password1')
            password2 = request.POST.get('password2')

            # Password validation
            if password1 != password2:
                messages.error(request, "Passwords do not match.")
                return redirect('signup')

            # Check if user already exists
            if User.objects.filter(username=roll_no).exists():
                messages.error(request, "Roll number already registered.")
                return redirect('signup')

            if User.objects.filter(email=email_id).exists():
                messages.error(request, "Email already registered.")
                return redirect('signup')

            # Create user account
            user = User.objects.create_user(
                username=roll_no,
                email=email_id,
                password=password1,
                first_name=name.split()[0],
                last_name=' '.join(name.split()[1:]) if len(name.split()) > 1 else ''
            )

            # Create the UserData entry with the new fields
            user_data = UserData.objects.create(
                user=user,
                roll_no=roll_no,
                name=name,
                phone_number=phone_number,
                country=country,
                state=state,
                city=city,
                batch=batch,
                department=department,
                degree=degree,  # Added degree field
                email_id=email_id,
                linked_in=linked_id,  # LinkedIn URL
                facebook=facebook,  # Facebook URL
                instagram=instagram,  # Instagram URL
                in_job=(current_status == 'job'),
                present_address=present_address,
                job_title=job_title if current_status == 'job' else None,
                job_address=job_address if current_status == 'job' else None,
                higher_study_uni_name=higher_study_uni_name if current_status == 'study' else None,
                higher_study_uni_address=higher_study_uni_address if current_status == 'study' else None,
                higher_study_field=higher_study_field if current_status == 'study' else None
            )

            # Success message and redirection
            messages.success(request, "Account created successfully! Please wait for approval.")
            return redirect('login')

        return render(request, 'signup.html')

    except Exception as e:
        # Catch any exception and display an error message
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('/login')


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

    alumni_queryset = UserData.objects.filter(account_is_approved=True)

    # Filter by bounding box if provided
    if all([south, west, north, east]):
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
            'lng': a.lng
        } for a in alumni_queryset]

        return JsonResponse({'alumni': alumni_data})

    # Regular HTML page render
    return render(request, 'alumni_map.html', {
        'alumni_list': alumni_queryset
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

def auth_logout(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('login')

@login_required
def contact_alumni(request, user_id):
    current_user = UserData.objects.filter(user=request.user).first()
    if not current_user or not current_user.account_is_approved:
        return redirect('/')
    try:
        receiver_user = get_object_or_404(User, pk=user_id)
        receiver = get_object_or_404(UserData, user=receiver_user)
        
        if request.method == 'POST':
            subject = request.POST.get('subject')
            message = request.POST.get('message')

            # Render HTML email
            html_content = render_to_string('email/contact_email.html', {
                'subject': subject,
                'message': message,
                'sender': request.user
            })

            email = EmailMessage(
                subject=f"New Message: {subject}",
                body=html_content,
                from_email=settings.EMAIL_HOST_USER,
                to=[receiver.email_id],
            )
            email.content_subtype = "html"
            email.send()
            messages.success(request, "Your Message is sent successfully")

            return redirect('/alumni-map')
        return redirect(f'/chat/{receiver.user.id}/')
    except Exception:
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

# Profile page
@login_required
def profile_view(request):
    user_data = UserData.objects.filter(user=request.user).first()
    if not user_data:
        if request.user.is_staff:
            return redirect('/admin/')
        messages.error(request, "No alumni profile found for your account.")
        return redirect('/')

    is_approved = user_data.account_is_approved
    if request.method == 'POST':
        # Update fields from form input
        user_data.name = request.POST.get('name', '').strip()
        user_data.phone_number = request.POST.get('phone_number', '').strip()
        user_data.email_id = request.POST.get('email_id', '').strip()
        user_data.country = request.POST.get('country', '').strip()
        user_data.state = request.POST.get('state', '').strip()
        user_data.city = request.POST.get('city', '').strip()
        user_data.batch = request.POST.get('batch', user_data.batch)
        user_data.degree = request.POST.get('degree', user_data.degree)
        user_data.department = request.POST.get('department', user_data.department)
        user_data.present_address = request.POST.get('present_address', '').strip()
        user_data.linked_in = request.POST.get('linkedin', '').strip()
        user_data.facebook = request.POST.get('facebook', '').strip()
        user_data.instagram = request.POST.get('instagram', '').strip()

        current_status = request.POST.get('current_status', '')
        user_data.in_job = (current_status == 'job')

        # Optional fields based on status
        if current_status == 'job':
            user_data.job_title = request.POST.get('job_title', '').strip()
            user_data.job_address = request.POST.get('job_address', '').strip()
            user_data.higher_study_uni_name = ''
            user_data.higher_study_uni_address = ''
            user_data.higher_study_field = ''
        elif current_status == 'study':
            user_data.higher_study_uni_name = request.POST.get('higher_study_uni_name', '').strip()
            user_data.higher_study_uni_address = request.POST.get('higher_study_uni_address', '').strip()
            user_data.higher_study_field = request.POST.get('higher_study_field', '').strip()
            user_data.job_title = ''
            user_data.job_address = ''
        else:
            user_data.job_title = ''
            user_data.job_address = ''
            user_data.higher_study_uni_name = ''
            user_data.higher_study_uni_address = ''
            user_data.higher_study_field = ''

        user_data.save()
        messages.success(request, "Your profile has been updated successfully.")
        return redirect('profile')

    if user_data.in_job:
        current_status = 'job'
    elif user_data.higher_study_uni_name or user_data.higher_study_field:
        current_status = 'study'
    else:
        current_status = 'none'

    return render(request, 'profile.html', {
        'user_data': user_data,
        'is_approved': is_approved,
        'current_status': current_status
    })





# CHAT FEATURE Added by Darshitha EE23B1033




_mongo_db = None


def get_chat_db():
    global _mongo_db
    if _mongo_db is not None:
        return _mongo_db
    mongo_uri = os.environ.get("MONGODB_URI", "")
    if not mongo_uri:
        return None
    _mongo_db = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)["ChatDB"]
    return _mongo_db
# count number of unread DMs
@login_required
def undread_dm(request):
    db = get_chat_db()
    if db is None:
        return JsonResponse({"count": 0})
    user_id = str(request.user.id)
    total_unseen = db.Chats.count_documents({
        "receiver_id": user_id,
        "is_seen": False
    })
    return JsonResponse({"count": total_unseen})
# Chat Key Generator
def get_chat_key(uid1, uid2):
    h1 = hashlib.md5(uid1.encode()).hexdigest()
    h2 = hashlib.md5(uid2.encode()).hexdigest()
    return str(int(h1, 16) ^ int(h2, 16))

def update_user_metadata(user_id, other_user_id):
    db = get_chat_db()
    if db is None:
        return
    result = db.UserMetaData.update_one(
        {"user_id": user_id, "chats.other_user_id": other_user_id},
        {"$set": {"chats.$.last_message_time": now()}}
    )
    if result.matched_count == 0:
        db.UserMetaData.update_one(
            {"user_id": user_id},
            {"$push": {"chats": {
                "other_user_id": other_user_id,
                "last_message_time": now()
            }}},
            upsert=True
        )
# 1. /chats
@login_required
def chats(request):
    db = get_chat_db()
    if db is None:
        return render(request, "chats.html", {"chats": [], "name": request.user.username})
    user_id = str(request.user.id)
    metadata = db.UserMetaData.find_one({"user_id": user_id})
    chat_list = metadata.get("chats", []) if metadata else []

    # Sort chats by last_message_time
    chat_list.sort(key=lambda x: x["last_message_time"], reverse=True)

    for chat in chat_list:
        other_user_id = chat.get("other_user_id")
        try:
            other_user = User.objects.get(id=other_user_id)
            user_data = UserData.objects.get(user=other_user)
            chat["name"] = user_data.name
        except (User.DoesNotExist, UserData.DoesNotExist):
            chat["name"] = "Deleted Account"

        # Check if there are any unseen messages from other_user_id to current user
        chat_key = get_chat_key(user_id, other_user_id)
        unseen_count = db.Chats.count_documents({
            "chat_key": chat_key,
            "receiver_id": user_id,
            "sender_id": other_user_id,
            "is_seen": False
        })
        chat["has_unseen"] = (unseen_count > 0)

    try:
        u = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect("chats")

    reciever = UserData.objects.get(user=u)
    name = reciever.name

    return render(request, "chats.html", {"chats": chat_list, "name": name})

# 2. /chat/<user_id>
@login_required
def chat_view(request, user_id):
    if request.user.id == int(user_id):
        return redirect("chats")
    try:
        u = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect("chats")  # Assuming you named the URL pattern 'chats'
    reciever = UserData.objects.get(user=u)
    return render(request, "chat.html", {"other_user_id": user_id, "rc": reciever})

# 3. /chat/<user_id>/load
@login_required
def load_messages(request, user_id):
    db = get_chat_db()
    if db is None:
        return JsonResponse({"messages": []})
    offset = int(request.GET.get("offset", 0))
    chat_key = get_chat_key(str(request.user.id), user_id)

    messages = list(db.Chats.find({"chat_key": chat_key})
                    .sort("datetime_sent", -1)
                    .skip(offset)
                    .limit(20))

    for msg in messages:
        msg["_id"] = str(msg["_id"])
    
    if offset>=20:
        return JsonResponse({"messages": list((messages))})  # latest below

    return JsonResponse({"messages": list(reversed(messages))})  # latest below

# 4. /chat/<user_id>/update
@login_required
def update_messages(request, user_id):
    db = get_chat_db()
    if db is None:
        return JsonResponse({"messages": []})
    chat_key = get_chat_key(str(request.user.id), user_id)

    unseen_messages = list(db.Chats.find({
        "chat_key": chat_key,
        "receiver_id": str(request.user.id),
        "is_seen": False
    }))

    for msg in unseen_messages:
        db.Chats.update_one(
            {"_id": msg["_id"]},
            {"$set": {"is_seen": True, "seen_time": now()}}
        )
        msg["_id"] = str(msg["_id"])

    return JsonResponse({"messages": unseen_messages})

# 5. /chat/<user_id>/add_message
@login_required
@require_POST
def add_message(request, user_id):
    db = get_chat_db()
    if db is None:
        return JsonResponse({"status": "unavailable"}, status=503)
    if not User.objects.filter(id=user_id).exists():
        return JsonResponse({"status": "error", "message": "Recipient not found"}, status=404)
    data = json.loads(request.body)
    text = data.get("text", "").strip()
    if not text:
        return JsonResponse({"status": "error", "message": "Message text cannot be empty"}, status=400)

    chat_key = get_chat_key(str(request.user.id), user_id)

    message = {
        "chat_key": chat_key,
        "sender_id": str(request.user.id),
        "receiver_id": user_id,
        "text": text,
        "datetime_sent": now(),
        "is_seen": False,
        "seen_time": None
    }

    db.Chats.insert_one(message)

    update_user_metadata(str(request.user.id), user_id)
    update_user_metadata(user_id, str(request.user.id))

    return JsonResponse({"status": "success"})


@login_required
def chats_partial(request):
    db = get_chat_db()
    if db is None:
        return JsonResponse({"chats": [], "name": request.user.username})
    user_id = str(request.user.id)
    metadata = db.UserMetaData.find_one({"user_id": user_id})
    chat_list = metadata.get("chats", []) if metadata else []

    # Sort chats by last_message_time
    chat_list.sort(key=lambda x: x["last_message_time"], reverse=True)

    for chat in chat_list:
        other_user_id = chat.get("other_user_id")
        try:
            other_user = User.objects.get(id=other_user_id)
            user_data = UserData.objects.get(user=other_user)
            chat["name"] = user_data.name
        except (User.DoesNotExist, UserData.DoesNotExist):
            chat["name"] = "Deleted Account"

        # Check if there are any unseen messages from other_user_id to current user
        chat_key = get_chat_key(user_id, other_user_id)
        unseen_count = db.Chats.count_documents({
            "chat_key": chat_key,
            "receiver_id": user_id,
            "sender_id": other_user_id,
            "is_seen": False
        })
        chat["has_unseen"] = (unseen_count > 0)

    try:
        u = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect("chats")

    reciever = UserData.objects.get(user=u)
    name = reciever.name

    return JsonResponse({"chats": chat_list, "name": name})


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

    if request.method == "POST":
        if cf_manager is None:
            return render(request, "manage_website.html", {
                "error": "Website DNS is not configured on this deployment.",
                "website": website,
                "user": user_data,
            })
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