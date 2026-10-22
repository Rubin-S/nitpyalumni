# Security operations

## Deployment and backups

Keep database exports, logs, environment files, and credentials outside Git.
Before data maintenance, take a private database backup, test its restoration in
an isolated database, and record account, profile, nomination, and vote counts.
Back up legacy MongoDB separately when access is available. Temporary files are
not durable backups.

Deploy to `Rubin-S/nitpyalumni` using the verified `production` remote. This
checkout's `origin` belongs to a different owner. Normal builds must never import
datasets, restore backups, create accounts, or grant privileges.

Check `/healthz`, username/email and admin login, approved-member messaging,
pending-user access denial, and election counts after deployment. Retain additive
schema on code rollbacks: reversing message or election-mail migrations deletes
their stored data. Never restore an old database over current voting data.

## Account containment and recovery

First verify an independent administrator with a unique password and production
shell access. Use interactive `createsuperuser` if necessary; never put passwords
in command arguments, logs, email, chat, or source control.

```bash
python manage.py security_lockdown
```

The default dry run reports legacy-password and privileged account IDs without
passwords, hashes, or emails. Verify identities independently; a strong password
does not establish that an old privilege grant was legitimate.

```bash
python manage.py security_lockdown --apply
python manage.py security_lockdown --apply --revoke-user VERIFIED_ACCOUNT_ID
```

`--apply` disables legacy shared-password accounts, removes their staff/superuser
flags, assigns unusable passwords, and clears all database sessions. The optional,
repeatable `--revoke-user` applies the same containment to explicitly reviewed IDs.
Profiles, nominations, votes, and service requests remain intact. These commands
are maintenance operations, never build steps.

Recovery through the canonical mailbox reactivates existing accounts and preserves
current permissions; it does not restore revoked privileges. **An inactive flag
alone is not a permanent ban under this policy.** For inaccessible mailboxes or
duplicate canonical emails, verify identity before correcting the account or using
interactive `python manage.py changepassword USERNAME` and activating it in admin.
Remove obsolete `DJANGO_SUPERUSER_*` and `NAVEEN_RAJ_PASSWORD` service variables.

## Credentials and request limits

Revoke exposed Django, SMTP, MongoDB, and Cloudflare credentials at their providers.
Replacing application configuration does not revoke old credentials. Scope DNS
tokens to the required zone, restrict database access, review provider access logs,
and verify integrations after redeploying. Never use an exposed Django key in
`SECRET_KEY_FALLBACKS`.

For rotation of an uncompromised key, set the old key in `SECRET_KEY_FALLBACKS`,
set a new `SECRET_KEY`, and deploy. Remove the fallback after the session lifetime
(default two weeks). Compromised keys require immediate replacement without a
fallback, invalidating old sessions and reset links.

Defaults in `.env.example` include login failure limits (10/account and 50/IP per
15 minutes), signup limits (10/IP/hour), contact email limits (10/user/day), and
one-year HSTS for the exact host. Reset requests allow one/email/minute and
10/IP/hour. Limits use shared database counters with opaque HMAC keys.

On public Render services, client IP limits trust only the edge's
`CF-Connecting-IP`; absent that header, IP limits are skipped. Outside Render,
they use the socket address. Other proxy arrangements require an explicit review
of this boundary; arbitrary `X-Forwarded-For` is not trusted. See
[Render's edge architecture](https://render.com/articles/how-render-handles-ddos-attacks)
and [Cloudflare's header contract](https://developers.cloudflare.com/fundamentals/reference/http-headers/#cf-connecting-ip).

## Sensitive Git history

The repository data guard prevents known credential patterns and operational data
from being committed; it is not a comprehensive secret scanner. Enable GitHub
secret scanning and push protection where available.

Removing files from the current branch does not purge historical commits, PR refs,
caches, forks, or other clones. Use a private fresh clone and `git-filter-repo` to
clean published branches and tags, coordinate rewritten history with collaborators,
and verify remote heads before force-pushing. Never mirror-push this checkout: it
contains refs from a separate upstream repository. Old clones can reintroduce
sensitive history and should be replaced.

Request cached sensitive-view and PR-ref removal privately through GitHub Support.
Follow [GitHub's removal procedure](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository);
never include credentials or alumni records in a public issue.
