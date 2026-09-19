"""Reconcile the app's people with the Anki deck through AnkiConnect.

The .apkg export is the source of truth for card content, but things also
happen on the Anki side: cards get suspended when someone should go, context
lines get fixed mid-review, notes for trashed people linger. This module reads
one snapshot of the deck (notes + cards) and derives:

* stale notes      -- notes that match no active person (by name or photo)
* to_trash         -- active people whose note is fully suspended or gone
* edits            -- fields changed in Anki more recently than in the app
* stats            -- per-person review counts for sorting the grid

and implements "Push to Anki": export, import, reschedule flagged cards,
suspend notes of trashed people, record the sync time, and trigger AnkiWeb sync.
"""

import os
import shutil
import tempfile
import time
from datetime import datetime, timezone

from app import db
from app.models import Person
from app.services import ankiconnect as ac
from app.services.deck_generator import generate_deck
from app.services.review_soon import CARD_TYPES

# Anki card ordinals are 0-based; CARD_TYPES lists 1-based template numbers.
_ORD_BY_KEY = {key: ordinal - 1 for key, ordinal, _ in CARD_TYPES}

# Anki card types: 0 new, 1 learning, 2 review, 3 relearning. Queue -1 = suspended.
_SUSPENDED = -1
_NEW = 0
_REVIEW = 2

_CACHE_TTL = 20.0
_cache: dict = {"at": 0.0, "notes": None}


class AnkiSyncError(Exception):
    pass


# --- snapshot ----------------------------------------------------------------


def invalidate() -> None:
    _cache["notes"] = None


def snapshot(force: bool = False) -> list[dict]:
    """Deck notes with their cards' scheduling state. Cached for a few seconds."""
    fresh = _cache["notes"] is not None and time.time() - _cache["at"] < _CACHE_TTL
    if fresh and not force:
        return _cache["notes"]

    notes = ac.deck_notes()
    card_ids = [cid for n in notes for cid in n["card_ids"]]
    by_id = {c["cardId"]: c for c in ac.cards_info(card_ids)}
    for n in notes:
        n["cards"] = [
            {
                "card_id": cid,
                "ord": by_id[cid]["ord"],
                "queue": by_id[cid]["queue"],
                "type": by_id[cid]["type"],
                "interval": by_id[cid]["interval"],
                "lapses": by_id[cid]["lapses"],
                "reps": by_id[cid]["reps"],
            }
            for cid in n["card_ids"]
            if cid in by_id
        ]
    _cache.update(at=time.time(), notes=notes)
    return notes


def match(
    people: list[Person], notes: list[dict]
) -> tuple[dict[str, dict], list[dict]]:
    """Pair notes with people by exact name, else by photo filename.

    Using both means a rename or a photo swap that has not been pushed yet
    still matches. Returns (person_id -> note, unmatched notes).
    """
    by_name = {(p.name or "").strip(): p for p in people}
    by_face = {p.face_filename: p for p in people if p.face_filename}
    matched: dict[str, dict] = {}
    unmatched: list[dict] = []
    for n in notes:
        person = by_name.get(n["name"]) or (
            by_face.get(n["face"]) if n["face"] else None
        )
        if person is not None and person.id not in matched:
            matched[person.id] = n
        else:
            unmatched.append(n)
    return matched, unmatched


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _brief(p: Person) -> dict:
    return {
        "person_id": p.id,
        "name": p.name,
        "context": p.context or "",
        "face": p.face_filename,
    }


# --- status ------------------------------------------------------------------


def status() -> dict:
    notes = snapshot()
    active = Person.active().all()
    trashed = Person.trashed().all()

    matched, unmatched = match(active, notes)
    trashed_matched, orphans = match(trashed, unmatched)
    trashed_note_ids = {n["note_id"] for n in trashed_matched.values()}

    stale = [
        {
            "note_id": n["note_id"],
            "name": n["name"],
            "context": n["context"],
            "in_trash": n["note_id"] in trashed_note_ids,
        }
        for n in unmatched
        if n["note_id"] in trashed_note_ids or n in orphans
    ]

    to_trash: list[dict] = []
    edits: list[dict] = []
    stats: dict[str, dict] = {}
    new_people: list[dict] = []

    for p in active:
        n = matched.get(p.id)
        if n is None:
            if p.anki_synced_at is None:
                new_people.append(_brief(p))
            else:
                to_trash.append({**_brief(p), "reason": "deleted in Anki"})
            continue

        cards = n["cards"]
        all_suspended = bool(cards) and all(c["queue"] == _SUSPENDED for c in cards)
        if all_suspended:
            to_trash.append(
                {**_brief(p), "reason": "suspended in Anki", "note_id": n["note_id"]}
            )

        note_mod = datetime.fromtimestamp(n["mod"], timezone.utc)
        if p.updated_at is None or note_mod > _as_utc(p.updated_at):
            for field, app_val, anki_val in (
                ("name", (p.name or "").strip(), n["name"]),
                ("context", (p.context or "").strip(), n["context"]),
            ):
                if app_val != anki_val:
                    edits.append(
                        {
                            "person_id": p.id,
                            "name": p.name,
                            "field": field,
                            "app": app_val,
                            "anki": anki_val,
                            "anki_mod": note_mod.isoformat(),
                        }
                    )

        review = [
            c["interval"] for c in cards if c["type"] == _REVIEW and c["interval"] > 0
        ]
        stats[p.id] = {
            "cards": len(cards),
            "reps": sum(c["reps"] for c in cards),
            "lapses": sum(c["lapses"] for c in cards),
            "interval": min(review) if review else None,
            "never_seen": bool(cards)
            and all(c["type"] == _NEW and c["reps"] == 0 for c in cards),
            "suspended": all_suspended,
        }

    return {
        "deck_notes": len(notes),
        "stale": stale,
        "to_trash": to_trash,
        "edits": edits,
        "stats": stats,
        "new_people": new_people,
        "flagged": sum(1 for p in active if p.review_soon_list()),
    }


