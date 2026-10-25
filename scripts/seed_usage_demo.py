"""Seed or remove demonstration conversations for the usage report (F08).

Usage:
  python scripts/seed_usage_demo.py DB_PATH [--workspace local] [--days 90] [--remove]

Rows are summaries in the same shape the staff recognizer sends: counts and Sales30 labels only. Their ids are
derived from a fixed namespace, so --remove deletes exactly the rows this script added and nothing recorded at a
counter. Running it again replaces the previous demonstration set.
"""
import argparse
import json
import random
import sqlite3
import uuid
from datetime import datetime, time, timedelta, timezone

NAMESPACE = uuid.UUID('7f3c2a10-5b6e-4c1d-9a8f-0d1e2f3a4b5c')
LOCAL = timezone(timedelta(hours=7))
MAX_ROWS = 5000

# What a customer typically signs for each situation; courtesy words open and close most conversations.
SCENARIOS = [
    ('product', 0.46, [['Muốn', 'Mua', 'Tivi'], ['Cần', 'Tủ lạnh'], ['Cho', 'Xem', 'Điện thoại'], ['Muốn', 'Xem', 'Laptop'],
                       ['Mua', 'Máy giặt'], ['Cần', 'Nồi cơm điện'], ['Mua', 'Gạo'], ['Cho', 'Sữa'], ['Mua', 'Cà phê'],
                       ['Siêu thị', 'Có', 'Tivi'], ['Xem', 'Tủ lạnh', 'Mới']]),
    ('price', 0.2, [['Tivi', 'Rẻ'], ['Laptop', 'Đắt'], ['Điện thoại', 'Mới'], ['Máy giặt', 'Cũ'], ['Thử', 'Laptop'],
                    ['Sử dụng', 'Nồi cơm điện'], ['Muốn', 'Rẻ']]),
    ('payment', 0.14, [['Ngân hàng'], ['Mua bán', 'Ngân hàng'], ['Cung cấp', 'Ngân hàng'], ['Mua', 'Ngân hàng']]),
    ('return', 0.08, [['Thay đổi', 'Điện thoại'], ['Từ chối', 'Mua'], ['Thay đổi', 'Máy giặt'], ['Thay đổi', 'Laptop']]),
    ('courtesy', 0.12, [['Chào'], ['Cảm ơn'], ['Chào', 'Tôi']]),
]
# Signs the model confuses most often in pilot sessions; these are the ones staff and customers undo.
CONFUSED = ['Rẻ', 'Đắt', 'Mua bán', 'Thay đổi', 'Cung cấp', 'Sử dụng', 'Cũ', 'Thử']


def pick(rng, weighted):
    roll, total = rng.random(), 0.0
    for item in weighted:
        total += item[1]
        if roll <= total:
            return item
    return weighted[-1]


