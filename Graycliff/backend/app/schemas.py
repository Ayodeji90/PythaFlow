from pydantic import BaseModel, Field


class OrderItemIn(BaseModel):
    item_id: int
    qty: int = Field(ge=1, le=12, default=1)


class KnowledgeIn(BaseModel):
    category: str = Field(pattern="^(property|hours|dining|services|policies|faq)$")
    topic: str = Field(min_length=2, max_length=60)
    question: str = ""
    content: str = Field(min_length=5)
    keywords: str = ""
    priority: int = Field(ge=1, le=10, default=5)
    verified: bool = False


class KnowledgePatch(BaseModel):
    question: str | None = None
    content: str | None = Field(default=None, min_length=5)
    keywords: str | None = None
    priority: int | None = Field(default=None, ge=1, le=10)
    verified: bool | None = None
    active: bool | None = None


class OrderIn(BaseModel):
    items: list[OrderItemIn]
    guest_id: int | None = None
    table_no: int = 1
    covers: int = 2
    channel: str = "qr-menu"


class ReservationIn(BaseModel):
    guest_name: str
    date: str
    time: str
    party_size: int = 2
    guest_id: int | None = None
    source: str = "web"


class SuggestionDecision(BaseModel):
    status: str = Field(pattern="^(accepted|rejected)$")


class MarketingRequest(BaseModel):
    channel: str = "instagram"
    topic: str | None = None
    tone: str = "elegant"


class DraftUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|approved|scheduled)$")


class VoiceUtterance(BaseModel):
    transcript: str
    guest_id: int | None = None
