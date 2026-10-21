from django.core.management.base import BaseCommand
from elections.notifications import deliver_pending


class Command(BaseCommand):
    help = "Send queued election notifications within the shared daily election-mail cap."

    def handle(self, *args, **options):
        self.stdout.write(f"Mail service accepted {deliver_pending()} notification(s).")
