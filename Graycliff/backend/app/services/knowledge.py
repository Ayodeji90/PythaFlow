"""Knowledge base retrieval — the concierge's memory of the house.

Two consumers:
  · prompt assembly — core_digest() puts the always-relevant facts
    (address, hours, dress code, reservations policy) into every LLM turn
  · question answering — search() scores entries against a guest query;
    answer_question() composes a reply from knowledge and the menu, and
    is what the rule-based fallback speaks verbatim

Scoring is deliberately simple keyword/overlap ranking: the corpus is a
few dozen curated entries per restaurant, not the open web. The service
interface (search/answer) is the stable seam — an embedding retriever
can replace the internals later without touching callers.
"""

import re

from sqlalchemy.orm import Session

from ..models import KnowledgeEntry, MenuItem

STOPWORDS = {
    "the", "a", "an", "is", "are", "am", "was", "do", "does", "did", "you",
    "your", "yours", "i", "we", "my", "our", "me", "us", "it", "its", "to",
    "of", "for", "in", "on", "at", "and", "or", "with", "have", "has", "had",
    "can", "could", "would", "should", "will", "there", "any", "some", "what",
    "when", "where", "who", "how", "why", "which", "please", "about", "tell",
    "know", "like", "get", "that", "this", "be", "if", "so",
}

PAIRING_WORDS = ("pair", "pairs", "pairing", "goes with", "go with", "wine with",
                 "drink with", "recommend with")


def _tokens(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in STOPWORDS]


def _guest_safe(text: str) -> str:
    """Strip [bracketed staff annotations] — editors see them, guests never do."""
    return re.sub(r"\s*\[[^\]]*\]", "", text).strip()


def core_digest(db: Session, restaurant_id: str = "graycliff") -> str:
    """Compact always-in-prompt facts: priority >= 8, one line each."""
    rows = (db.query(KnowledgeEntry)
            .filter(KnowledgeEntry.restaurant_id == restaurant_id,
                    KnowledgeEntry.active == 1, KnowledgeEntry.priority >= 8)
            .order_by(KnowledgeEntry.priority.desc()).all())
    return "\n".join(f"- {r.topic.replace('_', ' ')}: {_guest_safe(r.content)}" for r in rows)


def _expand(tokens: set[str]) -> set[str]:
    """Cheap singular/plural folding: 'cards' also matches 'card'."""
    extra = {t[:-1] for t in tokens if t.endswith("s") and len(t) > 3}
    return tokens | extra


def search(db: Session, query: str, restaurant_id: str = "graycliff",
           k: int = 4) -> list[tuple[float, KnowledgeEntry]]:
    """Rank knowledge entries against a guest query."""
    q_tokens = _expand(set(_tokens(query)))
    if not q_tokens:
        return []
    q_lower = query.lower()

    scored: list[tuple[float, KnowledgeEntry]] = []
    rows = (db.query(KnowledgeEntry)
            .filter(KnowledgeEntry.restaurant_id == restaurant_id,
                    KnowledgeEntry.active == 1).all())
    for r in rows:
        keywords = [w.strip() for w in r.keywords.lower().split(",") if w.strip()]
        score = 0.0
        matched: set[str] = set()
        for kw in keywords:
            if " " in kw:                      # multi-word keys match as phrases
                if kw in q_lower:
                    score += 4.0
                    matched |= set(kw.split())
            elif kw in q_tokens:
                score += 3.0
                matched.add(kw)
        # A token that already earned keyword credit must not also earn
        # overlap credit — otherwise "…dinner" drags hours above dress code.
        rest = q_tokens - matched
        score += 2.0 * len(rest & set(_tokens(r.question)))
        score += 1.5 * len(rest & set(_tokens(r.topic)))
        score += 0.5 * len(rest & set(_tokens(r.content)))
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].priority))
    return scored[:k]


def menu_answer(db: Session, query: str) -> str | None:
    """Answer menu-shaped questions (pairing, price, what's in it) directly."""
    q_lower = query.lower()
    q_tokens = set(_tokens(query))
    is_pairing = any(w in q_lower for w in PAIRING_WORDS)
    items = db.query(MenuItem).filter(MenuItem.active == 1).all()

    # "The lobster" is ambiguous (bisque? thermidor?). Prefer mains, and on
    # pairing questions prefer dishes that actually carry a pairing.
    best, best_score = None, 0.0
    for m in items:
        hits = len(q_tokens & set(_tokens(m.name)))
        if hits == 0:
            continue
        score = float(hits)
        if m.category in ("Main", "Tasting"):
            score += 0.25
        if is_pairing and m.pairing_item_id:
            score += 0.5
        if score > best_score:
            best, best_score = m, score
    if not best:
        return None

    if any(w in q_lower for w in PAIRING_WORDS):
        if best.pairing_item_id:
            wine = db.get(MenuItem, best.pairing_item_id)
            if wine:
                return (f"With the {best.name}, the sommelier suggests the "
                        f"{wine.name} (${wine.price:.0f}).")
        return (f"For the {best.name}, ask our sommelier tableside — "
                f"the cellar rarely disappoints.")
    if any(w in q_tokens for w in ("price", "cost", "much")):
        return f"The {best.name} is ${best.price:.0f}."
    # generic dish question → describe it
    return f"The {best.name} — {best.description}. ${best.price:.0f}."


def answer_question(db: Session, query: str,
                    restaurant_id: str = "graycliff") -> dict:
    """Compose the fallback-spoken answer; also used as tool output."""
    from_menu = menu_answer(db, query)
    hits = search(db, query, restaurant_id)

    if from_menu and (not hits or hits[0][0] < 3.0 or
                      any(w in query.lower() for w in PAIRING_WORDS)):
        return {"reply": from_menu, "source": "menu", "matched": True}
    if hits:
        top = hits[0][1]
        return {"reply": _guest_safe(top.content), "source": f"knowledge:{top.topic}",
                "matched": True}
    return {
        "reply": ("I don't want to guess on that one — our team at "
                  "+1 242 302 9150 will have the exact answer. Is there "
                  "anything else I can help you with?"),
        "source": "none", "matched": False,
    }


def retrieved_context(db: Session, query: str,
                      restaurant_id: str = "graycliff") -> str:
    """Top entries formatted for the LLM prompt."""
    hits = search(db, query, restaurant_id)
    return "\n".join(f"- ({r.category}/{r.topic}) {_guest_safe(r.content)}" for _, r in hits)
