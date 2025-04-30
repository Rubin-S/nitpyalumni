from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
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
            roll_no = request.POST.get('roll_no')
            phone_number = request.POST.get('phone_number')
            email_id = request.POST.get('email_id')
            country = request.POST.get('country')
            state = request.POST.get('state')
            city = request.POST.get('city')
            batch = request.POST.get('batch')
            degree = request.POST.get('degree')
            department = request.POST.get('department')
            present_address = request.POST.get('present_address')
            linked_id = request.POST.get('linkedin') or None
            facebook = request.POST.get('facebook') or None
            instagram = request.POST.get('instagram') or None
            current_status = request.POST.get('current_status')
            job_title = request.POST.get('job_title') or None
            job_address = request.POST.get('job_address') or None
            higher_study_uni_name = request.POST.get('higher_study_uni_name') or None
            higher_study_uni_address = request.POST.get('higher_study_uni_address') or None
            higher_study_field = request.POST.get('higher_study_field') or None
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
            lng__lte=east
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
        print(alumni_queryset)

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
    if request.method == 'POST':
        reason = request.POST.get('reason')
        utr_transaction_number = request.POST.get('utr_transaction_number')

        CardApplicationRequest.objects.create(
            user=request.user,
            reason=reason,
            utr_transaction_number=utr_transaction_number
        )
        messages.success(request, 'Your card application request has been submitted successfully.')
        return redirect('card_application')

    return render(request, 'card_application.html')

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
        return render(request, 'contact_alumni.html', {'receiver': receiver})
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
            return redirect('/donate-book/')

    return render(request, 'donate_book.html')
