"""
URL configuration for project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from web import views
urlpatterns = [

    path('', views.index),
    path('vision_and_mission', views.vam),
    path('director_message', views.dm),
    path('signup/', views.signup_view, name='signup'),
    path('alumni-map/', views.alumni_map, name='alumni_map'),
    path('login/', views.login_view, name='login'),
     path('guest-house-booking/', views.guest_house_booking_request, name='guest_house_booking'),
    path('card-application/', views.card_application_request, name='card_application'),
    path('get-transcript/', views.get_transcript_request, name='get_transcript'),
    path('logout/', views.auth_logout, name='logout'),
    path('contact-alumni/<int:user_id>/', views.contact_alumni, name='contact_alumni'),
    path('add-job/', views.add_job_posting, name='add_job_posting'),
    path('all-jobs/', views.all_jobs_view, name='all_jobs'),
    path('volunteer-talk/', views.volunteer_talk_view, name='volunteer_talk'),
    path('all-talks', views.all_talks_view)
]
