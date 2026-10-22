"""Run the election mail queue in each Gunicorn worker."""


def post_worker_init(worker):
    from elections.mail_worker import start
    worker.election_mail_worker = start()


def worker_exit(server, worker):
    mail_worker = getattr(worker, "election_mail_worker", None)
    if mail_worker:
        stop, thread = mail_worker
        stop.set()
        thread.join(timeout=12)
