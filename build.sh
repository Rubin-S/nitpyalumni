#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ["DJANGO_SUPERUSER_USERNAME"]
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@nitpyalumni.com")
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]
user, created = User.objects.get_or_create(
    username=username,
    defaults={"email": email, "is_staff": True, "is_superuser": True},
)
user.email = email
user.is_staff = True
user.is_superuser = True
user.set_password(password)
user.save()
print("superuser ready")
PY
fi

if [ -f "backup_userdata.csv" ]; then
  python manage.py shell <<'PY'
from web.models import UserData
if UserData.objects.count() < 100:
    import load_backup_userdata
    load_backup_userdata.run_import()
PY
fi

python setup_superadmin.py

