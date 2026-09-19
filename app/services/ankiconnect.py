"""Minimal client for the AnkiConnect add-on (https://git.foosoft.net/alex/anki-connect).

Optional: if Anki desktop is running on this machine with AnkiConnect installed,
flagged cards can be rescheduled directly instead of via a manual search.
Set ANKICONNECT_URL to override the default endpoint.
"""

import html
import os
import re

import requests

URL = os.environ.get("ANKICONNECT_URL", "http://127.0.0.1:8765")


class AnkiConnectError(Exception):
    pass


def _invoke(action: str, **params: object) -> object:
    try:
        resp = requests.post(
            URL,
            json={"action": action, "version": 6, "params": params},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise AnkiConnectError(f"Could not reach AnkiConnect at {URL}: {e}") from e
    if data.get("error"):
        raise AnkiConnectError(str(data["error"]))
    return data.get("result")


def is_available() -> bool:
    """True only if something that identifies itself as AnkiConnect answers.

    A plain GET to AnkiConnect returns a short "AnkiConnect v.N" page. Checking
    for that string avoids false positives when another app holds the port.
    """
    try:
        resp = requests.get(URL, timeout=1)
        resp.raise_for_status()
        return "AnkiConnect" in resp.text[:200]
    except requests.RequestException:
        return False


def reschedule(query: str, days: str = "0") -> int:
    """Bring forward every card matching ``query``. Returns the card count.

    ``days`` uses Anki's "Set Due Date" syntax ("0" = today, "1" = tomorrow,
    "0-2" = random within range, suffix "!" also resets the interval).
    The special value "forget" resets the cards to new instead.
    """
    cards = _invoke("findCards", query=query)
    if not isinstance(cards, list) or not cards:
        return 0
    if days == "forget":
        _invoke("forgetCards", cards=cards)
    else:
        _invoke("setDueDate", cards=cards, days=days)
    return len(cards)


DECK_NAME = "Names and Faces"

_IMG_SRC_RE = re.compile(r'src="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")


def _field(note: dict, name: str) -> str:
    return note.get("fields", {}).get(name, {}).get("value", "")


def deck_notes() -> list[dict]:
    """Notes in the Names and Faces deck: id, plain-text name, face filename, context."""
    ids = _invoke("findNotes", query=f'"deck:{DECK_NAME}"')
    if not ids:
        return []
    info = _invoke("notesInfo", notes=ids)
    notes = []
    for n in info or []:
        face_match = _IMG_SRC_RE.search(_field(n, "Face"))
        notes.append(
            {
                "note_id": n["noteId"],
                "name": html.unescape(_TAG_RE.sub("", _field(n, "Name"))).strip(),
                "face": face_match.group(1) if face_match else "",
                "context": html.unescape(_TAG_RE.sub("", _field(n, "Context"))).strip(),
            }
        )
    return notes


def stale_notes(people: list) -> list[dict]:
    """Deck notes with no matching person in the app.

    A note matches a person if either the name or the photo filename agrees, so
    a rename or a photo swap that has not been imported yet is not reported.
    Importing never deletes, so these are usually people removed from the app.
    """
    names = {(p.name or "").strip() for p in people}
    faces = {p.face_filename for p in people if p.face_filename}
    return [
        n
        for n in deck_notes()
        if n["name"] not in names and (not n["face"] or n["face"] not in faces)
    ]


def delete_notes(note_ids: list[int]) -> None:
    _invoke("deleteNotes", notes=note_ids)


def suspend_notes(note_ids: list[int]) -> int:
    """Suspend every card of the given notes. Returns the card count."""
    query = " or ".join(f"nid:{i}" for i in note_ids)
    cards = _invoke("findCards", query=query)
    if not cards:
        return 0
    _invoke("suspend", cards=cards)
    return len(cards)
