"""A lightweight durable-mail drain in the existing web-service workers.

No additional Render service is needed. Database claims and the shared daily
budget coordinate workers; process restarts never discard queued mail.
"""


def post_worker_init(worker):
    from elections.mail_worker import start
    worker.election_mail_worker = start()


def worker_exit(server, worker):
    mail_worker = getattr(worker, "election_mail_worker", None)
    if mail_worker:
        stop, thread = mail_worker
        stop.set()
        thread.join(timeout=12)
