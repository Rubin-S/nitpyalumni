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
