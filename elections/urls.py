from django.urls import path

from elections import views

app_name = "elections"

urlpatterns = [
    path("", views.election_list, name="election_list"),
    path("<int:election_id>/", views.election_detail, name="election_detail"),
    path("<int:election_id>/nominate/", views.nominate, name="nominate"),
    path("<int:election_id>/withdraw/", views.withdraw, name="withdraw"),
    path("<int:election_id>/vote/", views.ballot, name="ballot"),
    path("<int:election_id>/results/", views.results, name="results"),
]
