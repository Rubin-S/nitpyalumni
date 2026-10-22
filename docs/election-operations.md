# Running an alumni election

## Publishing and voting

1. Sign in to `/admin/` with an activated staff account that has election permissions.
   Create positions and a timeline; administrator dates use Asia/Kolkata. Voting
   must start in the future when publishing.
2. Review alumni approval and explicit voting eligibility. Nominations and voting
   require both flags and an active account. Staff status does not grant a vote;
   password recovery does not grant approval or eligibility.
3. Publish, invite nominations, and approve candidates before voting begins.
   Candidates must still be active, approved, and eligible at approval. Review
   notes are included in candidate notifications.
4. Check `/healthz`, backups, the mail queue, and the verified `DEFAULT_FROM_EMAIL`.

Once voting starts, the timeline, positions, candidate identities, manifestos,
and nomination status are frozen. Candidate names, roll numbers, departments, and
batches come from nomination snapshots; later profile edits do not change ballots
or results. Started election records and profiles with recorded ballots are
protected against deletion.

Eligibility is checked live rather than against a frozen roster. Account recovery
and administrator eligibility changes can affect access during voting. Each voter
may submit one ballot, skip positions, and must choose at least one candidate.
Confirmed ballots cannot be edited. Publish results explicitly after voting closes;
tallies remain hidden beforehand. Ties require a separate administrator decision.
Reopening an election is unsupported. Published turnout snapshots cannot be rewritten.

## Notification delivery

Notices and receipts use the persistent `ElectionMail` queue. Receipts contain no
candidate choices. Gunicorn workers drain the queue every 60 seconds using shared
database claims. `ELECTION_EMAIL_DAILY_LIMIT` defaults to 20 recipient attempts per
UTC day, resetting at 05:30 IST. Failed attempts consume capacity; other site and
provider mail also count toward the provider's allowance.

In `/admin/elections/electionmail/`:

- **Queued:** no delivery attempt yet.
- **Accepted:** the SMTP provider accepted the message; inbox delivery is unconfirmed.
- **Delivery uncertain:** a send may have occurred. Reconcile provider records before
  any manual retry; automatic retries are disabled to avoid duplicates.

Voting-open announcements are deduplicated per canonical account email and expire
when voting closes. Receipts take priority. The election action “Send queued election
notifications” and `python manage.py send_election_mail` respect the same quota.
Set the daily limit to `0` to pause all delivery, or set
`ELECTION_MAIL_WORKER_ENABLED=false` to disable automatic draining.

## Privacy and recovery

Ballots have no direct voter reference or timestamp, and individual choices are
excluded from receipts and exports. This does not provide cryptographic anonymity
against database operators, transaction logs, or timing inference. Restrict database
access and keep CSRF enabled.

Retain additive schema during code rollbacks. Reversing the outbox migration deletes
queued records; restoring an old database can overwrite current votes. Take and
verify private backups before maintenance.
