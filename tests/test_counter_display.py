from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app import display as display_module
from app.display_db import DisplayDevice, DisplayEnrollment
from app.main import create_app
from app.platform_db import Membership, utc_now
from test_local_admin import local_settings

BASE = '/api/v1/displays'
PASSWORD = 'correct-password-123'


@pytest.fixture
def settings(monkeypatch, tmp_path):
    return local_settings(monkeypatch, tmp_path)


def enroll(client, name='Quầy 1'):
    response = client.post(BASE+'/enrollments', json={'name':name})
    assert response.status_code == 201, response.text
    return response.json()


def claim(client, **secret):
    response = client.post(BASE+'/claim', json=secret)
    return response, response.cookies.get('vsign_display')


def pair(client, name='Quầy 1'):
    """An enrolled display id and its device token."""
    enrollment = enroll(client, name)
    response, token = claim(client, code=enrollment['code'])
    assert response.status_code == 200, response.text
    client.cookies.delete('vsign_display')
    assert client.post(BASE+f'/enrollments/{enrollment["id"]}/confirm').status_code == 200
    display = next(row for row in client.get(BASE).json()['displays'] if row['name'] == name)
    return display['id'], token


def device_headers(token):
    return {'cookie':f'vsign_display={token}'}


def me(client, token):
    client.cookies.clear()
    response = client.get(BASE+'/me', headers=device_headers(token) if token else {})
    assert response.status_code == 200, response.text
    return response


def test_one_time_code_enrolls_a_permanent_display(settings):
    with TestClient(create_app(settings)) as client:
        enrollment = enroll(client)
        assert len(enrollment['code']) == 6 and enrollment['code'].isdigit() and len(enrollment['link_token']) == 43
        response, token = claim(client, code=enrollment['code'])
        assert response.status_code == 200, response.text
        state = response.json()
        assert state['state'] == 'awaiting_confirmation' and len(state['verification']) == 2 and state['name'] == 'Quầy 1'
        assert me(client, token).json()['verification'] == state['verification']
        pending = client.get(BASE).json()['enrollments']
        assert pending == [{'id':enrollment['id'], 'name':'Quầy 1', 'status':'awaiting_confirmation',
                            'expires_at':pending[0]['expires_at'], 'verification':state['verification']}]
        # The code is spent once claimed, even before staff confirm it.
        assert claim(client, code=enrollment['code'])[0].status_code == 404
        assert client.post(BASE+f'/enrollments/{enrollment["id"]}/confirm').status_code == 200
        paired = me(client, token).json()
        assert paired['state'] == 'paired' and paired['display']['name'] == 'Quầy 1'
        # Months later the token still works: only revocation ends it.
        with client.app.state.platform_database.session() as session:
            device = session.scalar(select(DisplayDevice))
            device.created_at = utc_now() - timedelta(days=400)
            session.commit()
        assert me(client, token).json()['state'] == 'paired'
        stored = Path(settings.database_url.removeprefix('sqlite:///')).read_bytes()
        assert token.encode() not in stored and enrollment['link_token'].encode() not in stored
        listed = client.get(BASE).json()
        assert listed['permissions'] == {'manage':True} and listed['enrollments'] == []
        assert [row['name'] for row in listed['displays']] == ['Quầy 1'] and listed['displays'][0]['online'] is False


def test_link_token_claims_and_rejection_unpairs(settings):
    with TestClient(create_app(settings)) as client:
        enrollment = enroll(client)
        response, token = claim(client, link_token=enrollment['link_token'])
        assert response.status_code == 200
        assert client.post(BASE+f'/enrollments/{enrollment["id"]}/reject').status_code == 200
        response = me(client, token)
        assert response.json() == {'api_version':'1', 'state':'unpaired', 'reason':'rejected'}
        assert 'vsign_display=""' in response.headers['set-cookie'] or 'Max-Age=0' in response.headers['set-cookie']
        assert client.post(BASE+f'/enrollments/{enrollment["id"]}/confirm').status_code == 409
        assert claim(client, code='12345', link_token=None)[0].status_code == 422
        assert claim(client, code=enrollment['code'], link_token=enrollment['link_token'])[0].status_code == 422


def test_expired_and_guessed_codes_stop_working(settings, monkeypatch):
    monkeypatch.setattr(display_module, 'CLAIMS_PER_ADDRESS_PER_MINUTE', 100)
    monkeypatch.setattr(display_module, 'CLAIMS_PER_MINUTE', 100)
    with TestClient(create_app(settings)) as client:
        expiring = enroll(client, 'Quầy hết hạn')
        with client.app.state.platform_database.session() as session:
            session.get(DisplayEnrollment, expiring['id']).expires_at = utc_now() - timedelta(seconds=1)
            session.commit()
        assert claim(client, code=expiring['code'])[0].status_code == 404
        guessed = enroll(client, 'Quầy đoán')
        wrong = f'{(int(guessed["code"]) + 1) % 1_000_000:06d}'
        for _ in range(display_module.MAX_FAILED_ATTEMPTS):
            assert claim(client, code=wrong)[0].status_code == 404
        # The real code is now dead too: a code survives only a bounded number of guesses in total.
        assert claim(client, code=guessed['code'])[0].status_code == 404
        assert client.get(BASE).json()['enrollments'] == []


