from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from django.db import connection


def healthz(_request):
    connection.ensure_connection()
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("elections/", include("elections.urls")),
    path("", include("web.urls")),
]

handler400 = 'web.views.custom_bad_request'
handler403 = 'web.views.custom_permission_denied'
handler404 = 'web.views.custom_page_not_found'
handler500 = 'web.views.custom_server_error'
