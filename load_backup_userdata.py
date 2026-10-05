import csv
import os
import sys
from decimal import Decimal

from pathlib import Path

# Setup Django
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')

import django
django.setup()

from django.db import transaction, connection
from django.contrib.auth.models import User
from web.models import UserData
from elections.models import Election, Position, Nomination, Vote, VoterRecord


def clean_val(val):
    if val is None:
        return None
    val = val.strip()
    return val if val else None


def run_import():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, 'backup_userdata.csv')
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} does not exist!")
        return

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Loaded {len(rows)} rows from {csv_path}")

    with transaction.atomic():
        # 1. Clean up demo votes and dummy nominations
        print("Cleaning up old demo votes, voter records, and dummy nominations...")
        Vote.objects.all().delete()
        VoterRecord.objects.all().delete()
        Nomination.objects.all().delete()

        # 2. Remove dummy users if any exist
        dummy_rolls = ['CS20B1001', 'EC20B1002', 'ME20B1003', 'CE20B1004', 'EE20B1005']
        UserData.objects.filter(roll_no__in=dummy_rolls).delete()
        User.objects.filter(username__in=dummy_rolls).delete()

        # Also remove any leftover UserData to avoid primary key conflicts
        UserData.objects.all().delete()

        userdata_to_create = []
        created_users = 0
        updated_users = 0

        for r in rows:
            rec_id = int(r['id'])
            username = r['user'].strip()
            roll_no = r['roll_no'].strip()
            name = r['name'].strip()
            email_id = r['email_id'].strip().lower()

            # Handle auth User
            if username == 'admin':
                user = User.objects.filter(username='admin').first()
                if not user:
                    user = User.objects.create_superuser('admin', email_id, 'adminpassword123')
                    created_users += 1
                else:
                    user.email = email_id
                    user.save(update_fields=['email'])
                    updated_users += 1
            else:
                user = User.objects.filter(username=username).first()
                name_parts = name.split()
                first_name = name_parts[0] if name_parts else ''
                last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
                is_naveen_raj = (
                    username.upper() == 'ME15D2141' or
                    email_id in ('naveenraj.r@nitpy.ac.in', 'admin@xyx.com')
                )

                if not user:
                    user = User(
                        username=username,
                        email=email_id,
                        first_name=first_name,
                        last_name=last_name,
                        is_active=True,
                        is_staff=is_naveen_raj,
                        is_superuser=is_naveen_raj,
                    )
                    user.set_password('password123')
                    user.save()
                    created_users += 1
                else:
                    user.email = email_id
                    user.first_name = first_name
                    user.last_name = last_name
                    if is_naveen_raj:
                        user.is_staff = True
                        user.is_superuser = True
                    user.save(update_fields=['email', 'first_name', 'last_name', 'is_staff', 'is_superuser'] if is_naveen_raj else ['email', 'first_name', 'last_name'])
                    updated_users += 1

            # Prepare UserData instance
            lat_str = clean_val(r.get('lat'))
            lng_str = clean_val(r.get('lng'))
            lat = Decimal(lat_str) if lat_str else Decimal("10.9254")
            lng = Decimal(lng_str) if lng_str else Decimal("79.8380")

            ud = UserData(
                id=rec_id,
                user=user,
                account_is_approved=(r.get('account_is_approved', 'True').strip().lower() in ('true', '1')),
                is_eligible_to_vote=True,
                roll_no=roll_no,
                name=name,
                phone_number=r.get('phone_number', '').strip(),
                country=r.get('country', '').strip(),
                state=r.get('state', '').strip(),
                city=r.get('city', '').strip(),
                batch=int(r.get('batch', 2020)),
                department=r.get('department', '').strip(),
                degree=r.get('degree', '').strip(),
                email_id=email_id,
                linked_in=clean_val(r.get('linked_in')),
                facebook=clean_val(r.get('facebook')),
                instagram=clean_val(r.get('instagram')),
                in_job=(r.get('in_job', 'False').strip().lower() in ('true', '1')),
                present_address=r.get('present_address', '').strip(),
                job_title=clean_val(r.get('job_title')),
                job_address=clean_val(r.get('job_address')),
                higher_study_uni_name=clean_val(r.get('higher_study_uni_name')),
                higher_study_uni_address=clean_val(r.get('higher_study_uni_address')),
                higher_study_field=clean_val(r.get('higher_study_field')),
                lat=lat,
                lng=lng,
            )
            userdata_to_create.append(ud)

        print(f"Bulk creating {len(userdata_to_create)} UserData records...")
        UserData.objects.bulk_create(userdata_to_create)

        # Update database autoincrement sequence
        if connection.vendor == 'sqlite':
            with connection.cursor() as cursor:
                cursor.execute("SELECT MAX(id) FROM web_userdata")
                max_id = cursor.fetchone()[0] or 1
                cursor.execute("UPDATE sqlite_sequence SET seq = %s WHERE name = 'web_userdata'", [max_id])
                if cursor.rowcount == 0:
                    cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('web_userdata', %s)", [max_id])
        elif connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SELECT setval(pg_get_serial_sequence('web_userdata', 'id'), coalesce(max(id), 1)) FROM web_userdata")

        # Re-seed demo election nominations with real alumni if elections exist
        live_election = Election.objects.filter(is_published=True).order_by('id').first()
        if live_election:
            pres_pos = live_election.positions.filter(title="President").first()
            sec_pos = live_election.positions.filter(title__icontains="Secretary").first()
            
            # Select real alumni
            cand1 = UserData.objects.filter(roll_no="ME18B1003").first() # Abdul Rahman
            cand2 = UserData.objects.filter(roll_no="CS15B1003").first() # Ankur Mondal
            cand3 = UserData.objects.filter(roll_no="EC18B1049").first() # PRIYADHARSHINI G

            if pres_pos and cand1 and cand2:
                Nomination.objects.create(
                    election=live_election, position=pres_pos, candidate=cand1,
                    manifesto="Dedicated to fostering stronger alumni-student mentorship and growing our chapter network.",
                    status=Nomination.Status.APPROVED
                )
                Nomination.objects.create(
                    election=live_election, position=pres_pos, candidate=cand2,
                    manifesto="Focused on career growth opportunities, tech talks, and improving our digital alumni portal.",
                    status=Nomination.Status.APPROVED
                )
            if sec_pos and cand3:
                Nomination.objects.create(
                    election=live_election, position=sec_pos, candidate=cand3,
                    manifesto="Committed to transparent communication, timely election notifications, and active regional meetups.",
                    status=Nomination.Status.APPROVED
                )
            print("Re-seeded sample approved nominations for demo election.")

    print("\n--- IMPORT SUMMARY ---")
    print(f"Total UserData in DB: {UserData.objects.count()}")
    print(f"Total Users in DB: {User.objects.count()}")
    print(f"Total Eligible Voters: {UserData.objects.filter(is_eligible_to_vote=True).count()}")
    print("Import completed successfully!")


if __name__ == '__main__':
    run_import()
