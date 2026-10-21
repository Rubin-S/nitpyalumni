# Running an alumni election

## Before publishing

1. Sign in to `/admin/` with an activated staff/superuser account. Create an election, positions and a timeline. All administrator dates use Asia/Kolkata. Date ordering is enforced in forms and the database. Voting must start in the future when publishing.
2. Review alumni approval and the explicit voting-eligibility flag. Voting and nominations require both flags plus an active login account. Password recovery reactivates the existing account without changing either flag. Staff status alone never grants a vote.
3. Publish the election and invite nominations. Review candidates before voting begins. The candidate must still be active, approved and eligible at approval. The nomination review note is included in the candidate notification.
4. Verify `/healthz`, backup availability, mail queue and sender configuration. Provider login (`EMAIL_HOST_USER`) is not the sender; `DEFAULT_FROM_EMAIL` must use a verified sender address.

## Integrity rules

- All election mutations acquire the election row lock before validating current state. Ballot submission also locks/reloads the auth account and alumni profile. The unique election/voter constraint and the transaction around voter record, choices and receipt prevent duplicate or partial ballots.
- Once voting starts, the published timeline, positions, candidate identities, manifestos and nomination status are frozen. Published turnout snapshots cannot be rewritten. Reopening a closed election is not supported; create a separate election instead.
- Each nomination captures the submitted candidate name, roll number, department and batch. Ballots and results use this immutable snapshot, so later alumni-profile edits cannot change candidate presentation or historical results. Administrators can inspect the submitted identity alongside the current profile.
- Admin bulk deletion and cascades cannot delete started election records. Voter profiles with recorded ballots are protected against deletion. Voting-eligibility bulk actions are recorded in Django's administrator history.
- Eligibility is checked live; there is no frozen voter roster. An otherwise eligible locked account can recover while voting is open. Explicit administrator eligibility changes take effect on subsequent requests. The result-publication snapshot records eligible active profiles at publication, with a denominator no smaller than turnout.
- A voter may skip positions but must select at least one candidate. A confirmed ballot cannot be edited. Ties are shown explicitly; the portal does not choose a tie-break winner automatically.
- Results are published explicitly by an administrator after voting closes. Unpublished results are hidden from alumni. Administrator tallies are unavailable until closure.

## Mail delivery and quota

- Nomination notices, candidate decisions, receipts and voting-open announcements use the durable `ElectionMail` outbox. A receipt contains no candidate selections. Records roll back with their associated mutation; SMTP occurs only after commit.
- Each Gunicorn worker starts a small daemon queue drain through the automatically loaded `gunicorn.conf.py`. Workers poll every60seconds and coordinate with row locks and `skip_locked`. No separate Render resource or paid worker is created. Pending messages survive process restarts.
- `ELECTION_EMAIL_DAILY_LIMIT` defaults to20 recipient attempts per UTC day across all web workers and elections, preserving capacity for recovery. A reserved attempt consumes capacity even if SMTP fails. The daily clock resets05:30IST. Other site mail and inbound mail also consume provider quota; the application cap is not proof of remaining provider allowance.
- Voting-open messages are queued once per canonical account email. The old reset/resend action is removed. Messages that remain queued when voting closes expire without sending. Receipts have priority over announcements.
- In `/admin/elections/electionmail/`, Queued means not yet attempted, Accepted means the SMTP provider accepted it (not proof of inbox delivery), and Delivery uncertain means an attempted send was not conclusively recorded. Uncertain messages are not retried automatically, avoiding duplicate sends after a timeout or process crash. An administrator must reconcile them with provider delivery records before deciding whether a manual retry is appropriate.
- Administrators can use the election action “Send queued election notifications” or `python manage.py send_election_mail`; both respect the same cap. A cap of0 pauses delivery without discarding queued messages. A worker can also be disabled with `ELECTION_MAIL_WORKER_ENABLED=false` while retaining the queue.

## Privacy and recovery

Vote rows have random IDs and no voter reference or timestamp. The portal does not display individual choices or include them in exports/receipts. This is application-level separation, **not cryptographic anonymity against database operators, transaction-log access or timing inference**. Restrict direct database access to trusted operators. Ballot pages are private and non-cacheable; keep CSRF enabled.

This release adds an outbox, a date-order constraint and stronger voter deletion protection. It deletes no accounts, profiles, ballots or messages. Do not reverse its migration once notifications exist: reverse migration would drop their queue. If a code rollback is required, retain the additive schema and verify compatibility. Do not restore an old database over current voting data.
