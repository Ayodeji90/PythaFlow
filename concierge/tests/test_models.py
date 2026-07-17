"""Day-2 guardrail: prove tenant isolation and that model defaults work."""
import uuid

from sqlalchemy import select

from app.models import Conversation, Guest, Tenant
from app.models.enums import ChannelType


async def test_tenant_isolation(session):
    t1 = Tenant(slug=f"t1-{uuid.uuid4().hex[:8]}", name="Alpha")
    t2 = Tenant(slug=f"t2-{uuid.uuid4().hex[:8]}", name="Beta")
    session.add_all([t1, t2])
    await session.flush()

    g1 = Guest(tenant_id=t1.id, display_name="Alpha guest")
    g2 = Guest(tenant_id=t2.id, display_name="Beta guest")
    session.add_all([g1, g2])
    await session.flush()

    # A tenant-scoped query returns ONLY that tenant's rows.
    rows = (
        await session.execute(select(Guest).where(Guest.tenant_id == t1.id))
    ).scalars().all()
    assert [r.id for r in rows] == [g1.id]

    # Trying to reach tenant 2's row through tenant 1's scope returns nothing.
    leaked = (
        await session.execute(
            select(Guest).where(Guest.tenant_id == t1.id, Guest.id == g2.id)
        )
    ).scalar_one_or_none()
    assert leaked is None


async def test_defaults_and_pk(session):
    t = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Gamma")
    session.add(t)
    await session.flush()

    conv = Conversation(tenant_id=t.id, channel_type=ChannelType.webchat)
    session.add(conv)
    await session.flush()
    await session.refresh(conv)

    assert conv.id is not None                 # server-generated UUID pk
    assert conv.status.value == "active"       # enum server default
    assert conv.state == {}                    # jsonb server default
    assert conv.created_at is not None         # timestamp default
