from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
import re
from web.models import UserData, DonateBook
from .models import GuestHouseBookingRequest, CardApplicationRequest, GetTranscriptRequest
from django.contrib.auth import logout
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
from django.db.models import Q
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.timezone import now
import json, hashlib
from pymongo import MongoClient
from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from .models import Website, UserData
from web.helper.cf import CloudflareDNSManager
def index(request):
    if request.user.is_authenticated:
        user = UserData.objects.get(user=request.user)
        is_approved = user.account_is_approved
        return render(request, 'student_dash.html', context={"user":user, "is_approved":is_approved})
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
    current_user = UserData.objects.get(user=request.user)
    if not current_user.account_is_approved:
        return redirect('/')

    south = request.GET.get('south')
    west = request.GET.get('west')
    north = request.GET.get('north')
    east = request.GET.get('east')
    search_query = request.GET.get('search', '').strip()

    alumni_queryset = UserData.objects.all()

    # Full-text multi-field search


    # Filter by bounding box if provided
    if all([south, west, north, east]):
        alumni_queryset = alumni_queryset.filter(
            lat__gte=south,
            lat__lte=north,
            lng__gte=west,
            lng__lte=east,
            account_is_approved=True
        )
    if search_query:
        alumni_queryset = UserData.objects.all().filter(
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
    current_user = UserData.objects.get(user=request.user)
    if not current_user.account_is_approved:
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
    current_user = UserData.objects.get(user=request.user)
    if not current_user.account_is_approved:
        return redirect('/')
    context = {"name": current_user.name, "roll": current_user.roll_no, "department": current_user.department, "year": current_user.batch, "card_template_url": "https://raw.githubusercontent.com/Ojas1024/nitpyalumni_images/refs/heads/main/alumni%20id%202-Recovered_page-0001.jpg"}

    return render(request, 'card_application.html', context=context)

@login_required
def get_transcript_request(request):
    current_user = UserData.objects.get(user=request.user)
    if not current_user.account_is_approved:
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
    return redirect('login')  # or wherever you want to send them after logout

@login_required
def contact_alumni(request, user_id):
    current_user = UserData.objects.get(user=request.user)
    if not current_user.account_is_approved:
        return redirect('/')
    try:
        receiver = get_object_or_404(User, pk=user_id)

        receiver = get_object_or_404(UserData, user=receiver)
        
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

            return redirect('/alumni-map')  # Redirect to a success page after sending
        return redirect(f'/chat/{receiver.user.id}/')
    except Exception as e:
        return redirect('/')

from .models import JobPosting

@login_required
def add_job_posting(request):
    current_user = UserData.objects.get(user=request.user)
    if not current_user.account_is_approved:
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
        return redirect('/')  # redirect after submission

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


from .models import Talk
from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone

class TalkForm(forms.ModelForm):
    class Meta:
        model = Talk
        fields = ['current_position', 'short_bio', 'topic', 'datetime', 'venue', 'extra_text']
        widgets = {
            'datetime': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

@login_required
def volunteer_talk_view(request):
    current_user = UserData.objects.get(user=request.user)
    if not current_user.account_is_approved:
        return redirect('/')
    if request.method == 'POST':
        form = TalkForm(request.POST)
        if form.is_valid():
            talk = form.save(commit=False)
            talk.user = request.user
            talk.save()
            messages.success(request, "You will be informed soon about the approval of this talk.")
            return redirect('volunteer_talk')  # or redirect to a success page
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
    current_user = UserData.objects.get(user=request.user)
    if not current_user.account_is_approved:
        return redirect('/')
    if request.method == 'POST':
        booktitle = request.POST.get('booktitle', '').strip()

        if not booktitle:
            messages.error(request, "Book title cannot be empty.")
        else:
            book = DonateBook(booktitle=booktitle, user=request.user)
            book.save()
            messages.success(request, "Thank you for your donation request. It will be reviewed shortly.")
            return redirect('/home')

    return render(request, 'donate_book.html')




# Profile page addded
@login_required
def profile_view(request):
    user_data = UserData.objects.get(user=request.user)
    is_approved = user_data.account_is_approved
    if request.method == 'POST':
        # Update fields from form input
        user_data.name = request.POST['name']
        user_data.roll_no = request.POST['roll_no']
        user_data.phone_number = request.POST['phone_number']
        user_data.email_id = request.POST['email_id']
        user_data.country = request.POST['country']
        user_data.state = request.POST['state']
        user_data.city = request.POST['city']
        user_data.batch = request.POST['batch']
        user_data.degree = request.POST['degree']
        user_data.department = request.POST['department']
        user_data.present_address = request.POST['present_address']
        user_data.linkedin = request.POST['linkedin']
        user_data.facebook = request.POST['facebook']
        user_data.instagram = request.POST['instagram']
        user_data.current_status = request.POST['current_status']

        # Optional fields based on status
        if user_data.current_status == 'job':
            user_data.job_title = request.POST.get('job_title', '')
            user_data.job_address = request.POST.get('job_address', '')
            user_data.higher_study_uni_name = ''
            user_data.higher_study_uni_address = ''
            user_data.higher_study_field = ''
        elif user_data.current_status == 'study':
            user_data.higher_study_uni_name = request.POST.get('higher_study_uni_name', '')
            user_data.higher_study_uni_address = request.POST.get('higher_study_uni_address', '')
            user_data.higher_study_field = request.POST.get('higher_study_field', '')
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

    return render(request, 'profile.html', {
        'user_data': user_data,
        "is_approved": is_approved
    })





# CHAT FEATURE Added by Darshitha EE23B1033




client = MongoClient("mongodb+srv://chatbot:chatbot117@cluster0.lxwem4m.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client["ChatDB"]
# count number of unread DMs
def undread_dm(request):
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
        return JsonResponse({"count":unseen_count})
    return JsonResponse({"count":0})
# Chat Key Generator
def get_chat_key(uid1, uid2):
    h1 = hashlib.md5(uid1.encode()).hexdigest()
    h2 = hashlib.md5(uid2.encode()).hexdigest()
    return str(int(h1, 16) ^ int(h2, 16))

def update_user_metadata(user_id, other_user_id):
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
@csrf_exempt
@login_required
@require_POST
def add_message(request, user_id):
    data = json.loads(request.body)
    chat_key = get_chat_key(str(request.user.id), user_id)

    message = {
        "chat_key": chat_key,
        "sender_id": str(request.user.id),
        "receiver_id": user_id,
        "text": data["text"],
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



API_TOKEN = "ooU0aLRpMToQEF-rMEw-5f4qXPlfNaaJbZDX1wBV"
ZONE_ID = "0d6b245cd01a7763d0db34987ade66e1"

cf_manager = CloudflareDNSManager(ZONE_ID, API_TOKEN)

@login_required
def manage_website_view(request):
    """
    Shows current website info (if any) and handles creation, update, and deletion.
    Secured: Ensures user can only edit/delete THEIR OWN website.
    """
    user_data = request.user.userdata
    if not user_data.account_is_approved:
        return redirect('/')
    website = Website.objects.filter(user=user_data).first()

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

            if Website.objects.filter(name=name).exists():
                return render(request, "manage_website.html", {
                    "error": "Subdomain already exists.",
                    "website": website,
                    "user": user_data
                })

            cf_response = cf_manager.create_record(record_type, name, content)
            if not cf_response.get("success"):
                return render(request, "manage_website.html", {
                    "error": f"DNS Error: {cf_response['errors'][0]['message']}",
                    "website": website,
                    "user": user_data
                })

            Website.objects.create(user=user_data, name=name, content=content)
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

            if new_name != website.name and Website.objects.filter(name=new_name).exists():
                return render(request, "manage_website.html", {
                    "error": "Subdomain already exists.",
                    "website": website,
                    "user": user_data
                })

            search = cf_manager.search_records(name=website.name+".nitpyalumni.com")
            records = search.get("result", [])
            if records:
                record_id = records[0]["id"]
                cf_manager.delete_record(record_id)

            cf_response = cf_manager.create_record(record_type, new_name, new_content)
            if not cf_response.get("success"):
                return render(request, "manage_website.html", {
                    "error": f"DNS Error: {cf_response['errors'][0]['message']}",
                    "website": website,
                    "user": user_data
                })

            website.name = new_name
            website.content = new_content
            website.save()
            return redirect("manage_website")

        elif action == "delete":
            if not website:
                return render(request, "manage_website.html", {
                    "error": "You do not have a website to delete.",
                    "website": None,
                    "user": user_data
                })

            search = cf_manager.search_records(name=website.name+".nitpyalumni.com")
            records = search.get("result", [])
            if records:
                record_id = records[0]["id"]
                cf_manager.delete_record(record_id)

            website.delete()
            return redirect("manage_website")

    return render(request, "manage_website.html", {
        "website": website,
        "user": user_data
    })