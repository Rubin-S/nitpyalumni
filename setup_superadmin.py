import os
import sys
from pathlib import Path
from django.db.models import Q

# Setup Django if run as standalone script
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')
import django
django.setup()

from django.contrib.auth.models import User
from web.models import UserData


def setup_naveen_raj_superadmin():
    """
    Grants highest super admin access to Dr. Naveen Raj R.
    Works locally and in production (PostgreSQL on Render).
    """
    print("=" * 60)
    print("Configuring Dr. Naveen Raj R as Super Admin (Highest Access)...")
    print("=" * 60)

    # 1. Identify all matching accounts (by roll_no/username, official email, or dummy backup email)
    users = list(User.objects.filter(
        Q(username__iexact='ME15D2141') |
        Q(email__iexact='naveenraj.r@nitpy.ac.in') |
        Q(email__iexact='admin@xyx.com')
    ))

    target_user = None
    # Prefer existing ME15D2141 if present
    for u in users:
        if u.username.upper() == 'ME15D2141':
            target_user = u
            break
    # Or existing user with email naveenraj.r@nitpy.ac.in
    if not target_user:
        for u in users:
            if u.email.lower() == 'naveenraj.r@nitpy.ac.in':
                target_user = u
                break
    if not target_user and users:
        target_user = users[0]

    if not target_user:
        target_user = User.objects.create(
            username='ME15D2141',
            email='naveenraj.r@nitpy.ac.in',
            first_name='Dr. Naveen Raj',
            last_name='R',
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        custom_password = os.environ.get('NAVEEN_RAJ_PASSWORD', 'password123')
        target_user.set_password(custom_password)
        target_user.save()
        print(f"Created new Super Admin User: username={target_user.username}, email={target_user.email}")
    else:
        target_user.is_staff = True
        target_user.is_superuser = True
        target_user.is_active = True
        target_user.first_name = 'Dr. Naveen Raj'
        target_user.last_name = 'R'
        target_user.email = 'naveenraj.r@nitpy.ac.in'

        custom_password = os.environ.get('NAVEEN_RAJ_PASSWORD')
        if custom_password:
            target_user.set_password(custom_password)
            print("Updated password from NAVEEN_RAJ_PASSWORD environment variable.")
        elif not target_user.has_usable_password():
            target_user.set_password('password123')
            print("Set default password 'password123' as no usable password was found.")

        target_user.save()
        print(f"Updated Super Admin User: id={target_user.id}, username={target_user.username}, email={target_user.email}")

    # Ensure all other matching accounts are also promoted (e.g. if separate user was created)
    for u in users:
        if u.id != target_user.id:
            u.is_staff = True
            u.is_superuser = True
            u.is_active = True
            u.save()
            print(f"Promoted associated User: id={u.id}, username={u.username}, email={u.email} to super admin.")

    # 2. Update or create UserData profile for Dr. Naveen Raj
    ud = UserData.objects.filter(
        Q(user=target_user) | Q(roll_no__iexact='ME15D2141')
    ).first()

    if ud:
        ud.user = target_user
        ud.name = 'Dr. Naveen Raj R'
        ud.email_id = 'naveenraj.r@nitpy.ac.in'
        ud.phone_number = '7358455415'
        ud.account_is_approved = True
        ud.is_eligible_to_vote = True
        ud.save()
        print(f"Updated UserData Profile: id={ud.id}, roll_no={ud.roll_no}, name={ud.name}, approved=True, eligible_to_vote=True")
    else:
        ud = UserData.objects.create(
            user=target_user,
            roll_no='ME15D2141',
            name='Dr. Naveen Raj R',
            email_id='naveenraj.r@nitpy.ac.in',
            phone_number='7358455415',
            country='India',
            state='Tamil nadu',
            city='chennai',
            batch=2018,
            department='Civil Engineering',
            degree='B.Tech',
            account_is_approved=True,
            is_eligible_to_vote=True,
            present_address='chennai, india',
            linked_in='https://www.linkedin.com/in/navraj94/',
        )
        print(f"Created UserData Profile: id={ud.id}, roll_no={ud.roll_no}, name={ud.name}, approved=True, eligible_to_vote=True")

    print("Dr. Naveen Raj R super admin configuration complete!")
    print("=" * 60)


if __name__ == '__main__':
    setup_naveen_raj_superadmin()