def test_claims_are_rate_limited_per_address(settings):
    with TestClient(create_app(settings)) as client:
        for _ in range(display_module.CLAIMS_PER_ADDRESS_PER_MINUTE):
            assert claim(client, code='000000')[0].status_code == 404
        response = claim(client, code='000000')[0]
        assert response.status_code == 429 and 'Retry-After' in response.headers


def test_claim_requires_allowed_origin(settings):
    with TestClient(create_app(settings)) as client:
        enrollment = enroll(client)
        response = client.post(BASE+'/claim', json={'code':enrollment['code']}, headers={'Origin':'https://evil.example'})
        assert response.status_code == 403


def test_rename_and_revoke_end_the_device(settings):
    with TestClient(create_app(settings)) as client:
        display_id, token = pair(client)
        client.cookies.clear()
        assert client.post(BASE+f'/{display_id}/rename', json={'name':'  Quầy VIP  '}).json()['displays'][0]['name'] == 'Quầy VIP'
        with client.websocket_connect(f'/ws/display/{display_id}?role=device', headers=device_headers(token)) as device:
            assert device.receive_json()['type'] == 'welcome'
            assert device.receive_json() == {'type':'peer', 'role':'staff', 'online':False, 'name':None}
            assert client.get(BASE).json()['displays'][0]['online'] is True
            assert client.post(BASE+f'/{display_id}/revoke').json()['displays'] == []
            assert device.receive_json() == {'type':'revoked'}
            with pytest.raises(WebSocketDisconnect) as closed:
                device.receive_json()
            assert closed.value.code == 4003
        assert me(client, token).json() == {'api_version':'1', 'state':'unpaired', 'reason':'revoked'}
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f'/ws/display/{display_id}?role=device', headers=device_headers(token)) as device:
                device.receive_json()
        assert client.post(BASE+f'/{display_id}/rename', json={'name':'Lại'}).status_code == 404


def test_staff_and_device_share_state_signals_and_commands(settings):
    with TestClient(create_app(settings)) as client:
        display_id, token = pair(client)
        client.cookies.clear()
        with client.websocket_connect(f'/ws/display/{display_id}?role=staff') as staff:
            welcome = staff.receive_json()
            assert welcome['role'] == 'staff' and welcome['display'] == {'id':display_id, 'name':'Quầy 1'}
            assert welcome['ice_servers'][0]['urls']
            assert staff.receive_json() == {'type':'peer', 'role':'device', 'online':False}
            state = {'type':'display_state', 'conversation_id':'c1', 'revision':3, 'phase':'ok', 'word':'Xin chào',
                     'words':['Xin chào'], 'sentence':'Xin chào.', 'guide':'fixed'}
            staff.send_json(state)
            with client.websocket_connect(f'/ws/display/{display_id}?role=device', headers=device_headers(token)) as device:
                assert device.receive_json()['role'] == 'device'
                peer = device.receive_json()
                assert peer['role'] == 'staff' and peer['online'] and peer['name']
                assert device.receive_json() == state
                assert staff.receive_json() == {'type':'peer', 'role':'device', 'online':True}
                offer = {'type':'signal', 'session':'s1', 'kind':'offer', 'sdp':'v=0'}
                device.send_json(offer)
                assert staff.receive_json() == offer
                candidate = {'type':'signal', 'session':'s1', 'kind':'candidate',
                             'candidate':{'candidate':'candidate:1 1 udp 1 10.0.0.2 5000 typ host', 'sdpMid':'0', 'sdpMLineIndex':0}}
                staff.send_json(candidate)
                assert device.receive_json() == candidate
                # A device may not speak for staff, and malformed messages are refused without closing the socket.
                device.send_json({**state, 'word':'Giả mạo'})
                assert device.receive_json()['type'] == 'error'
                staff.send_json({'type':'signal', 'session':'s1', 'kind':'offer'})
                assert staff.receive_json()['type'] == 'error'
                device.send_json({'type':'ping'})
                assert device.receive_json() == {'type':'pong'}
                command = {'type':'command', 'name':'new_conversation', 'conversation_id':'c2'}
                staff.send_json(command)
                assert device.receive_json() == command
            assert staff.receive_json() == {'type':'peer', 'role':'device', 'online':False}
            staff.send_json({'type':'command', 'name':'end_session', 'conversation_id':'c2'})
            with pytest.raises(WebSocketDisconnect) as closed:
                staff.receive_json()
            assert closed.value.code == 4011


