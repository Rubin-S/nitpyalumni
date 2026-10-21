"""Contain credentials from the removed legacy account bootstrap scripts."""
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from web.security import has_legacy_password


class Command(BaseCommand):
    help = "Audit legacy passwords and privileged accounts; --apply locks affected accounts and clears sessions."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply containment; default is read-only.")
        parser.add_argument("--revoke-user", type=int, action="append", default=[], help="Also lock an explicitly reviewed user ID (repeatable).")

    def handle(self, *args, **options):
        User = get_user_model()
        revoke_ids = set(options["revoke_user"])
        if revoke_ids - set(User.objects.filter(pk__in=revoke_ids).values_list("pk", flat=True)):
            raise CommandError("An explicitly selected user ID does not exist; no changes made.")
        with transaction.atomic():
            users = User.objects.all().order_by("pk")
            if options["apply"]:
                users = users.select_for_update()
            affected = []
            privileged = []
            for user in users.iterator():
                if user.is_staff or user.is_superuser:
                    privileged.append(user.pk)
                # Use the hasher without a setter: even a dry run must not
                # upgrade hashes or mutate credentials in the database.
                legacy_password = has_legacy_password(user.password)
                if legacy_password or user.pk in revoke_ids:
                    affected.append(user.pk)
                    if options["apply"]:
                        user.set_unusable_password()
                        user.is_active = user.is_staff = user.is_superuser = False
                        user.save(update_fields=["password", "is_active", "is_staff", "is_superuser"])
            self.stdout.write(f"Review privileged account IDs: {privileged}")
            self.stdout.write(f"Accounts requiring containment: {affected}")
            if options["apply"]:
                # All sessions may have been exposed to stored XSS, even for
                # accounts whose passwords are strong.
                Session.objects.all().delete()
                self.stdout.write(f"Locked {len(affected)} accounts; invalidated all database sessions. No alumni/election data deleted.")
            else:
                self.stdout.write("DRY RUN: no changes made. Verify administrator recovery access before --apply.")
