"""In-process relay between one staff recognizer and one counter display per room.

The runtime is a single uvicorn worker, so rooms live in memory. Nothing here is durable: a restart drops every
socket, both sides reconnect, and the staff side re-negotiates video and re-sends its state.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from starlette.websockets import WebSocket

# Application close codes, shared with the web client.
CLOSE_REPLACED = 4001
CLOSE_REVOKED = 4003
CLOSE_OCCUPIED = 4009
CLOSE_TAKEN_OVER = 4010
CLOSE_ENDED = 4011


@dataclass(eq=False)
class Peer:
    websocket: WebSocket
    role: str
    user_id: Optional[str] = None
    name: str = ''
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, message: dict[str, Any]) -> bool:
        async with self.lock:
            try:
                await self.websocket.send_json(message)
                return True
            except Exception:
                return False

    async def close(self, code: int, reason: str = '') -> None:
        try:
            await self.websocket.close(code=code, reason=reason)
        except Exception:
            pass


@dataclass
class Room:
    staff: Optional[Peer] = None
    device: Optional[Peer] = None
    # The staff side's latest display_state, replayed to a device that reconnects mid-session.
    state: Optional[dict[str, Any]] = None


def staff_presence(peer: Optional[Peer]) -> dict[str, Any]:
    return {'type':'peer', 'role':'staff', 'online':peer is not None, 'name':peer.name if peer else None}


def device_presence(peer: Optional[Peer]) -> dict[str, Any]:
    return {'type':'peer', 'role':'device', 'online':peer is not None}


class DisplayHub:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def presence(self, display_id: str) -> tuple[bool, Optional[str]]:
        room = self.rooms.get(display_id)
        if room is None:
            return False, None
        return room.device is not None, room.staff.name if room.staff else None

    def is_current(self, display_id: str, peer: Peer) -> bool:
        room = self.rooms.get(display_id)
        return room is not None and peer in (room.staff, room.device)

    async def join_device(self, display_id: str, peer: Peer) -> None:
        room = self.rooms.setdefault(display_id, Room())
        previous, room.device = room.device, peer
        if previous is not None:
            # The same counter opened in another tab or after a network change: the newest socket wins.
            await previous.close(CLOSE_REPLACED, 'Màn hình đã mở ở nơi khác')
        await peer.send(staff_presence(room.staff))
        if room.state is not None:
            await peer.send(room.state)
        if room.staff is not None:
            await room.staff.send(device_presence(peer))

    async def join_staff(self, display_id: str, peer: Peer, takeover: bool) -> Optional[str]:
        """Seat the staff member; returns the occupant's name instead when someone else holds the counter."""
        room = self.rooms.setdefault(display_id, Room())
        previous = room.staff
        if previous is not None and not takeover:
            return previous.name or 'nhân viên khác'
        room.staff, room.state = peer, None
        if previous is not None:
            await previous.send({'type':'taken_over', 'by':peer.name})
            await previous.close(CLOSE_TAKEN_OVER, 'Quầy đã được tiếp quản')
        await peer.send(device_presence(room.device))
        if room.device is not None:
            await room.device.send(staff_presence(peer))
        return None

    async def leave(self, display_id: str, peer: Peer) -> None:
        room = self.rooms.get(display_id)
        if room is None:
            return
        if room.staff is peer:
            room.staff, room.state = None, None
            if room.device is not None:
                await room.device.send(staff_presence(None))
        elif room.device is peer:
            room.device = None
            if room.staff is not None:
                await room.staff.send(device_presence(None))
        if room.staff is None and room.device is None and self.rooms.get(display_id) is room:
            del self.rooms[display_id]

    async def relay(self, display_id: str, sender: Peer, message: dict[str, Any]) -> None:
        room = self.rooms.get(display_id)
        if room is None or sender not in (room.staff, room.device):
            return
        if sender is room.staff and message['type'] == 'display_state':
            room.state = message
        if sender is room.staff and message['type'] == 'command' and message['name'] == 'new_conversation':
            room.state = None
        target = room.device if sender is room.staff else room.staff
        if target is not None:
            await target.send(message)

    async def revoke(self, display_id: str) -> None:
        room = self.rooms.pop(display_id, None)
        if room is None:
            return
        for peer in (room.device, room.staff):
            if peer is not None:
                await peer.send({'type':'revoked'})
                await peer.close(CLOSE_REVOKED, 'Màn hình quầy đã bị huỷ')
