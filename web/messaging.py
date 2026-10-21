"""PostgreSQL message storage. Identity/approval checks live at the view boundary."""
from django.db.models import BigIntegerField, Case, F, Max, Q, When

from web.models import DirectMessage, UserData


def conversation(first, second):
    return DirectMessage.objects.filter(
        Q(sender_id=first, receiver_id=second) | Q(sender_id=second, receiver_id=first)
    )


def payload(message):
    return {
        "_id": str(message.pk), "sender_id": str(message.sender_id),
        "receiver_id": str(message.receiver_id), "text": message.text,
        "datetime_sent": message.datetime_sent, "is_seen": message.is_seen,
        "seen_time": message.seen_time,
    }


def inbox(user):
    latest = DirectMessage.objects.filter(Q(sender=user) | Q(receiver=user)).annotate(
        peer_id=Case(When(sender=user, then=F("receiver_id")), default=F("sender_id"),
                     output_field=BigIntegerField())
    ).values("peer_id").annotate(last_message_time=Max("datetime_sent")).order_by("-last_message_time")
    rows = list(latest)
    profiles = {p.user_id: p for p in UserData.objects.filter(
        user_id__in=[row["peer_id"] for row in rows], account_is_approved=True, user__is_active=True,
    ).exclude(user=user)}
    unread = set(DirectMessage.objects.filter(
        receiver=user, is_seen=False, sender_id__in=profiles,
    ).values_list("sender_id", flat=True))
    return [{"other_user_id": str(row["peer_id"]), "name": profiles[row["peer_id"]].name,
             "last_message_time": row["last_message_time"], "has_unseen": row["peer_id"] in unread}
            for row in rows if row["peer_id"] in profiles]
