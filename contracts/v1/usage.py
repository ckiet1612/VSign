"""Usage reports: one aggregated summary per conversation at the counter. Counts and word labels only:
no video, no images, no free text, nothing that identifies the customer."""
from datetime import date, datetime, timedelta
from typing import Annotated, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from contracts.v1.sales_vocabulary import SALES_30_LABELS

USAGE_API_VERSION = '1'
MAX_CONVERSATION = timedelta(hours=12)
MAX_COUNT = 5000

# Retail situations from the MRD (F06/F08). A word belongs to exactly one group; greetings and courtesy words
# do not make a conversation about anything, so a conversation counts towards every other group it touches.
SCENARIOS = (
    ('product', 'Tìm và hỏi sản phẩm', ('Muốn', 'Mua', 'Cho', 'Xem', 'Cần', 'Siêu thị', 'Điện thoại', 'Laptop', 'Tivi',
                                        'Tủ lạnh', 'Máy giặt', 'Nồi cơm điện', 'Gạo', 'Sữa', 'Cà phê')),
    ('price', 'Giá và so sánh', ('Rẻ', 'Đắt', 'Mới', 'Cũ', 'Thử', 'Sử dụng')),
    ('payment', 'Thanh toán và giao dịch', ('Ngân hàng', 'Mua bán', 'Cung cấp')),
    ('return', 'Đổi trả và thay đổi', ('Thay đổi', 'Từ chối')),
    ('courtesy', 'Chào hỏi và lịch sự', ('Chào', 'Cảm ơn', 'Tôi', 'Có')),
)
SCENARIO_OF = {label: key for key, _, labels in SCENARIOS for label in labels}
assert set(SCENARIO_OF) == set(SALES_30_LABELS), 'Mỗi nhãn Sales30 phải thuộc đúng một nhóm tình huống'

Count = Annotated[int, Field(ge=0, le=MAX_COUNT)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ConversationSummaryRequest(Strict):
    id: UUID
    started_at: datetime
    ended_at: datetime
    channel: Literal['counter', 'same_screen']
    display_id: Optional[Annotated[str, StringConstraints(min_length=1, max_length=36)]] = None
    words: Count
    uncertain: Count
    failed: Count
    staff_undos: Count
    customer_undos: Count
    replies: Count
    voice_replies: Count
    labels: Dict[Label, Count] = Field(default_factory=dict, max_length=64)
    undone_labels: Dict[Label, Count] = Field(default_factory=dict, max_length=64)

    @field_validator('started_at', 'ended_at')
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError('Thời gian phải có múi giờ')
        return value

    @model_validator(mode='after')
    def consistent(self):
        if self.ended_at < self.started_at or self.ended_at - self.started_at > MAX_CONVERSATION:
            raise ValueError('Khoảng thời gian cuộc hội thoại không hợp lệ')
        if self.voice_replies > self.replies:
            raise ValueError('Số câu trả lời bằng giọng nói vượt tổng số câu trả lời')
        if (self.channel == 'counter') != (self.display_id is not None):
            raise ValueError('Chỉ cuộc hội thoại qua màn hình quầy mới có display_id')
        return self


class ConversationSummaryResponse(Strict):
    api_version: Literal['1'] = USAGE_API_VERSION
    id: UUID
    status: Literal['recorded', 'duplicate']


class UsageTotals(Strict):
    conversations: int
    counter_conversations: int
    words: int
    avg_words: float
    avg_duration_seconds: float
    replies: int
    voice_replies: int
    uncertain: int
    failed: int
    undos: int
    customer_undos: int
    unhandled_conversations: int


class UsageDay(Strict):
    date: date
    conversations: int
    words: int
    unhandled: int


class UsageScenario(Strict):
    id: str
    label: str
    conversations: int
    words: int


class UsageLabelCount(Strict):
    label: str
    count: int


class UsageUnhandled(Strict):
    no_word: int
    mostly_unclear: int
    undone_labels: List[UsageLabelCount]


class UsageReportResponse(Strict):
    api_version: Literal['1'] = USAGE_API_VERSION
    workspace_id: str
    generated_at: datetime
    timezone: Literal['Asia/Ho_Chi_Minh'] = 'Asia/Ho_Chi_Minh'
    days: Literal[7, 30, 90]
    start_date: date
    totals: UsageTotals
    daily: List[UsageDay]
    scenarios: List[UsageScenario]
    top_words: List[UsageLabelCount]
    unhandled: UsageUnhandled
