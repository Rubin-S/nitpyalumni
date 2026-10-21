from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.conf import settings

from web import throttle
from web.security import LEGACY_PASSWORDS, has_legacy_password

LOGIN_ACCOUNT_SCOPE = "login-fail-account"
LOGIN_IP_SCOPE = "login-fail-ip"


def _client_ip(request):
    """Client IP for per-IP limits, or None when it cannot be trusted.

    On Render, REMOTE_ADDR is a shared proxy address; limiting on it would let
    one attacker lock out every user. Only Cloudflare's CF-Connecting-IP (set by
    Render's edge) identifies a client there; without it, skip the IP limit and
    rely on the per-account limit.
    """
    if request is None:
        return None
    if settings.PASSWORD_RESET_TRUST_RENDER_PROXY and not request.META.get("HTTP_CF_CONNECTING_IP"):
        return None
    from web.password_reset import reset_client_ip
    ip = reset_client_ip(request)
    return None if ip == "unknown" else ip


def login_is_locked(identity, ip):
    window = settings.LOGIN_FAILURE_WINDOW_SECONDS
    if throttle.is_limited(LOGIN_ACCOUNT_SCOPE, identity, settings.LOGIN_FAILURE_LIMIT_PER_ACCOUNT, window):
        return True
    return ip is not None and throttle.is_limited(
        LOGIN_IP_SCOPE, ip, settings.LOGIN_FAILURE_LIMIT_PER_IP, window,
    )


def record_login_failure(identity, ip):
    window = settings.LOGIN_FAILURE_WINDOW_SECONDS
    throttle.hit(LOGIN_ACCOUNT_SCOPE, identity, window)
    if ip is not None:
        throttle.hit(LOGIN_IP_SCOPE, ip, window)


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
        if not username or not password:
            return None

        clean_username = username.strip()
        # Brute-force protection for both /login/ and /admin/login/. While an
        # account or client IP is locked, even a correct password is refused,
        # so guessing cannot continue. Keys are HMACs, never raw identities.
        identity = clean_username.casefold()
        ip = _client_ip(request)
        if login_is_locked(identity, ip):
            if request is not None:
                request.login_throttled = True
            UserModel().set_password(password)
            return None
        if password in LEGACY_PASSWORDS:
            record_login_failure(identity, ip)
            return None
        # Profile contact fields are editable and are not login identities.
        # Fail closed on ambiguous legacy email/username collisions.
        matches = list(UserModel.objects.filter(
            Q(username__iexact=clean_username) | Q(email__iexact=clean_username)
        )[:2])
        if len(matches) != 1:
            # Preserve Django's expensive hash work for unknown identities.
            UserModel().set_password(password)
            record_login_failure(identity, ip)
            return None
        user = matches[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        record_login_failure(identity, ip)
        return None
