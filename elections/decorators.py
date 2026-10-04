from functools import wraps

from django.shortcuts import redirect

from web.models import UserData


def approved_alumni_required(view_func):
    """
    Allow only logged-in users with an approved alumni profile, or staff users
    in preview mode. Sets ``request.userdata`` (None for staff without UserData).
    Use together with (and after) @login_required.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        userdata = UserData.objects.filter(user=request.user).first()
        if not userdata or not userdata.account_is_approved:
            if request.user.is_staff:
                request.userdata = userdata
                return view_func(request, *args, **kwargs)
            return redirect("/")
        request.userdata = userdata
        return view_func(request, *args, **kwargs)

    return wrapper
