from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.websockets import WebSocketDisconnect

from app.display import CounterDisplays
from app.display_hub import CLOSE_ENDED, CLOSE_OCCUPIED, DisplayHub, Peer
from app.platform_auth import SESSION_COOKIE_NAME, record_audit, resolve_local_admin, resolve_principal
from contracts.v1.display import (
    DISPLAY_COOKIE_NAME, DISPLAY_MESSAGE_MAX_BYTES, ClaimRequest, CreateEnrollmentRequest, DeviceMessage,
    RenameDisplayRequest, StaffMessage,
)

# A device cookie never expires on the server; the browser keeps it as long as it is allowed to (about ten years).
DEVICE_COOKIE_MAX_AGE = 10 * 365 * 24 * 60 * 60
IDLE_TIMEOUT_SECONDS = 20
REAUTHORIZE_SECONDS = 30
MESSAGES_PER_SECOND = 60


class PrivateDisplayRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # The default validation response echoes the submitted code or link token.
                return JSONResponse(status_code=422, content={'detail':'Dữ liệu yêu cầu không hợp lệ.'})
        return private_handler


def client_address(request) -> str:
    return request.client.host if request.client else 'unknown'


def set_device_cookie(response: Response, settings, token: str) -> None:
    response.set_cookie(DISPLAY_COOKIE_NAME, token, max_age=DEVICE_COOKIE_MAX_AGE, httponly=True,
                        secure=settings.auth_cookie_secure, samesite='lax', path='/')


def clear_device_cookie(response: Response, settings) -> None:
    response.delete_cookie(DISPLAY_COOKIE_NAME, path='/', secure=settings.auth_cookie_secure, httponly=True, samesite='lax')


def create_display_router(settings, get_database, require_permission, validate_origin):
    router = APIRouter(prefix='/displays', tags=['displays'], route_class=PrivateDisplayRoute)

    def hub(request: Request) -> DisplayHub:
        return request.app.state.display_hub

    def store(request: Request) -> CounterDisplays:
        return CounterDisplays(get_database(request), settings)

    def manager(request: Request):
        if request.method != 'GET':
            validate_origin(request)
        return require_permission(request, 'settings:manage')

    def staff(request: Request):
        return require_permission(request, 'recognize:use')

    async def mutate(operation):
        try:
            return await run_in_threadpool(operation)
        except SQLAlchemyError:
            raise HTTPException(503, 'Chưa lưu được thay đổi. Hãy thử lại') from None

    def overview(request: Request, actor):
        return store(request).overview(actor, hub(request).presence, actor.can('settings:manage'))

    @router.get('')
    async def list_displays(request: Request, actor=Depends(staff)):
        return await run_in_threadpool(overview, request, actor)

    @router.post('/enrollments', status_code=201)
    async def create_enrollment(request: Request, payload: CreateEnrollmentRequest, actor=Depends(manager)):
        return await mutate(lambda: store(request).create_enrollment(actor, payload))

    @router.post('/enrollments/{identity}/confirm')
    async def confirm(request: Request, identity: str, actor=Depends(manager)):
        await mutate(lambda: store(request).decide(actor, identity, True))
        return await run_in_threadpool(overview, request, actor)

    @router.post('/enrollments/{identity}/reject')
    async def reject(request: Request, identity: str, actor=Depends(manager)):
        await mutate(lambda: store(request).decide(actor, identity, False))
        return await run_in_threadpool(overview, request, actor)

    @router.post('/{identity}/rename')
    async def rename(request: Request, identity: str, payload: RenameDisplayRequest, actor=Depends(manager)):
        await mutate(lambda: store(request).rename(actor, identity, payload.name))
        return await run_in_threadpool(overview, request, actor)

    @router.post('/{identity}/revoke')
    async def revoke(request: Request, identity: str, actor=Depends(manager)):
        await mutate(lambda: store(request).revoke(actor, identity))
        await hub(request).revoke(identity)
        return await run_in_threadpool(overview, request, actor)

    @router.post('/claim')
    async def claim(request: Request, payload: ClaimRequest, response: Response):
        validate_origin(request)
        token, state = await mutate(lambda: store(request).claim(payload, client_address(request)))
        set_device_cookie(response, settings, token)
        return state

    @router.get('/me')
    async def me(request: Request, response: Response):
        token = request.cookies.get(DISPLAY_COOKIE_NAME)
        state = await run_in_threadpool(store(request).me, token)
        if token and state['state'] == 'unpaired':
            clear_device_cookie(response, settings)
        return state

    return router


