from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticate using either email or username (case-insensitive).
    Works for both the frontend login (/login/) and Django admin (/admin/login/).
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or not password:
            return None

        clean_username = username.strip()
        try:
            user = UserModel.objects.filter(
                Q(username__iexact=clean_username) | Q(email__iexact=clean_username)
            ).first()
            if not user:
                from web.models import UserData
                ud = UserData.objects.filter(
                    Q(roll_no__iexact=clean_username) | Q(email_id__iexact=clean_username)
                ).select_related("user").first()
                if ud and ud.user:
                    user = ud.user

            if user and user.check_password(password) and self.user_can_authenticate(user):
                return user
        except Exception:
            return None
        return None
