"""Knowledge retrieval + voice intent classification.

These lock down the exact failure modes found in review:
  · questions being cooked as orders ("what pairs with the lobster?")
  · vintage years read as quantities ("the 2015 margaux" → qty 2015)
  · silent wrong-time reservations ("table for 4 at 8pm" → time lost)
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MenuItem
from app.seed import seed_knowledge_if_empty
from app.services import knowledge
from app.services.llm import _interpret_rule_based

def make_menu() -> list[MenuItem]:
    """Fresh instances per test — ORM objects must not span sessions."""
    return [
        MenuItem(id=1, name="Grilled Bahamian Lobster Thermidor", category="Main",
                 price=97.5, cost=30, tags="lobster,seafood,signature",
                 description="Whole local lobster, thermidor glaze", pairing_item_id=3),
        MenuItem(id=2, name="Wagyu Beef Tenderloin A5", category="Main",
                 price=145, cost=52, tags="wagyu,beef,premium",
                 description="Japanese A5 wagyu, truffle jus"),
        MenuItem(id=3, name="Chablis Grand Cru (glass)", category="Wine",
                 price=26, cost=9, tags="wine,white,glass",
                 description="Les Clos, mineral and precise"),
        MenuItem(id=4, name="Chateau Margaux 2015", category="Wine",
                 price=950, cost=400, tags="wine,red,premium",
                 description="Premier Grand Cru Classé, Margaux"),
        # Distractor: also contains "lobster" but is a starter without a
        # pairing — "the lobster" must resolve to the Thermidor, not this.
        MenuItem(id=5, name="Caribbean Lobster Bisque", category="Starter",
                 price=22, cost=6, tags="lobster,soup,seafood",
                 description="Silky lobster bisque, cognac cream"),
    ]


MENU_NAMES = [m.name for m in make_menu()]
TODAY = "2026-07-10"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(make_menu())
    session.commit()
    seed_knowledge_if_empty(session)   # loads the real Graycliff pack
    yield session
    session.close()


# ---------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------

def test_pack_seeded(db):
    assert db.query(knowledge.KnowledgeEntry).count() >= 25


@pytest.mark.parametrize("query,expected_topic", [
    ("what should I wear to dinner", "dress_code"),
    ("is there a dress code?", "dress_code"),
    ("how do I get there from the cruise ship", "getting_here"),
    ("what time do you open for dinner", "dinner_hours"),
    ("can I cancel my booking", "cancellation"),
    ("do you take credit cards", "payment"),
    ("are kids allowed", "children"),
    ("can we tour the wine cellar", "wine_cellar"),
])
def test_search_finds_right_entry(db, query, expected_topic):
    hits = knowledge.search(db, query)
    assert hits, f"no hits for {query!r}"
    assert hits[0][1].topic == expected_topic


def test_core_digest_holds_the_essentials(db):
    digest = knowledge.core_digest(db)
    assert "West Hill Street" in digest
    assert "reservation" in digest.lower()


def test_pairing_question_answers_from_menu(db):
    out = knowledge.answer_question(db, "what pairs with the lobster?")
    assert out["matched"]
    assert "Chablis" in out["reply"]
    assert "Thermidor" in out["reply"]   # not the Bisque distractor


def test_staff_annotations_never_spoken(db):
    out = knowledge.answer_question(db, "is there a dress code?")
    assert out["matched"]
    assert "[" not in out["reply"] and "]" not in out["reply"]
    assert "[" not in knowledge.core_digest(db)


def test_unknown_question_defers_honestly(db):
    out = knowledge.answer_question(db, "do you allow helicopters on the lawn")
    assert not out["matched"]
    assert "242" in out["reply"]   # hands the guest the phone number


# ---------------------------------------------------------------------------
# rule-based intent classification — the review traps
# ---------------------------------------------------------------------------

def test_question_is_not_an_order():
    r = _interpret_rule_based("what pairs with the lobster?", MENU_NAMES, TODAY)
    assert r["intent"] == "question"
    assert r["items"] == []


def test_order_verb_still_orders():
    r = _interpret_rule_based("can I get the wagyu please", MENU_NAMES, TODAY)
    assert r["intent"] == "order"
    assert r["items"][0]["name"] == "Wagyu Beef Tenderloin A5"


def test_bare_mention_orders():
    r = _interpret_rule_based("two lobster thermidor please", MENU_NAMES, TODAY)
    assert r["intent"] == "order"
    assert r["items"][0]["qty"] == 2


def test_vintage_year_is_not_a_quantity():
    r = _interpret_rule_based("a bottle of the 2015 margaux please", MENU_NAMES, TODAY)
    assert r["intent"] == "order"
    assert r["items"][0]["qty"] <= 12


def test_reservation_with_digit_party_and_pm_time():
    r = _interpret_rule_based("book a table for 4 at 8pm", MENU_NAMES, TODAY)
    assert r["intent"] == "reservation"
    assert r["party_size"] == 4
    assert r["time"] == "20:00"


def test_reservation_tomorrow_evening():
    r = _interpret_rule_based("book a table for four tomorrow at 8pm", MENU_NAMES, TODAY)
    assert r["party_size"] == 4
    assert r["date"] == "2026-07-11"
    assert r["time"] == "20:00"


def test_hours_question_not_reservation():
    r = _interpret_rule_based("what are your dinner hours?", MENU_NAMES, TODAY)
    assert r["intent"] == "question"
