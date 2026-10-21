"""Small bounded queue drain; only started by Gunicorn after Django loads."""
import logging
from threading import Event, Thread

from django.conf import settings
from django.db import connections

logger = logging.getLogger(__name__)


def start():
    if settings.DEBUG or not settings.ELECTION_MAIL_WORKER_ENABLED:
        return None
    stop = Event()

    def run():
        from elections.notifications import deliver_pending
        while not stop.wait(60):
            try:
                deliver_pending(limit=5)
            except Exception:
                logger.error("Election mail worker paused this iteration; inspect queue and database health.")
            finally:
                # Connections are thread-local. Never touch a request's connection.
                connections.close_all()

    thread = Thread(target=run, name="election-mail", daemon=True)
    thread.start()
    logger.info("Election mail worker started; shared daily recipient cap: %s.", settings.ELECTION_EMAIL_DAILY_LIMIT)
    return stop, thread
