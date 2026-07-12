"""Voice intent extraction and marketing copy — app-core AI logic.

This module is vendor-blind: it talks to the LLMService interface only
(see llm_service.py) and never imports a provider SDK. Model/provider
choice lives in .env. Without any provider configured, both features
fall back to rule-based logic so the demo always runs — the fallback is
clearly flagged in responses.
"""

import difflib
import json
import re
from datetime import date, timedelta

from .llm_service import get_llm_service


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Voice intent extraction
# ---------------------------------------------------------------------------

def interpret_voice(transcript: str, menu_names: list[str], today: str,
                    knowledge: str = "") -> dict:
    svc = get_llm_service()
    if svc.available():
        try:
            return _interpret_with_llm(svc, transcript, menu_names, today, knowledge)
        except Exception:
            pass  # fall through to the rule-based parser
    return _interpret_rule_based(transcript, menu_names, today)


def _interpret_with_llm(svc, transcript: str, menu_names: list[str], today: str,
                        knowledge: str = "") -> dict:
    knowledge_block = (
        f"\nProperty knowledge (answer questions ONLY from this — if the "
        f"answer isn't here, say you'll check with the team):\n{knowledge}\n"
        if knowledge else ""
    )
    prompt = f"""You are the voice concierge for Graycliff Restaurant, Nassau.
Today's date is {today}. The menu items are:
{chr(10).join('- ' + n for n in menu_names)}
{knowledge_block}
Interpret the guest's utterance and respond with ONLY a JSON object:
{{"intent": "order" | "reservation" | "question" | "unknown",
  "items": [{{"name": "<exact menu item name from the list>", "qty": <int>}}],
  "party_size": <int or null>, "date": "<YYYY-MM-DD or null>", "time": "<HH:MM or null>",
  "guest_name": "<name if stated, else null>",
  "reply": "<one graceful spoken sentence — confirm what you understood, or
            answer the question from the property knowledge>"}}

Rules: map dishes to the closest menu item name from the list. Resolve
relative dates ("tomorrow", "Friday") against today's date. If they want
a table, intent is "reservation". If they are asking about the property,
menu, hours, or policies rather than ordering, intent is "question" and
the reply IS the answer, grounded in the property knowledge above. Keep
the reply short and warm; never invent facts.

Guest said: "{transcript}"
"""
    data = _extract_json(svc.generate(prompt, tier="fast", max_tokens=500))
    data["engine"] = svc.name
    return data


ORDER_VERBS = re.compile(
    r"\b(i'?d like|i would like|can i (?:get|have)|could i (?:get|have)|"
    r"may i have|we'?ll have|i'?ll (?:have|take)|order|bring me|bring us|"
    r"give me|get me|send up)\b")
QUESTION_OPENERS = re.compile(
    r"^(what|when|where|who|why|how|is|are|do|does|did|can you tell|"
    r"could you tell|tell me about|is there|are there)\b")


