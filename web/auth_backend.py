from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q
from web.security import LEGACY_PASSWORDS, has_legacy_password


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticate using either email or username (case-insensitive).
    Works for both the frontend login (/login/) and Django admin (/admin/login/).
    """
    def get_user(self, user_id):
        user = super().get_user(user_id)
        if user is not None and has_legacy_password(user.password):
            return None
        return user

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or not password or password in LEGACY_PASSWORDS:
            return None

        clean_username = username.strip()
        # Profile contact fields are editable and are not login identities.
        # Fail closed on ambiguous legacy email/username collisions.
        matches = list(UserModel.objects.filter(
            Q(username__iexact=clean_username) | Q(email__iexact=clean_username)
        )[:2])
        if len(matches) != 1:
            # Preserve Django's expensive hash work for unknown identities.
            UserModel().set_password(password)
            return None
        user = matches[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
