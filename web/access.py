"""Access rules shared by messaging pages and their JSON endpoints."""
from functools import wraps

from django.http import HttpResponseForbidden, JsonResponse

from web.models import UserData


def approved_alumni_required(*, api=False):
    """Staff status never substitutes for alumni approval in messaging."""
    def decorate(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            profile = UserData.objects.filter(
                user=request.user, account_is_approved=True, user__is_active=True,
            ).first()
            if profile is None:
                if api:
                    return JsonResponse({"error": "An approved alumni account is required."}, status=403)
                return HttpResponseForbidden("An approved alumni account is required.")
            request.userdata = profile
            return view(request, *args, **kwargs)
        return wrapper
    return decorate
