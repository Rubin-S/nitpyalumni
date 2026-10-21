"""Email ownership recovery for active and inactive local accounts."""
import logging
from ipaddress import ip_address
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.views import (
    INTERNAL_RESET_SESSION_TOKEN, PasswordResetConfirmView, PasswordResetView,
)
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.crypto import salted_hmac

from web.models import PasswordResetThrottle

logger = logging.getLogger(__name__)


def reset_client_ip(request):
    # Public Render traffic always traverses its Cloudflare edge. Cloudflare
    # overwrites this single-IP header; arbitrary X-Forwarded-For is not trusted.
    # Elsewhere, forwarded headers are ignored unless the deployment is adapted.
    address = request.META.get("REMOTE_ADDR", "")
    if settings.PASSWORD_RESET_TRUST_RENDER_PROXY:
        address = request.META.get("HTTP_CF_CONNECTING_IP", address)
    try:
        return str(ip_address(address))
    except ValueError:
        return "unknown"


def consume_reset_limit(email, remote_address):
    """Shared database limits: one email/minute and ten attempts/IP/hour.

    The address is resolved at the trusted proxy boundary. Keys are HMACs,
    not email/IP addresses.
    """
    now = timezone.now()
    minute = int(now.timestamp()) // 60
    hour = int(now.timestamp()) // 3600
    buckets = [
        (f"email:{email.casefold()}:{minute}", 1),
        (f"ip:{remote_address}:{hour}", 10),
    ]
    with transaction.atomic():
        PasswordResetThrottle.objects.filter(expires_at__lt=now).delete()
        allowed = True
        for raw_key, maximum in buckets:
            key = salted_hmac("password-recovery-throttle", raw_key).hexdigest()
            bucket, _ = PasswordResetThrottle.objects.get_or_create(
                key=key, defaults={"expires_at": now + timedelta(hours=2)},
            )
            bucket = PasswordResetThrottle.objects.select_for_update().get(pk=bucket.pk)
            if bucket.attempts >= maximum:
                allowed = False
            else:
                bucket.attempts += 1
                bucket.save(update_fields=["attempts"])
        return allowed


class AccountPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        # UserData contact fields are editable and cannot establish ownership.
        # Ambiguous canonical emails require administrator assistance.
        users = list(get_user_model().objects.filter(email__iexact=email)[:2])
        return users if len(users) == 1 else []

    def save(self, **kwargs):
        origin = urlsplit(settings.PASSWORD_RESET_ORIGIN)
        kwargs.update(domain_override=origin.netloc, use_https=True)
        return super().save(**kwargs)

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        subject = "".join(render_to_string(subject_template_name, context).splitlines())
        message = EmailMultiAlternatives(
            subject, render_to_string(email_template_name, context), from_email, [to_email],
        )
        try:
            message.send()
        except Exception:
            # Keep unknown, throttled, and delivery-failed requests identical.
            # SMTP exceptions can contain recipient addresses or credentials.
            logger.error("Password recovery email delivery failed; check mail configuration.")


class AccountPasswordResetView(PasswordResetView):
    form_class = AccountPasswordResetForm

    def form_valid(self, form):
        if not consume_reset_limit(form.cleaned_data["email"], reset_client_ip(self.request)):
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


class AccountPasswordResetConfirmView(PasswordResetConfirmView):
    def dispatch(self, *args, **kwargs):
        response = super().dispatch(*args, **kwargs)
        response["Referrer-Policy"] = "no-referrer"
        return response

    def form_valid(self, form):
        # Serialize redemption with password changes. Recheck the token under
        # lock, so two concurrent submissions cannot redeem it twice.
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=self.user.pk)
            token = self.request.session.get(INTERNAL_RESET_SESSION_TOKEN)
            if not self.token_generator.check_token(user, token):
                form.add_error(None, "This reset link has expired or already been used. Please request a new link.")
                return self.form_invalid(form)
            if get_user_model().objects.filter(email__iexact=user.email).exclude(pk=user.pk).exists():
                form.add_error(None, "This account needs administrator assistance to reset its password.")
                return self.form_invalid(form)
            form.user = user
            user.is_active = True
            # SetPasswordForm saves the same user with its new password.
            # Staff/superuser flags and alumni approval remain unchanged.
            return super().form_valid(form)
