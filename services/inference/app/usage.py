"""Usage reports (F08): store one summary per conversation, aggregate them per workspace for a period."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.display_db import DisplayDevice
from app.platform_auth import Principal
from app.platform_db import Database, utc_now
from app.usage_db import UsageConversation
from contracts.v1.sales_vocabulary import SALES_30_LABELS
from contracts.v1.usage import SCENARIO_OF, SCENARIOS, ConversationSummaryRequest

# Vietnam has no daylight saving time, so a fixed offset gives the same calendar days as Asia/Ho_Chi_Minh.
LOCAL = timezone(timedelta(hours=7))
KNOWN = frozenset(SALES_30_LABELS)


def _known(labels: dict[str, int]) -> dict[str, int]:
    return {label: count for label, count in labels.items() if label in KNOWN and count > 0}


def store_conversation(database: Database, workspace_id: str, actor: Principal, payload: ConversationSummaryRequest) -> bool:
    """True when stored, False when the same summary was already stored (a retried request)."""
    conversation_id = str(payload.id)
    with database.session() as session:
        existing = session.get(UsageConversation, conversation_id)
        if existing is not None:
            if existing.workspace_id != workspace_id or existing.user_id != actor.user.id:
                raise HTTPException(status_code=409, detail='ID cuộc hội thoại đã được dùng')
            return False
        if payload.display_id is not None:
            display = session.get(DisplayDevice, payload.display_id)
            if display is None or display.workspace_id != workspace_id:
                raise HTTPException(status_code=422, detail='Màn hình quầy không thuộc workspace này')
        session.add(UsageConversation(
            id=conversation_id, workspace_id=workspace_id, user_id=actor.user.id, display_id=payload.display_id,
            channel=payload.channel, started_at=payload.started_at, ended_at=payload.ended_at, words=payload.words,
            uncertain=payload.uncertain, failed=payload.failed, staff_undos=payload.staff_undos,
            customer_undos=payload.customer_undos, replies=payload.replies, voice_replies=payload.voice_replies,
            labels_json=_known(payload.labels), undone_labels_json=_known(payload.undone_labels)))
        try:
            session.commit()
        except IntegrityError:
            # A concurrent retry stored it first.
            session.rollback()
            return False
        return True


def is_unhandled(row: UsageConversation) -> str | None:
    """Why a conversation went badly: no word came through, or more segments failed or were undone than kept."""
    problems = row.uncertain + row.failed
    if row.words == 0:
        return 'no_word' if problems else None
    return 'mostly_unclear' if problems + row.staff_undos + row.customer_undos > row.words else None


def usage_report(database: Database, workspace_id: str, days: int) -> dict:
    now = utc_now()
    today = now.astimezone(LOCAL).date()
    start_date = today - timedelta(days=days - 1)
    start = (now.astimezone(LOCAL).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1))
    with database.session() as session:
        rows = session.scalars(select(UsageConversation).where(
            UsageConversation.workspace_id == workspace_id,
            UsageConversation.started_at >= start.astimezone(timezone.utc),
            UsageConversation.started_at <= now)).all()

    def local_day(value):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(LOCAL).date()

    daily = {start_date + timedelta(days=offset): {'conversations': 0, 'words': 0, 'unhandled': 0} for offset in range(days)}
    words, undone = Counter(), Counter()
    scenario_words, scenario_conversations = Counter(), Counter()
    reasons = Counter()
    duration = 0.0
    for row in rows:
        reason = is_unhandled(row)
        reasons[reason] += 1
        bucket = daily.get(local_day(row.started_at))
        if bucket is not None:
            bucket['conversations'] += 1
            bucket['words'] += row.words
            bucket['unhandled'] += reason is not None
        words.update(row.labels_json)
        undone.update(row.undone_labels_json)
        touched = {SCENARIO_OF[label] for label in row.labels_json if label in SCENARIO_OF}
        for label, count in row.labels_json.items():
            if label in SCENARIO_OF:
                scenario_words[SCENARIO_OF[label]] += count
        # Courtesy words alone are still a conversation, but they do not say what the customer came for.
        topical = touched - {'courtesy'}
        scenario_conversations.update(topical or touched)
        started = row.started_at.replace(tzinfo=row.started_at.tzinfo or timezone.utc)
        ended = row.ended_at.replace(tzinfo=row.ended_at.tzinfo or timezone.utc)
        duration += (ended - started).total_seconds()

    total = len(rows)
    total_words = sum(row.words for row in rows)
    return {
        'workspace_id': workspace_id, 'generated_at': now, 'days': days, 'start_date': start_date,
        'totals': {
            'conversations': total, 'counter_conversations': sum(row.channel == 'counter' for row in rows),
            'words': total_words, 'avg_words': round(total_words / total, 1) if total else 0.0,
            'avg_duration_seconds': round(duration / total, 1) if total else 0.0,
            'replies': sum(row.replies for row in rows), 'voice_replies': sum(row.voice_replies for row in rows),
            'uncertain': sum(row.uncertain for row in rows), 'failed': sum(row.failed for row in rows),
            'undos': sum(row.staff_undos + row.customer_undos for row in rows),
            'customer_undos': sum(row.customer_undos for row in rows),
            'unhandled_conversations': total - reasons[None],
        },
        'daily': [{'date': day, **values} for day, values in daily.items()],
        'scenarios': [{'id': key, 'label': label, 'conversations': scenario_conversations[key], 'words': scenario_words[key]}
                      for key, label, _ in SCENARIOS],
        'top_words': [{'label': label, 'count': count} for label, count in
                      sorted(words.items(), key=lambda item: (-item[1], item[0]))[:10]],
        'unhandled': {'no_word': reasons['no_word'], 'mostly_unclear': reasons['mostly_unclear'],
                      'undone_labels': [{'label': label, 'count': count} for label, count in
                                        sorted(undone.items(), key=lambda item: (-item[1], item[0]))[:8]]},
    }
