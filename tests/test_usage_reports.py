from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.platform_db import Membership
from test_counter_display import pair
from test_local_admin import local_settings

BASE = '/api/v1/workspace/usage'
PASSWORD = 'correct-password-123'


@pytest.fixture
def settings(monkeypatch, tmp_path):
    return local_settings(monkeypatch, tmp_path)


def summary(**overrides):
    ended = datetime.now(timezone.utc) - timedelta(minutes=1)
    body = {'id':str(uuid4()), 'started_at':(ended - timedelta(seconds=90)).isoformat(), 'ended_at':ended.isoformat(),
            'channel':'same_screen', 'display_id':None, 'words':3, 'uncertain':1, 'failed':0, 'staff_undos':0,
            'customer_undos':0, 'replies':1, 'voice_replies':0,
            'labels':{'Tôi':1, 'Muốn':1, 'Tivi':1}, 'undone_labels':{}}
    body.update(overrides)
    return body


def test_conversation_summaries_build_the_usage_report(settings):
    with TestClient(create_app(settings)) as client:
        display_id, _ = pair(client)
        first = summary()
        assert client.post(BASE+'/conversations', json=first).status_code == 201
        # A retried request is accepted once and not counted twice.
        retry = client.post(BASE+'/conversations', json=first)
        assert retry.status_code == 200 and retry.json()['status'] == 'duplicate'
        client.post(BASE+'/conversations', json=summary(channel='counter', display_id=display_id, words=2,
            labels={'Ngân hàng':1, 'Cảm ơn':1}, customer_undos=1, replies=2, voice_replies=1, undone_labels={'Rẻ':1}))
        client.post(BASE+'/conversations', json=summary(words=0, uncertain=3, labels={}, replies=0))
        client.post(BASE+'/conversations', json=summary(words=1, uncertain=1, staff_undos=1, labels={'Chào':1},
                                                        undone_labels={'Rẻ':1, 'Giả':4}, replies=0))
        report = client.get(BASE+'/report', params={'days':7})
        assert report.status_code == 200, report.text
        body = report.json()
        assert body['days'] == 7 and len(body['daily']) == 7 and body['timezone'] == 'Asia/Ho_Chi_Minh'
        totals = body['totals']
        assert totals['conversations'] == 4 and totals['counter_conversations'] == 1
        assert totals['words'] == 6 and totals['avg_words'] == 1.5 and totals['avg_duration_seconds'] == 90
        assert totals['replies'] == 3 and totals['voice_replies'] == 1
        assert totals['undos'] == 2 and totals['customer_undos'] == 1
        assert totals['unhandled_conversations'] == 2
        assert body['unhandled']['no_word'] == 1 and body['unhandled']['mostly_unclear'] == 1
        # Labels outside the vocabulary are not kept.
        assert body['unhandled']['undone_labels'] == [{'label':'Rẻ', 'count':2}]
        scenarios = {row['id']:row for row in body['scenarios']}
        assert scenarios['product'] == {'id':'product', 'label':'Tìm và hỏi sản phẩm', 'conversations':1, 'words':2}
        assert scenarios['payment']['conversations'] == 1
        # A greeting-only conversation still counts, under courtesy.
        assert scenarios['courtesy']['conversations'] == 1 and scenarios['courtesy']['words'] == 3
        assert sum(day['conversations'] for day in body['daily']) == 4
        assert {'label':'Tivi', 'count':1} in body['top_words']


@pytest.mark.parametrize('overrides', [
    {'ended_at':(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
    {'started_at':(datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()},
    {'started_at':'2026-01-01T00:00:00'},
    {'voice_replies':2},
    {'channel':'counter'},
    {'display_id':'unknown'},
    {'words':-1},
    {'transcript':'Tôi muốn mua tivi'},
])
def test_invalid_summaries_are_rejected(settings, overrides):
    with TestClient(create_app(settings)) as client:
        assert client.post(BASE+'/conversations', json=summary(**overrides)).status_code == 422


def test_unknown_display_is_refused(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post(BASE+'/conversations', json=summary(channel='counter', display_id=str(uuid4())))
        assert response.status_code == 422


def test_report_period_is_validated(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get(BASE+'/report', params={'days':14}).status_code == 422
        empty = client.get(BASE+'/report').json()
        assert empty['days'] == 30 and empty['totals']['conversations'] == 0 and empty['totals']['avg_words'] == 0


@pytest.mark.parametrize('role, can_read', [('viewer', True), ('operator', True), ('model_admin', False)])
def test_report_permission_follows_role(settings, role, can_read):
    settings = replace(settings, local_admin_enabled=False, auth_required=True, bootstrap_admin_email='owner@example.com',
                       bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        assert client.post('/api/v1/auth/login', json={'email':'owner@example.com', 'password':PASSWORD}).status_code == 200
        with client.app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = role
            session.commit()
        assert client.get(BASE+'/report').status_code == (200 if can_read else 403)
        capabilities = client.get('/api/v1/workspace/capabilities').json()['capabilities']
        assert capabilities['reports'] is can_read
        # Anyone at the counter records their own conversations.
        assert client.post(BASE+'/conversations', json=summary()).status_code == 201
