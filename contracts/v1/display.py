"""Counter displays: a customer-facing laptop paired once to the workspace, mirrored by a staff recognizer."""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator

DISPLAY_COOKIE_NAME = 'vsign_display'
DISPLAY_NAME_MAX = 60
DISPLAY_MESSAGE_MAX_BYTES = 65536
REPLY_MAX = 300

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=DISPLAY_NAME_MAX)]
Word = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Token = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,64}$')]
InferencePhase = Literal['ready', 'capturing', 'processing', 'ok', 'uncertain', 'no_hands', 'bad_framing',
                         'busy', 'error', 'disconnected']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CreateEnrollmentRequest(Strict):
    name: DisplayName


class RenameDisplayRequest(Strict):
    name: DisplayName


class ClaimRequest(Strict):
    code: Optional[Annotated[str, StringConstraints(pattern=r'^\d{6}$')]] = Field(default=None, repr=False)
    link_token: Optional[Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{43}$')]] = Field(default=None, repr=False)

    @model_validator(mode='after')
    def one_secret(self):
        if (self.code is None) == (self.link_token is None):
            raise ValueError('Cần đúng một mã hoặc liên kết')
        return self


# WebSocket messages. Staff and device share the socket; the server checks which side may send which type.

class IceCandidate(Strict):
    candidate: Annotated[str, StringConstraints(max_length=1024)]
    sdpMid: Optional[Annotated[str, StringConstraints(max_length=64)]] = None
    sdpMLineIndex: Optional[int] = Field(default=None, ge=0, le=64)


class SignalMessage(Strict):
    type: Literal['signal']
    session: Token
    kind: Literal['offer', 'answer', 'candidate', 'request_offer']
    sdp: Optional[Annotated[str, StringConstraints(max_length=32768)]] = None
    candidate: Optional[IceCandidate] = None

    @model_validator(mode='after')
    def payload_matches_kind(self):
        if (self.kind in ('offer', 'answer')) != (self.sdp is not None):
            raise ValueError('SDP chỉ đi kèm offer/answer')
        if (self.kind == 'candidate') != (self.candidate is not None):
            raise ValueError('Candidate chỉ đi kèm kind=candidate')
        return self


class DisplayState(Strict):
    type: Literal['display_state']
    conversation_id: Token
    revision: int = Field(ge=0)
    phase: InferencePhase
    word: Optional[Word] = None
    words: List[Word] = Field(default_factory=list, max_length=200)
    sentence: Annotated[str, StringConstraints(max_length=600)] = ''
    guide: Literal['fixed', 'adaptive'] = 'fixed'
    # The staff member's latest answer to the customer, typed or dictated on the staff side.
    reply: Annotated[str, StringConstraints(max_length=REPLY_MAX)] = ''


class CommandMessage(Strict):
    type: Literal['command']
    name: Literal['new_conversation', 'end_session']
    conversation_id: Token


class CustomerAction(Strict):
    """A button pressed on the counter screen; the staff recognizer owns the transcript and applies it."""
    type: Literal['customer_action']
    action: Literal['undo_word']
    conversation_id: Token


class PingMessage(Strict):
    type: Literal['ping']


StaffMessage = TypeAdapter(Annotated[Union[SignalMessage, DisplayState, CommandMessage, PingMessage], Field(discriminator='type')])
DeviceMessage = TypeAdapter(Annotated[Union[SignalMessage, CustomerAction, PingMessage], Field(discriminator='type')])