def _interpret_rule_based(transcript: str, menu_names: list[str], today: str) -> dict:
    """Keyword parser — keeps the demo alive without an API key.

    Intent precedence matters: reservation keywords, then explicit order
    verbs, then question shape, then bare dish mentions. Question must
    outrank bare mentions so "what pairs with the lobster?" is answered,
    not cooked.
    """
    lower = transcript.lower().strip()
    is_reservation = bool(re.search(r"\b(book|reserve|reservation|table for)\b", lower))
    is_order_phrase = bool(ORDER_VERBS.search(lower))
    is_question = (not is_reservation and not is_order_phrase
                   and bool(QUESTION_OPENERS.match(lower) or "?" in lower))

    # How many menu items each significant word appears in — a word that is
    # unique to one dish ("thermidor", "wagyu") can identify it alone.
    word_freq: dict[str, int] = {}
    for name in menu_names:
        for w in set(re.split(r"[^a-z0-9]+", name.lower().replace("'", ""))):
            if len(w) > 3:
                word_freq[w] = word_freq.get(w, 0) + 1

    items = []
    if not is_question:
        for name in menu_names:
            simple = name.lower().replace("'", "")
            words = [w for w in re.split(r"[^a-z0-9]+", simple) if len(w) > 3]
            hits = [w for w in words if w in lower]
            unique_hit = any(len(w) >= 5 and word_freq.get(w, 0) == 1 for w in hits)
            if not (simple in lower or len(hits) >= 2
                    or (len(words) == 1 and hits) or unique_hit):
                continue
            anchor = hits[0] if hits else words[0]
            # qty sits directly before the dish words; a bare year like
            # "2015 margaux" must not read as quantity — cap at 12.
            qty_match = re.search(r"\b(\d{1,2}|two|three|four|five|six)\s+(?:\w+\s+){0,3}"
                                  + re.escape(anchor), lower)
            qty_map = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
            qty = 1
            if qty_match:
                token = qty_match.group(1)
                qty = qty_map.get(token, int(token) if token.isdigit() else 1)
                qty = max(1, min(qty, 12))
            items.append({"name": name, "qty": qty})
        if not items and not is_reservation:
            # fuzzy last resort against distinctive words
            for name in menu_names:
                key = name.lower().split()[0]
                if len(key) > 4 and difflib.get_close_matches(key, lower.split(), cutoff=0.85):
                    items.append({"name": name, "qty": 1})
                    break

    party = None
    m = re.search(r"(?:table for|party of|for)\s+(\d+|two|three|four|five|six)", lower)
    if m:
        party = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}.get(
            m.group(1), int(m.group(1)) if m.group(1).isdigit() else None)

    when_date = None
    base = date.fromisoformat(today)
    if "tomorrow" in lower:
        when_date = (base + timedelta(days=1)).isoformat()
    elif "tonight" in lower or "today" in lower:
        when_date = base.isoformat()

    when_time = None
    # First number carrying am/pm or minutes wins — "table for 4 at 8pm"
    # must read the 8, not the 4.
    for tm in re.finditer(r"(\d{1,2})(?::(\d{2}))?\s*(pm|p\.m\.|am|a\.m\.)", lower):
        hour = int(tm.group(1)) % 12 + (12 if "p" in tm.group(3) else 0)
        when_time = f"{hour:02d}:{tm.group(2) or '00'}"
        break
    if when_time is None:
        at = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", lower)
        if at:
            hour = int(at.group(1))
            if 1 <= hour <= 11:      # bare "at 8" at a dinner house means evening
                hour += 12
            when_time = f"{hour:02d}:{at.group(2) or '00'}"

    if is_reservation:
        intent = "reservation"
        reply = f"Certainly — a table for {party or 2}"
        reply += f" on {when_date}" if when_date else ""
        reply += f" at {when_time}" if when_time else ""
        reply += ". We look forward to welcoming you."
    elif is_question:
        intent = "question"
        reply = ""  # the voice router fills this from the knowledge base
    elif items:
        intent = "order"
        listed = ", ".join(f"{i['qty']} {i['name']}" for i in items)
        reply = f"With pleasure — {listed}. The kitchen has been notified."
    else:
        intent = "unknown"
        reply = "I'm sorry, I didn't quite catch that. Could you name the dish, ask about the house, or say 'book a table'?"

    return {
        "intent": intent,
        "items": items, "party_size": party, "date": when_date, "time": when_time,
        "guest_name": None, "reply": reply, "engine": "rules",
    }


# ---------------------------------------------------------------------------
# Marketing copy
# ---------------------------------------------------------------------------

BRAND_VOICE = (
    "Graycliff Hotel & Restaurant: a 1740s Nassau mansion, the Caribbean's "
    "first five-star restaurant, a legendary 250,000-bottle wine cellar, an "
    "on-site chocolatier and cigar factory. Voice: elegant, warm, storied — "
    "never gimmicky, no exclamation marks, no hashtag spam (2-3 tasteful tags at most)."
)


def generate_marketing(channel: str, topic: str | None, tone: str, context: dict) -> dict:
    svc = get_llm_service()
    if svc.available():
        try:
            return _marketing_with_llm(svc, channel, topic, tone, context)
        except Exception:
            pass
    return _marketing_template(channel, topic, context)


def _marketing_with_llm(svc, channel: str, topic: str | None, tone: str, context: dict) -> dict:
    prompt = f"""{BRAND_VOICE}

Write one {channel} piece for Graycliff Restaurant.
Tone: {tone}. {"Topic: " + topic if topic else "Choose the strongest angle from the data."}

Live restaurant data:
- Best sellers this week: {", ".join(context["best_sellers"])}
- Upcoming events: {"; ".join(context["events"]) or "none listed"}
- Season: {context["season"]}
- Signature experiences: wine-cellar dinners, chocolate atelier, hand-rolled cigars

Respond with ONLY JSON: {{"title": "<subject line or hook, under 80 chars>",
"body": "<the piece: 60-120 words for social, 120-180 for email>"}}"""
    data = _extract_json(svc.generate(prompt, tier="quality", max_tokens=700))
    data["engine"] = svc.name
    return data


def _marketing_template(channel: str, topic: str | None, context: dict) -> dict:
    best = context["best_sellers"][0] if context["best_sellers"] else "our tasting menu"
    event = context["events"][0] if context["events"] else None
    season = context["season"]

    if channel == "email":
        title = topic or f"An evening at Graycliff — {season} at West Hill Street"
        body = (
            f"Dear friend of Graycliff,\n\n"
            f"The {season} season has settled over Nassau, and our kitchen is at its best. "
            f"Guests this week have returned again and again to the {best} — we suggest "
            f"pairing it with a pour from our 250,000-bottle cellar.\n\n"
            + (f"Mark your calendar: {event}. Seats are limited.\n\n" if event else "")
            + "Reserve your table on West Hill Street, or simply reply to this note.\n\n"
            f"— The Graycliff family"
        )
    else:
        title = topic or f"{season} evenings at Graycliff"
        body = (
            f"Candlelight in a 1740s mansion. The {best}, and a cellar of 250,000 stories. "
            + (f"{event} — join us. " if event else "")
            + f"Reservations at the link in bio. #Graycliff #Nassau"
        )
    return {"title": title, "body": body, "engine": "template"}
