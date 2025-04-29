from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from web.models import UserData
from .models import GuestHouseBookingRequest, CardApplicationRequest, GetTranscriptRequest
from django.contrib.auth import logout
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
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
    if request.method == 'POST':
        name = request.POST.get('name')
        roll_no = request.POST.get('roll_no')
        phone_number = request.POST.get('phone_number')
        email_id = request.POST.get('email_id')
        country = request.POST.get('country')
        state = request.POST.get('state')
        city = request.POST.get('city')
        batch = request.POST.get('batch')
        department = request.POST.get('department')
        present_address = request.POST.get('present_address')
        facebook = request.POST.get('facebook') or None
        instagram = request.POST.get('instagram') or None
        current_status = request.POST.get('current_status')
        job_title = request.POST.get('job_title') or None
        higher_study_uni_name = request.POST.get('higher_study_uni_name') or None
        higher_study_uni_address = request.POST.get('higher_study_uni_address') or None
        higher_study_field = request.POST.get('higher_study_field') or None
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return redirect('signup')

        if User.objects.filter(username=roll_no).exists():
            messages.error(request, "Roll number already registered.")
            return redirect('signup')

        if User.objects.filter(email=email_id).exists():
            messages.error(request, "Email already registered.")
            return redirect('signup')

        user = User.objects.create_user(
            username=roll_no,
            email=email_id,
            password=password1,
            first_name=name.split()[0],
            last_name=' '.join(name.split()[1:]) if len(name.split()) > 1 else ''
        )

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
            email_id=email_id,
            facebook=facebook,
            instagram=instagram,
            in_job=(current_status == 'job'),
            present_address=present_address,
            job_title=job_title if current_status == 'job' else None,
            higher_study_uni_name=higher_study_uni_name if current_status == 'study' else None,
            higher_study_uni_address=higher_study_uni_address if current_status == 'study' else None,
            higher_study_field=higher_study_field if current_status == 'study' else None
        )

        messages.success(request, "Account created successfully! Please wait for approval.")
        return redirect('login')

    return render(request, 'signup.html')
@login_required
def alumni_map(request):
    # Fetch query parameters
    country = request.GET.get('country', '')
    entries = int(request.GET.get('entries', 10))

    # Fetch data from the database
    alumni_queryset = UserData.objects.all()

    if country:
        alumni_queryset = alumni_queryset.filter(country=country)

    # Pagination logic
    paginator = Paginator(alumni_queryset, entries)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Pass data to the template
    return render(request, 'alumni_map.html', {
        'alumni_list': page_obj,
        'page_obj': page_obj
    })

@login_required
def guest_house_booking_request(request):
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
    try:
        receiver = get_object_or_404(User, pk=user_id)
        print(receiver)
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
        print(e)
        return redirect('/')