def conversation(rng, started, display_id, user_id, workspace_id, index):
    _, _, phrases = pick(rng, SCENARIOS)
    signed = list(rng.choice(phrases))
    if rng.random() < 0.55:
        signed.insert(0, rng.choice(['Chào', 'Tôi']))
    if rng.random() < 0.35:
        signed.append('Cảm ơn')
    counter = display_id is not None and rng.random() < 0.72
    kind = rng.random()
    undone = {}
    staff_undos = customer_undos = 0
    if kind < 0.04:  # nothing came through: the customer gave up or switched to pointing
        words, uncertain, failed, labels = 0, rng.randint(1, 3), rng.randint(0, 1), {}
    else:
        labels = {}
        for label in signed:
            labels[label] = labels.get(label, 0) + 1
        words = len(signed)
        uncertain = rng.choices([0, 1, 2], weights=[74, 21, 5])[0]
        failed = 1 if rng.random() < 0.05 else 0
        undos = rng.choices([0, 1, 2], weights=[70, 24, 6])[0]
        if kind < 0.1:  # mostly unclear: more segments failed or undone than kept
            uncertain = words - 1 + rng.randint(0, 1)
            undos = max(undos, 1)
        for _ in range(undos):
            label = rng.choice(CONFUSED)
            undone[label] = undone.get(label, 0) + 1
            if counter and rng.random() < 0.4:
                customer_undos += 1
            else:
                staff_undos += 1
    replies = 0 if words == 0 and rng.random() < 0.5 else rng.choices([1, 2, 3, 4], weights=[38, 36, 18, 8])[0]
    voice = sum(rng.random() < 0.28 for _ in range(replies))
    seconds = 25 + words * rng.uniform(9, 16) + replies * rng.uniform(6, 12) + rng.uniform(0, 40)
    return {
        'id': str(uuid.uuid5(NAMESPACE, f'{workspace_id}:{index}')), 'workspace_id': workspace_id, 'user_id': user_id,
        'display_id': display_id if counter else None, 'channel': 'counter' if counter else 'same_screen',
        'started_at': started, 'ended_at': started + timedelta(seconds=seconds),
        'words': words, 'uncertain': uncertain, 'failed': failed, 'staff_undos': staff_undos,
        'customer_undos': customer_undos, 'replies': replies, 'voice_replies': voice,
        'labels_json': json.dumps(labels), 'undone_labels_json': json.dumps(undone),
    }


def stamp(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=' ', timespec='microseconds')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('database')
    parser.add_argument('--workspace', default='local')
    parser.add_argument('--days', type=int, default=90)
    parser.add_argument('--seed', type=int, default=20261025)
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    ids = [str(uuid.uuid5(NAMESPACE, f'{args.workspace}:{index}')) for index in range(MAX_ROWS)]
    db = sqlite3.connect(args.database)
    with db:
        removed = sum(db.execute('DELETE FROM usage_conversations WHERE id = ?', (row_id,)).rowcount for row_id in ids)
        if args.remove:
            print(f'Removed {removed} demonstration conversations.')
            return
        user = db.execute("SELECT u.id FROM users u JOIN memberships m ON m.user_id = u.id "
                          "WHERE m.workspace_id = ? ORDER BY m.created_at LIMIT 1", (args.workspace,)).fetchone()
        if user is None:
            raise SystemExit(f'No member in workspace {args.workspace}.')
        displays = [row[0] for row in db.execute('SELECT id FROM display_devices WHERE workspace_id = ? ORDER BY created_at',
                                                 (args.workspace,))][:2]
        rng = random.Random(args.seed)
        today = datetime.now(LOCAL).date()
        now = datetime.now(LOCAL)
        rows = []
        for offset in range(args.days - 1, -1, -1):
            date = today - timedelta(days=offset)
            # A pilot that grows over the period: about 3 conversations a day at the start, 12 at the end; quieter Sundays.
            progress = 1 - offset / max(args.days - 1, 1)
            mean = (3 + 9 * progress) * (0.55 if date.weekday() == 6 else 1.15 if date.weekday() == 5 else 1)
            for _ in range(max(0, round(rng.gauss(mean, mean * 0.25)))):
                hour = rng.choices(range(8, 21), weights=[3, 6, 8, 7, 5, 4, 5, 6, 7, 8, 9, 7, 4])[0]
                started = datetime.combine(date, time(hour, rng.randint(0, 59), rng.randint(0, 59)), LOCAL)
                if started >= now or len(rows) >= MAX_ROWS:
                    continue
                display = rng.choice(displays) if displays else None
                rows.append(conversation(rng, started, display, user[0], args.workspace, len(rows)))
        for row in rows:
            row['started_at'], row['ended_at'] = stamp(row['started_at']), stamp(row['ended_at'])
            row['created_at'] = row['ended_at']
        db.executemany(f"INSERT INTO usage_conversations ({', '.join(rows[0])}) VALUES ({', '.join(':' + key for key in rows[0])})", rows)
    print(f'Replaced {removed} with {len(rows)} demonstration conversations in workspace {args.workspace}.')


if __name__ == '__main__':
    main()
