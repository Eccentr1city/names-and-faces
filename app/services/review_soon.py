"""Flag cards for early review in Anki after a person's details change.

Re-importing an updated .apkg preserves Anki's scheduling, which is normally
what we want. But when a person's name, photo, or context changes, the cards
that test that information are effectively new material and should come up
soon. Anki's importer cannot reschedule existing cards, so instead we:

1. Record which card types are affected on the Person (``review_soon_cards``).
2. Tag those notes on export (``nf::review-soon::<card>``). Tags on existing
   notes are updated when the deck is re-imported.
3. Let the user bring the cards forward, either automatically through
   AnkiConnect or by pasting a search string into Anki's browser and using
   "Set Due Date".
"""

# (key, Anki template ordinal (1-based), template name), in the order the
# templates are defined in deck_generator._build_model.
CARD_TYPES: list[tuple[str, int, str]] = [
    ("face_to_name", 1, "Face to Name"),
    ("name_to_face", 2, "Name to Face"),
    ("name_face_to_context", 3, "Name and Face to Context"),
    ("context_to_person", 4, "Context to Person"),
]

CARD_KEYS: list[str] = [key for key, _, _ in CARD_TYPES]

CARD_LABELS: dict[str, str] = {
    "face_to_name": "Face → Name",
    "name_to_face": "Name → Face",
    "name_face_to_context": "Name + Face → Context",
    "context_to_person": "Context → Person",
}

# Which cards actually test a given field, as question or answer. Context is
# shown on the back of every card, but only cards 3 and 4 quiz it.
FIELD_TO_CARDS: dict[str, list[str]] = {
    "name": CARD_KEYS,
    "face": CARD_KEYS,
    "context": ["name_face_to_context", "context_to_person"],
}

TAG_ROOT = "nf::review-soon"


def tag_for(card_key: str) -> str:
    return f"{TAG_ROOT}::{card_key}"


def cards_for_changes(changed_fields: list[str]) -> list[str]:
    """Card keys affected by a change to the given fields, in template order."""
    affected = {c for f in changed_fields for c in FIELD_TO_CARDS.get(f, [])}
    return [k for k in CARD_KEYS if k in affected]


def merge_cards(existing: list[str], new: list[str]) -> list[str]:
    wanted = set(existing) | set(new)
    return [k for k in CARD_KEYS if k in wanted]


def anki_search() -> str:
    """Anki browser search matching exactly the flagged cards.

    Each card type is matched by its own tag plus the template ordinal, so a
    context-only change does not pull in that person's Face -> Name card.
    """
    clauses = [f"(tag:{tag_for(key)} card:{ordinal})" for key, ordinal, _ in CARD_TYPES]
    return " OR ".join(clauses)