# --- actions -----------------------------------------------------------------


def _reschedule_flagged(
    people: list[Person], matched: dict[str, dict], days: str
) -> tuple[list[int], list[Person]]:
    """Bring forward exactly the card types flagged on each person, then clear
    the flags of everyone whose note was found. Does not commit."""
    cards: list[int] = []
    found: list[Person] = []
    for p in people:
        keys = p.review_soon_list()
        n = matched.get(p.id) if keys else None
        if not n:
            continue
        ords = {_ORD_BY_KEY[k] for k in keys if k in _ORD_BY_KEY}
        cards += [c["card_id"] for c in n["cards"] if c["ord"] in ords]
        found.append(p)
    if cards:
        if days == "forget":
            ac.forget_cards(cards)
        else:
            ac.set_due_date(cards, days)
    for p in found:
        p.review_soon_cards = ""
    return cards, found


def reschedule_flagged(days: str = "0") -> tuple[int, int]:
    """Reschedule flagged cards without importing (for decks imported by hand).
    Returns (cards, people)."""
    people = Person.active().all()
    matched, _ = match(people, snapshot(force=True))
    cards, found = _reschedule_flagged(people, matched, days)
    db.session.commit()
    invalidate()
    return len(cards), len(found)


def push(days: str = "0") -> dict:
    """Export, import into Anki, reschedule flagged cards, suspend notes of
    trashed people, stamp the sync time, and sync with AnkiWeb."""
    people = Person.active().all()
    new_count = sum(1 for p in people if p.anki_synced_at is None)

    tmpdir = tempfile.mkdtemp(prefix="names-and-faces-")
    path = os.path.join(tmpdir, "names_and_faces.apkg")
    try:
        generate_deck(people, path)
        if not ac.import_package(path):
            raise AnkiSyncError("Anki reported that the package import failed.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    notes = snapshot(force=True)
    matched, unmatched = match(people, notes)

    resched_cards, flagged_people = _reschedule_flagged(people, matched, days)

    # Suspend (never delete) notes belonging to people in the trash.
    trashed_matched, _ = match(Person.trashed().all(), unmatched)
    suspend_cards = [
        c["card_id"]
        for n in trashed_matched.values()
        for c in n["cards"]
        if c["queue"] != _SUSPENDED
    ]
    ac.suspend_cards(suspend_cards)

    now = datetime.now(timezone.utc)
    for p in people:
        p.anki_synced_at = now
    db.session.commit()
    invalidate()

    sync_error = None
    try:
        ac.sync()
    except ac.AnkiConnectError as e:
        sync_error = str(e)

    return {
        "people": len(people),
        "new": new_count,
        "rescheduled_people": len(flagged_people),
        "rescheduled_cards": len(resched_cards),
        "suspended_people": len(trashed_matched),
        "suspended_cards": len(suspend_cards),
        "days": days,
        "sync_error": sync_error,
    }


def apply_edits(requested: list[dict]) -> int:
    """Copy Anki's newer field values into the app for the requested (person, field) pairs."""
    wanted = {(e.get("person_id"), e.get("field")) for e in requested}
    applied = 0
    for e in status()["edits"]:
        if (e["person_id"], e["field"]) not in wanted:
            continue
        person = Person.query.get(e["person_id"])
        if person is None:
            continue
        setattr(person, e["field"], e["anki"])
        person.touch()
        applied += 1
    db.session.commit()
    invalidate()
    return applied


def trash_people(person_ids: list[str]) -> int:
    """Move to the trash only people the status currently proposes for it."""
    allowed = {t["person_id"] for t in status()["to_trash"]}
    ids = set(person_ids) & allowed
    now = datetime.now(timezone.utc)
    for p in Person.active().filter(Person.id.in_(ids)).all():
        p.deleted_at = now
        p.review_soon_cards = ""
    db.session.commit()
    return len(ids)


def act_on_stale(action: str, note_ids: list[int]) -> int:
    """Suspend or delete notes, restricted to those currently stale."""
    allowed = {s["note_id"] for s in status()["stale"]}
    ids = sorted(set(note_ids) & allowed)
    if not ids:
        return 0
    notes = {n["note_id"]: n for n in snapshot()}
    if action == "delete":
        ac.delete_notes(ids)
    else:
        ac.suspend_cards(
            [
                c["card_id"]
                for i in ids
                for c in notes[i]["cards"]
                if c["queue"] != _SUSPENDED
            ]
        )
    invalidate()
    return len(ids)
