# Security remediation

## Application changes

- Removed the legacy account promotion and destructive CSV import scripts, including
  all build hooks and example provisioning environment variables. Normal builds
  install dependencies, collect static assets, and apply schema migrations only.
- Canonical Django usernames/emails are the only login identities. Ambiguous legacy
  identities fail closed. Editable contact emails never select an authentication
  account. The legacy shared passwords are rejected by the sole authentication
  backend, including Django admin; the fallback backend that bypassed this policy
  has been removed. Existing sessions for accounts still using a legacy password are
  rejected on their next request, before the explicit database containment step.
- Every messaging endpoint requires an active, approved alumni profile, including
  staff accounts. Peer endpoints also require a different active, approved recipient.
  Mongo queries check both participant IDs independently of the legacy chat hash.
  Existing messages remain readable without a data migration.
- Message-read updates use POST with CSRF protection. Message JSON, type, size,
  recipient IDs, and offsets are validated. Backend failures return controlled
  responses without connection strings. Message responses expose only display fields.
- User-authored text is rendered using DOM text nodes in chat, history, map markers,
  popups, and table rows. Failed message sends preserve the draft.
- Removed the tracked alumni CSV and server log; added ignore rules and a CI guard
  for tracked operational data, personal-data CSV headers, and the credential forms
  found in historical source. This guard is targeted prevention, not a comprehensive
  secret scanner. Enable GitHub secret scanning/push protection as well.

## Before production rollout

1. Take a private PostgreSQL backup and verify that it can be restored to an isolated
   database. Back up MongoDB separately. Record counts of users, profiles, nominations,
   voter records, and votes. Do not store exports or credentials in this repository.
2. Verify an independently provisioned administrator with a strong, unique password
   and access to the Render shell. Never reuse a bootstrap password. Use interactive
   `python manage.py createsuperuser` if a recovery administrator is needed; confirm
   existing users before choosing a new identity. Do not place passwords in command
   arguments, logs, chat, or source control.
3. Deploy the reviewed patch to the `Rubin-S/nitpyalumni` repository/service. The local
   checkout also has an `origin` pointing to a different owner's repository; use the
   verified `production` remote or the intended GitHub repository explicitly.
   Compute-plan fields are omitted so syncing this existing Blueprint retains the
   live web-service and database plans rather than applying stale Free-plan settings.
4. Check `/healthz`, canonical username/email and admin login, pending-user messaging
   denial, approved-member conversations, and election counts.

## Existing account and session containment

Run in the production application shell after deploying the patch:

```bash
python manage.py security_lockdown
```

This is a dry run. It reports account IDs with legacy passwords and all privileged
account IDs; it prints no passwords, hashes, emails, or message content. Checking
password hashes can take time. Confirm which administrators are legitimate through
an independent identity check. Strong passwords do not prove that privileges were
legitimately assigned by the old scripts.

Once recovery administrator access is verified:

```bash
python manage.py security_lockdown --apply
```

This disables accounts using legacy shared passwords, removes their staff/superuser
flags, gives them unusable passwords, and deletes **all database sessions** because
stored XSS could have affected any session. Profiles, nominations, votes, and service
requests are preserved. Sessions on the removed fallback authentication backend are
also no longer accepted. Re-running containment is safe.

For a separately reviewed account whose privileges were improperly assigned, add an
explicit ID (repeat for multiple accounts):

```bash
python manage.py security_lockdown --apply --revoke-user VERIFIED_ACCOUNT_ID
```

This also locks and demotes those explicitly selected accounts. Do not select IDs by
email/name heuristics. This command is not run during builds or migrations.

After configuring and verifying email delivery, users can recover at
`/password-reset/`, including inactive users with unusable passwords. Under the
approved recovery policy, possession of the canonical `User.email` mailbox and
successful submission of a one-hour, single-use reset link activates the existing
account. Requesting a link alone makes no account changes. Alumni approval and
current privilege flags remain unchanged; removed privileges are never restored.
An inactive flag alone therefore does not permanently ban an account: its owner
can reactivate through this flow. No accounts or profiles are deleted.

For users who cannot access their registered mailbox, verify identity before
administrator-assisted recovery using interactive
`python manage.py changepassword USERNAME` and activating the account in Django
admin. Grant only reviewed permissions. Do not send passwords by email or chat.

Remove obsolete `DJANGO_SUPERUSER_*` and `NAVEEN_RAJ_PASSWORD` environment variables
from the live service after containment; removing them from the Blueprint does not
prove the existing service environment has been cleaned.

## Credential rotation

Historical revisions contained literal Django, SMTP, MongoDB, and Cloudflare
credentials. Treat them as exposed; validity has not been tested. Rotate/revoke at
those providers and update the service environment through its secret controls.
For Cloudflare, use a token scoped to the needed zone and DNS operations. Rotate
MongoDB credentials and restrict access to the application. Rotate the SMTP password
through its mail administrator. Rotate the Django secret key; do not preserve an
exposed key as a fallback. Restart/redeploy and verify integration operation after
updating credentials. Review provider access logs for unexpected use.

## Git history and public copies

Deleting files at HEAD does not remove them from earlier public commits. Purge the
CSV/log paths, compiled Python caches, and historical credential literals from **all published branches,
tags, and relevant refs** using a fresh, private clone and `git-filter-repo` with
sensitive-data-removal support. Validate the cleaned object graph before pushing.
A local cleanup candidate is not a remote cleanup.

Coordinate the force-push with collaborators: commit hashes will change, signatures
may be lost, and old clones can reintroduce removed history. Verify remote heads
have not moved before replacing any refs. Do not mirror-push this checkout's refs:
it includes refs for a separate upstream repository. Re-clone collaborators' working
copies after the rewrite. The original local `.git` also retains the exposed history.

The upstream public repository and anyone else's clones may contain copies; this
project cannot remove those independently. After cleaning the project's published
refs, request GitHub Support's removal of cached sensitive views/PR refs where
applicable. Keep the request private; do not put the CSV, log, or credentials in a
public issue. Follow [GitHub's sensitive-data removal procedure](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

Private local copies of the removed CSV/log were preserved in a mode-0700 temporary
directory with mode-0600 files. Move any required copies into approved private
storage; temporary directories are not durable backups. Never commit them again.
