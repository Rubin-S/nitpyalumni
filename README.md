# NITPY Alumni

Django alumni portal with approved-member services, messaging, and elections.

## Local development

Use Python 3.12 and a virtual environment. Install `requirements.txt`, copy
`.env.example` into your environment configuration, and set `DEBUG=true` locally
(the application reads environment variables; it does not automatically load `.env`).

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Administrators are created explicitly using Django's interactive `createsuperuser`
command. Builds never create accounts, reset passwords, import datasets, or grant
privileges based on names, roll numbers, or email addresses. Alumni approval and
voting eligibility are assigned separately in the admin panel.

`DATABASE_URL` selects PostgreSQL; without it, local development uses SQLite.
Production requires `SECRET_KEY` and `DATABASE_URL` when running on Render.
`MONGODB_URI` enables messaging. Both sender and recipient must have active,
approved alumni accounts; staff status alone does not grant messaging access.
`EMAIL_HOST`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD` configure SMTP.
`CF_API_TOKEN` and `CF_ZONE_ID` enable personal-subdomain management.

Login accepts the canonical Django username or email. Editable profile contact
emails are not login aliases. Previously provisioned shared passwords are denied.

### Password recovery

The login page links to `/password-reset/`. All accounts, including inactive
accounts and those with unusable passwords, can recover through their canonical
`User.email`. A successful reset activates the existing account; it preserves
profiles, alumni approval, voting eligibility, and current staff/superuser flags.
Duplicate canonical email addresses require administrator-assisted correction.
Links expire after one hour and stop working after a successful reset. Recovery
never signs a user in automatically. Database-backed limits allow one request per
email per minute and ten attempts per client IP per hour. On public Render
services (`RENDER=true`), the app uses the Cloudflare edge's `CF-Connecting-IP`;
outside Render, it uses the socket address and ignores forwarded headers.
Arbitrary `X-Forwarded-For` is never trusted. Other hosting/proxy arrangements
must explicitly adapt this boundary before deployment. See
[Render's edge architecture](https://render.com/articles/how-render-handles-ddos-attacks)
and [Cloudflare's header contract](https://developers.cloudflare.com/fundamentals/reference/http-headers/#cf-connecting-ip).

Configure working SMTP before directing users to recover. `DEFAULT_FROM_EMAIL`
is the verified sender address, separate from the SMTP username.
`PASSWORD_RESET_ORIGIN` is the canonical HTTPS site origin (default
`https://nitpyalumni.com`); reset emails never use a request's Host header.
The additive migration `0009_passwordresetthrottle` creates only a request-limit
table. It does not update or delete existing accounts or alumni records.

For Resend SMTP, verify a domain you control and configure these Render service
environment values (store the sending API key privately in Render):

```dotenv
EMAIL_HOST=smtp.resend.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=resend
EMAIL_HOST_PASSWORD=<sending API key>
DEFAULT_FROM_EMAIL=accounts@nitpyalumni.com
PASSWORD_RESET_ORIGIN=https://nitpyalumni.com
```

Use a sender on the domain actually verified in Resend. Keep the SMTP backend;
console/file backends expose reset links in logs or files and do not deliver mail.
After deploying and configuring email, request a link for an account whose
mailbox you own and verify inbox delivery before announcing availability.
Delivery errors are logged without addresses, links, or SMTP exception details;
the public confirmation intentionally does not reveal whether an account exists.

## Verification

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
python scripts/check_repository_data.py
npm ci --ignore-scripts
npx playwright install chromium
npm run test:browser
```

Browser tests execute the actual chat/map template scripts with hostile content in
Chromium, with all network requests blocked. CI also tests SQLite and PostgreSQL.

## Security remediation and private data

See [the security remediation runbook](docs/security-remediation.md) before rollout.
The `security_lockdown` command is read-only unless `--apply` is supplied. Keep
backups, database exports, logs, environment files, and credentials outside Git.
Never run a data restore as a build step. Use a tested private database backup and
an explicit maintenance operation for restores; normal deployments must preserve
alumni, nominations, ballots, and service requests.