def test_one_staff_per_counter_until_taken_over(settings):
    with TestClient(create_app(settings)) as client:
        display_id, token = pair(client)
        client.cookies.clear()
        with client.websocket_connect(f'/ws/display/{display_id}?role=staff') as first:
            first.receive_json(), first.receive_json()
            with client.websocket_connect(f'/ws/display/{display_id}?role=staff') as second:
                second.receive_json()
                occupied = second.receive_json()
                assert occupied['type'] == 'occupied' and occupied['staff_name']
                with pytest.raises(WebSocketDisconnect) as closed:
                    second.receive_json()
                assert closed.value.code == 4009
            with client.websocket_connect(f'/ws/display/{display_id}?role=staff&takeover=1') as third:
                third.receive_json(), third.receive_json()
                assert first.receive_json()['type'] == 'taken_over'
                with pytest.raises(WebSocketDisconnect) as closed:
                    first.receive_json()
                assert closed.value.code == 4010
                with client.websocket_connect(f'/ws/display/{display_id}?role=device', headers=device_headers(token)) as device:
                    device.receive_json()
                    assert device.receive_json()['online'] is True
                    assert third.receive_json() == {'type':'peer', 'role':'device', 'online':True}


def test_socket_rejects_wrong_display_role_and_origin(settings):
    with TestClient(create_app(settings)) as client:
        first, token = pair(client, 'Quầy 1')
        second, _ = pair(client, 'Quầy 2')
        client.cookies.clear()
        for path, headers in ((f'/ws/display/{second}?role=device', device_headers(token)),
                              (f'/ws/display/{first}?role=device', {}),
                              (f'/ws/display/{first}', device_headers(token)),
                              ('/ws/display/missing?role=staff', {}),
                              (f'/ws/display/{first}?role=staff', {'origin':'https://evil.example'})):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(path, headers=headers) as socket:
                    socket.receive_json()


@pytest.mark.parametrize('role', ['operator', 'viewer'])
def test_staff_without_settings_manage_connect_but_cannot_enroll(settings, role):
    settings = replace(settings, local_admin_enabled=False, auth_required=True, bootstrap_admin_email='owner@example.com',
                       bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        assert client.post('/api/v1/auth/login', json={'email':'owner@example.com', 'password':PASSWORD}).status_code == 200
        display_id, token = pair(client)
        with client.app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = role
            session.commit()
        listed = client.get(BASE).json()
        assert listed['permissions'] == {'manage':False} and listed['displays'][0]['id'] == display_id
        assert client.post(BASE+'/enrollments', json={'name':'Quầy 2'}).status_code == 403
        assert client.post(BASE+f'/{display_id}/revoke').status_code == 403
        assert client.post(BASE+f'/{display_id}/rename', json={'name':'x'}).status_code == 403
        session_cookie = client.cookies.get('vsign_session')
        with client.websocket_connect(f'/ws/display/{display_id}?role=staff',
                                      headers={'cookie':f'vsign_session={session_cookie}'}) as staff:
            assert staff.receive_json()['type'] == 'welcome'
        # The device token is not a login: it opens nothing but its own display.
        client.cookies.clear()
        assert client.get('/api/v1/auth/me', headers=device_headers(token)).status_code == 401
        assert client.get(BASE, headers=device_headers(token)).status_code == 401
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws/inference', headers=device_headers(token)) as socket:
                socket.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f'/ws/display/{display_id}?role=staff', headers=device_headers(token)) as socket:
                socket.receive_json()


def test_migration_creates_display_tables(settings):
    with TestClient(create_app(settings)) as client:
        from sqlalchemy import inspect
        tables = set(inspect(client.app.state.platform_database.engine).get_table_names())
        assert {'display_devices', 'display_enrollments'} <= tables


def test_ice_servers_come_from_the_environment(monkeypatch, tmp_path):
    from app.config import Settings
    settings = local_settings(monkeypatch, tmp_path)
    assert settings.display_ice_servers[0]['urls'][0].startswith('stun:')
    monkeypatch.setenv('DISPLAY_ICE_SERVERS', '[{"urls":"turn:turn.example:3478","username":"u","credential":"c"}]')
    assert Settings.from_env().display_ice_servers == ({'urls':'turn:turn.example:3478', 'username':'u', 'credential':'c'},)
    for bad in ('not json', '{"urls":"stun:x"}', '[{"urls":"https://x"}]', '[{"urls":"stun:x","extra":1}]'):
        monkeypatch.setenv('DISPLAY_ICE_SERVERS', bad)
        with pytest.raises(RuntimeError):
            Settings.from_env()