def create_display_socket(settings):
    async def staff_principal(websocket: WebSocket, database):
        if settings.local_admin_enabled:
            current = await run_in_threadpool(resolve_local_admin, database, settings.workspace_id, settings.local_admin_role)
        else:
            current = await run_in_threadpool(resolve_principal, database, websocket.cookies.get(SESSION_COOKIE_NAME),
                                              settings.workspace_id)
        return current if current is not None and current.can('recognize:use') else None

    async def display_socket(websocket: WebSocket, display_id: str) -> None:
        origin = websocket.headers.get('origin')
        allowed = settings.allowed_origins
        if origin and '*' not in allowed and origin not in allowed:
            await websocket.close(code=1008, reason='Origin không được phép')
            return
        database = websocket.app.state.platform_database
        if database is None:
            await websocket.close(code=1013, reason='Workspace chưa sẵn sàng')
            return
        hub: DisplayHub = websocket.app.state.display_hub
        displays = CounterDisplays(database, settings)
        role = websocket.query_params.get('role')
        principal = None
        if role == 'device':
            token = websocket.cookies.get(DISPLAY_COOKIE_NAME)
            display = await run_in_threadpool(displays.device, token, True)
            if display is None or display['id'] != display_id:
                await websocket.close(code=1008, reason='Màn hình quầy chưa được đăng ký')
                return
        elif role == 'staff':
            principal = await staff_principal(websocket, database)
            display = await run_in_threadpool(displays.staff_display, principal, display_id) if principal else None
            if display is None:
                await websocket.close(code=1008, reason='Đăng nhập để kết nối quầy')
                return
        else:
            await websocket.close(code=1008, reason='Vai trò không hợp lệ')
            return

        await websocket.accept()
        peer = Peer(websocket, role, principal.user.id if principal else None,
                    (principal.user.display_name or principal.user.email) if principal else display['name'])
        await peer.send({'type':'welcome', 'role':role, 'display':display, 'ice_servers':list(settings.display_ice_servers)})
        if role == 'staff':
            takeover = websocket.query_params.get('takeover') == '1'
            occupant = await hub.join_staff(display_id, peer, takeover)
            if occupant is not None:
                await peer.send({'type':'occupied', 'staff_name':occupant})
                await peer.close(CLOSE_OCCUPIED, 'Quầy đang được sử dụng')
                return
            if takeover:
                await run_in_threadpool(record_audit, database, settings.workspace_id, 'display.taken_over', 'user',
                                        principal.user.id, 'success', {'display_id':display_id})
        else:
            await hub.join_device(display_id, peer)

        parser = StaffMessage if role == 'staff' else DeviceMessage
        checked_at = time.monotonic()
        window, count = int(time.monotonic()), 0
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=IDLE_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    # Clients ping every few seconds; silence means the network is gone even if TCP has not noticed.
                    await peer.close(1001, 'Không còn tín hiệu')
                    break
                if not hub.is_current(display_id, peer):
                    break
                now = time.monotonic()
                if int(now) != window:
                    window, count = int(now), 0
                count += 1
                if count > MESSAGES_PER_SECOND:
                    await peer.close(1008, 'Gửi quá nhanh')
                    break
                if now - checked_at > REAUTHORIZE_SECONDS:
                    checked_at = now
                    if role == 'staff':
                        still = await staff_principal(websocket, database)
                        valid = still is not None and still.user.id == principal.user.id and \
                            await run_in_threadpool(displays.staff_display, still, display_id) is not None
                    else:
                        valid = (await run_in_threadpool(displays.device, websocket.cookies.get(DISPLAY_COOKIE_NAME), True)) is not None
                    if not valid:
                        await peer.close(1008, 'Phiên đã hết hiệu lực')
                        break
                if len(raw.encode('utf-8')) > DISPLAY_MESSAGE_MAX_BYTES:
                    await peer.send({'type':'error', 'detail':'Tin nhắn quá lớn'})
                    continue
                try:
                    message = parser.validate_python(json.loads(raw))
                except (json.JSONDecodeError, ValidationError):
                    await peer.send({'type':'error', 'detail':'Tin nhắn không hợp lệ'})
                    continue
                if message.type == 'ping':
                    await peer.send({'type':'pong'})
                    continue
                await hub.relay(display_id, peer, message.model_dump(mode='json', exclude_none=True))
                if message.type == 'command' and message.name == 'end_session':
                    await peer.close(CLOSE_ENDED, 'Đã kết thúc phiên')
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            # Shielded: a cancelled connection task must still release the seat and tell the other side.
            await asyncio.shield(hub.leave(display_id, peer))

    return display_socket
