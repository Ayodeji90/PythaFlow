"""LLM gateway for voice intent extraction and marketing copy.

Uses the Claude API when ANTHROPIC_API_KEY is set (loaded from the repo
root .env). Without a key, both features fall back to rule-based logic
so the demo always runs — the fallback is clearly flagged in responses.
"""

import difflib
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[4] / ".env")

VOICE_MODEL = "claude-haiku-4-5-20251001"      # low latency for spoken turns
MARKETING_MODEL = "claude-sonnet-5"            # best copy quality

_client = None


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


# ---------------------------------------------------------------------------
# Voice intent extraction
# ---------------------------------------------------------------------------

def interpret_voice(transcript: str, menu_names: list[str], today: str) -> dict:
    if llm_available():
        try:
            return _interpret_with_claude(transcript, menu_names, today)
        except Exception:
            pass  # fall through to the rule-based parser
    return _interpret_rule_based(transcript, menu_names, today)


def _interpret_with_claude(transcript: str, menu_names: list[str], today: str) -> dict:
    prompt = f"""You are the voice concierge for Graycliff Restaurant, Nassau.
Today's date is {today}. The menu items are:
{chr(10).join('- ' + n for n in menu_names)}

Interpret the guest's utterance and respond with ONLY a JSON object:
{{"intent": "order" | "reservation" | "unknown",
  "items": [{{"name": "<exact menu item name from the list>", "qty": <int>}}],
  "party_size": <int or null>, "date": "<YYYY-MM-DD or null>", "time": "<HH:MM or null>",
  "guest_name": "<name if stated, else null>",
  "reply": "<one graceful spoken sentence confirming what you understood>"}}

Rules: map dishes to the closest menu item name from the list. Resolve
relative dates ("tomorrow", "Friday") against today's date. If they want
a table, intent is "reservation". Keep the reply short and warm.

Guest said: "{transcript}"
"""
    resp = _get_client().messages.create(
        model=VOICE_MODEL, max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    data = json.loads(text)
    data["engine"] = "claude"
    return data


def _interpret_rule_based(transcript: str, menu_names: list[str], today: str) -> dict:
    """Keyword parser — keeps the demo alive without an API key."""
    lower = transcript.lower()
    is_reservation = bool(re.search(r"\b(book|reserve|reservation|table for)\b", lower))

    # How many menu items each significant word appears in — a word that is
    # unique to one dish ("thermidor", "wagyu") can identify it alone.
    word_freq: dict[str, int] = {}
    for name in menu_names:
        for w in set(re.split(r"[^a-z0-9]+", name.lower().replace("'", ""))):
            if len(w) > 3:
                word_freq[w] = word_freq.get(w, 0) + 1

    items = []
    for name in menu_names:
        simple = name.lower().replace("'", "")
        words = [w for w in re.split(r"[^a-z0-9]+", simple) if len(w) > 3]
        hits = [w for w in words if w in lower]
        unique_hit = any(len(w) >= 5 and word_freq.get(w, 0) == 1 for w in hits)
        if not (simple in lower or len(hits) >= 2
                or (len(words) == 1 and hits) or unique_hit):
            continue
        anchor = hits[0] if hits else words[0]
        qty_match = re.search(r"(\d+|two|three|four)\s+(?:\w+\s+){0,3}" + re.escape(anchor), lower)
        qty_map = {"two": 2, "three": 3, "four": 4}
        qty = 1
        if qty_match:
            token = qty_match.group(1)
            qty = qty_map.get(token, int(token) if token.isdigit() else 1)
        items.append({"name": name, "qty": qty})
    if not items:
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
    tm = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(pm|p\.m\.|am|a\.m\.)?", lower)
    if tm and (tm.group(3) or tm.group(2)):
        hour = int(tm.group(1)) % 12 + (12 if "p" in (tm.group(3) or "") else 0)
        when_time = f"{hour:02d}:{tm.group(2) or '00'}"

    if is_reservation:
        reply = f"Certainly — a table for {party or 2}"
        reply += f" on {when_date}" if when_date else ""
        reply += f" at {when_time}" if when_time else ""
        reply += ". We look forward to welcoming you."
    elif items:
        listed = ", ".join(f"{i['qty']} {i['name']}" for i in items)
        reply = f"With pleasure — {listed}. The kitchen has been notified."
    else:
        reply = "I'm sorry, I didn't quite catch that. Could you name the dish or say 'book a table'?"

    return {
        "intent": "reservation" if is_reservation else ("order" if items else "unknown"),
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
    if llm_available():
        try:
            return _marketing_with_claude(channel, topic, tone, context)
        except Exception:
            pass
    return _marketing_template(channel, topic, context)


def _marketing_with_claude(channel: str, topic: str | None, tone: str, context: dict) -> dict:
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
    resp = _get_client().messages.create(
        model=MARKETING_MODEL, max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    data = json.loads(text)
    data["engine"] = "claude"
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
