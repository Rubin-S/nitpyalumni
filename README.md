# NITPY Alumni

Django alumni portal with approved-member services, messaging, and elections.

## Development

Use Python 3.12 and a virtual environment. Install `requirements.txt` and configure
variables from `.env.example`. The application reads the environment directly;
it does not load `.env` files. Set `DEBUG=true` locally.

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

`DATABASE_URL` selects PostgreSQL; local development otherwise uses SQLite.
Render production requires `SECRET_KEY` and `DATABASE_URL`. Builds install
dependencies, collect static assets, and migrate the schema. Account creation,
alumni approval, and voting eligibility require explicit administrator actions.

## Accounts and messaging

Login accepts the Django username or canonical `User.email`; editable profile
contact emails are not login aliases. Legacy shared passwords are rejected.
Accounts without a profile can complete `/profile/`, pending administrator approval.

`CHAT_BACKEND=postgres` stores new DMs in the application database. Both participants
must have active, approved alumni accounts; staff status alone does not grant
access. `CHAT_BACKEND=mongo` and `MONGODB_URI` select legacy storage for controlled
recovery. Switching backends does not import or merge old conversations.

Optional integrations use `GEOCODING_API_KEY` for profile locations and
`CF_API_TOKEN` / `CF_ZONE_ID` for personal-subdomain management. Configure DNS
credentials only after verifying ownership of the authoritative zone.

## Password recovery

`/password-reset/` supports existing accounts, including inactive accounts and
unusable passwords. A successful reset activates the account while preserving
its profile, approval, voting eligibility, and current staff/superuser flags.
Duplicate canonical emails require administrator correction. Links expire after
one hour, are single-use, and do not sign the user in automatically.

Configure SMTP and verify delivery to a mailbox you own before inviting users.
`DEFAULT_FROM_EMAIL` must be a verified sender, separate from the SMTP username.
For Resend SMTP:

```dotenv
EMAIL_HOST=smtp.resend.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=resend
EMAIL_HOST_PASSWORD=<sending API key>
DEFAULT_FROM_EMAIL=accounts@nitpyalumni.com
PASSWORD_RESET_ORIGIN=https://www.nitpyalumni.com
```

Store credentials privately in the service environment. `PASSWORD_RESET_ORIGIN`
controls link origins; emails never use the request Host header. Console/file
email backends expose reset links and do not deliver mail. Public reset responses
conceal account existence, and delivery errors omit addresses and tokens.

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

CI runs SQLite, PostgreSQL, and browser tests for hostile user content and login
submission behavior.

See [security operations](docs/security-remediation.md) for containment, credential
rotation, and backups, and [election operations](docs/election-operations.md) for
publishing elections and managing notification delivery.
