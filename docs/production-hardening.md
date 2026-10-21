# Production hardening (October 2026)

No schema migrations, no data changes, no password-hasher change and no
SECRET_KEY change. Every new setting has a safe default, so this can be
deployed before any environment variable is added.

## What changed

- **Dependencies:** Django 5.2 -> 5.2.18 and patched requests, urllib3,
  sqlparse, pymongo, idna, certifi (pip-audit: 149 known vulnerabilities -> 0).
  Pillow was removed; nothing imports it and there are no image fields.
- **Login brute force:** failed sign-ins are limited per account (10 / 15 min)
  and per client IP (50 / 15 min) for both `/login/` and `/admin/login/`. While
  locked, even the correct password is refused. Counters reuse the existing
  `PasswordResetThrottle` table with HMAC keys (no raw emails/IPs stored). On
  Render, only Cloudflare's `CF-Connecting-IP` is trusted; without it the IP
  limit is skipped so the shared proxy address can never lock everyone out.
- **Sign-up** limited to 10 attempts per IP per hour; **contact-alumni emails**
  limited to 10 per user per day (protects the shared Resend quota/reputation).
- **Input validation** on sign-up and profile edit: http(s)-only social links
  (blocks `javascript:` URLs), email format, batch range, and column lengths
  (previously an over-long value or non-numeric batch caused a 500).
- **Logout** now requires a CSRF-protected POST (GET shows a confirm button).
- **CSRF_TRUSTED_ORIGINS** no longer trusts every `*.onrender.com` app; the
  service's own Render hostname is still added automatically.
- **Headers:** HSTS (1 year, exact host only, no preload), a non-breaking CSP
  (`object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'`),
  Permissions-Policy, and explicit cookie/referrer/frame settings.
- **CDN assets** pinned with Subresource Integrity; Leaflet was loaded from an
  unversioned "latest" URL and is now pinned to 1.9.4 (the version it resolved to).
- **Admin CSV exports** neutralise spreadsheet formulas (CSV injection).
- **Logging:** errors and 500 tracebacks now reach Render logs; removed prints
  that could leak a geocoding API key or Cloudflare responses; outbound
  Cloudflare calls have timeouts. Removed unused `web/m1.py`.

## Optional environment variables

| Name | Default | Purpose |
| --- | --- | --- |
| `SECRET_KEY_FALLBACKS` | empty | Previous key(s) during a graceful SECRET_KEY rotation |
| `SECURE_HSTS_SECONDS` | `31536000` | Set `0` to disable HSTS |
| `LOGIN_FAILURE_LIMIT_PER_ACCOUNT` / `_PER_IP` / `LOGIN_FAILURE_WINDOW_SECONDS` | 10 / 50 / 900 | Brute-force limits |
| `SIGNUP_LIMIT_PER_IP_PER_HOUR` | 10 | Sign-up limit |
| `CONTACT_EMAIL_LIMIT_PER_USER_PER_DAY` | 10 | Contact email limit |
| `LOG_LEVEL` | `INFO` | Root log level |

## Graceful SECRET_KEY rotation (no mass logout)

1. Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
2. In Render, set `SECRET_KEY_FALLBACKS` to the **current** key and
   `SECRET_KEY` to the new one, then deploy. Sessions and reset links keep
   working and are re-signed with the new key as users return.
3. After ~2 weeks (the session lifetime), delete `SECRET_KEY_FALLBACKS`.
   Users who have not visited since then must sign in again.

If the current key is known to be leaked, skip the fallback: everyone is signed
out once, which is the safe trade-off.

## Profile completion and PostgreSQL messaging

Authenticated accounts without an alumni profile can now complete `/profile/`.
The profile remains linked to the existing account and roll number and starts
pending administrator approval. Password recovery does not grant approval or
staff/voting privileges. Existing profiles and approval flags are preserved.

`CHAT_BACKEND=postgres` is the default for new DMs. Migration
`0010_direct_message_storage` adds only a message table and indexes; it does not
modify accounts, profiles, or the original MongoDB database. Old MongoDB history
has not been imported and remains unavailable until its owner/access is recovered.
The legacy Mongo code remains behind explicit `CHAT_BACKEND=mongo` for controlled
recovery; switching storage back does not merge the two histories.

On a code rollback, retain the message table. Do not reverse migration 0010 after
new messages have been stored, because reversal drops that table. Normal builds
apply the additive migration before starting the new application.
