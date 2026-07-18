"""Day-5: chunking + RAG retrieval and the similarity floor.

Retrieval is tested with a FAKE embedder whose vectors we control, so the search,
tenant-scoping, and the floor are all deterministic and need no network/key."""
import uuid

from app.knowledge.chunk import chunk_document
from app.knowledge.ingest import ingest_text
from app.knowledge.retrieve import format_context, retrieve
from app.models import Tenant

# ---- chunking (pure) -------------------------------------------------------


def test_chunk_splits_on_headings_into_small_units():
    doc = (
        "# Hours\nMon-Fri 5pm-11pm. Sat-Sun 10am-11pm.\n\n"
        "# Dietary\nWe have 6 vegan dishes and mark all allergens.\n\n"
        "Parking\nValet available from 6pm.\n"
    )
    chunks = chunk_document(doc)
    titles = [c.title for c in chunks]
    assert "Hours" in titles
    assert "Dietary" in titles
    assert "Parking" in titles
    # each fact is its own small chunk, not one big blob
    hours = next(c for c in chunks if c.title == "Hours")
    assert "Mon-Fri" in hours.content
    assert "vegan" not in hours.content  # not bleeding across sections


def test_base_title_is_prefixed():
    chunks = chunk_document("# Hours\n9-5\n", base_title="Demo Bistro")
    assert chunks[0].title == "Demo Bistro — Hours"


# ---- a deterministic fake embedder -----------------------------------------


class FakeEmbedder:
    """Topic-based `dim`-length vectors (matching the real column width). Each
    topic maps to one basis dimension; text sharing a topic with the query embeds
    onto the same axis (cosine distance ~0), unrelated text lands on the 'unknown'
    axis (distance ~1). Deterministic, no network."""

    dim = 1024
    TOPICS = {
        0: ("vegan", "vegetarian", "dietary"),
        1: ("open", "5pm", "hours", "close"),
        2: ("wifi", "password", "internet"),
        3: ("park", "parking", "valet"),
    }

    def _vec(self, text: str) -> list[float]:
        t = text.lower()
        v = [0.0] * self.dim
        for idx, words in self.TOPICS.items():
            if any(w in t for w in words):
                v[idx] = 1.0
        if not any(v):
            v[self.dim - 1] = 1.0  # "unknown" axis, orthogonal to every topic
        return v

    async def embed(self, texts, *, input_type):
        return [self._vec(t) for t in texts]

    async def embed_query(self, text):
        return self._vec(text)

    async def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    async def aclose(self):
        return None


# ---- retrieval + floor -----------------------------------------------------


async def _seed_kb(session) -> Tenant:
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="KB Test")
    session.add(tenant)
    await session.flush()
    await ingest_text(
        session,
        tenant_id=tenant.id,
        source="facts",
        text="# Hours\nWe open at 5pm daily.\n\n# Vegan\nSix vegan dishes available.\n",
        embedder=FakeEmbedder(),
    )
    return tenant


async def test_retrieval_returns_relevant_chunk(session):
    tenant = await _seed_kb(session)
    hits = await retrieve(
        session, tenant_id=tenant.id, query="do you have vegan food?",
        embedder=FakeEmbedder(), max_distance=0.5,
    )
    assert hits, "expected a relevant chunk"
    assert "vegan" in hits[0].content.lower()
    assert "vegan" in format_context(hits).lower()


async def test_floor_rejects_irrelevant(session):
    tenant = await _seed_kb(session)
    # 'wifi' topic isn't in the KB → every chunk is on a different axis → the
    # floor rejects them all, so the concierge will defer to the team.
    hits = await retrieve(
        session, tenant_id=tenant.id, query="what is the wifi password?",
        embedder=FakeEmbedder(), max_distance=0.5,
    )
    assert hits == []


async def test_retrieval_is_tenant_scoped(session):
    t1 = await _seed_kb(session)
    t2 = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="Other")
    session.add(t2)
    await session.flush()
    # t2 has no KB — even a perfect query returns nothing for it.
    hits = await retrieve(
        session, tenant_id=t2.id, query="vegan", embedder=FakeEmbedder(),
        max_distance=0.5,
    )
    assert hits == []
    # ...while t1 still finds it.
    hits1 = await retrieve(
        session, tenant_id=t1.id, query="vegan", embedder=FakeEmbedder(),
        max_distance=0.5,
    )
    assert hits1
