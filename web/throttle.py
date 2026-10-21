"""Database-backed fixed-window rate limits shared by all gunicorn workers.

Reuses the PasswordResetThrottle table (an opaque HMAC key -> counter), so no
schema migration is required. Keys never contain raw emails, usernames or IPs.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from web.models import PasswordResetThrottle

_SALT = "nitpyalumni-rate-limit"


def _key(scope, identity, window_seconds, now):
    window = int(now.timestamp()) // window_seconds
    return salted_hmac(_SALT, f"{scope}:{identity}:{window_seconds}:{window}").hexdigest()


def _expiry(now, window_seconds):
    return now + timedelta(seconds=window_seconds * 2)


def is_limited(scope, identity, maximum, window_seconds):
    """True if `identity` has already used `maximum` attempts in this window."""
    if maximum <= 0:
        return False
    now = timezone.now()
    bucket = PasswordResetThrottle.objects.filter(
        key=_key(scope, identity, window_seconds, now), expires_at__gte=now,
    ).first()
    return bucket is not None and bucket.attempts >= maximum


def hit(scope, identity, window_seconds):
    """Record one attempt; returns the new count for this window."""
    now = timezone.now()
    key = _key(scope, identity, window_seconds, now)
    with transaction.atomic():
        PasswordResetThrottle.objects.filter(expires_at__lt=now).delete()
        bucket, _ = PasswordResetThrottle.objects.get_or_create(
            key=key, defaults={"expires_at": _expiry(now, window_seconds)},
        )
        bucket = PasswordResetThrottle.objects.select_for_update().get(pk=bucket.pk)
        bucket.attempts += 1
        bucket.save(update_fields=["attempts"])
        return bucket.attempts


def consume(scope, identity, maximum, window_seconds):
    """Atomically count an attempt; False when the limit was already reached."""
    if maximum <= 0:
        return True
    now = timezone.now()
    key = _key(scope, identity, window_seconds, now)
    with transaction.atomic():
        PasswordResetThrottle.objects.filter(expires_at__lt=now).delete()
        bucket, _ = PasswordResetThrottle.objects.get_or_create(
            key=key, defaults={"expires_at": _expiry(now, window_seconds)},
        )
        bucket = PasswordResetThrottle.objects.select_for_update().get(pk=bucket.pk)
        if bucket.attempts >= maximum:
            return False
        bucket.attempts += 1
        bucket.save(update_fields=["attempts"])
        return True
