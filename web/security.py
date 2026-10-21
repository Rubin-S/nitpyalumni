"""Shared rules for credentials previously provisioned by deployment scripts."""
from functools import lru_cache

from django.contrib.auth.hashers import check_password, is_password_usable

# These are a denylist, never credentials to provision or accept.
LEGACY_PASSWORDS = frozenset({"password123", "adminpassword123"})


@lru_cache(maxsize=4096)
def has_legacy_password(encoded):
    # Cache by the full encoded hash, not user ID: changing a password cannot
    # retain an old decision. Never store raw passwords in the cache. This keeps
    # session checks from performing expensive PBKDF work on every request.
    return is_password_usable(encoded) and any(
        check_password(password, encoded) for password in LEGACY_PASSWORDS
    )


class LegacyPasswordValidator:
    def validate(self, password, user=None):
        from django.core.exceptions import ValidationError
        if password in LEGACY_PASSWORDS:
            raise ValidationError("This password was used by a legacy account setup. Choose a unique password.", code="legacy_password")

    def get_help_text(self):
        return "Do not reuse a legacy account setup password."
