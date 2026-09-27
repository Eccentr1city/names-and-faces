"""Minimal client for the AnkiConnect add-on (https://git.foosoft.net/alex/anki-connect).

Optional: if Anki desktop is running on this machine with AnkiConnect installed,
the app can push decks, reschedule cards, and reconcile notes directly. Set
ANKICONNECT_URL to override the default endpoint, and ANKICONNECT_API_KEY if the
add-on has an apiKey configured (needed when reaching it over the network). Higher-level logic lives in
anki_sync.py; this module is a thin wrapper over individual actions.
"""

import html
import os
import re

import requests

URL = os.environ.get("ANKICONNECT_URL", "http://127.0.0.1:8765")
API_KEY = os.environ.get("ANKICONNECT_API_KEY")
DECK_NAME = "Names and Faces"

_IMG_SRC_RE = re.compile(r'src="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")


class AnkiConnectError(Exception):
    pass


def _invoke(action: str, timeout: int = 30, **params: object) -> object:
    payload = {"action": action, "version": 6, "params": params}
    if API_KEY:
        payload["key"] = API_KEY
    try:
        resp = requests.post(
            URL,
            json=payload,
            timeout=timeout,
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


# --- deck contents -----------------------------------------------------------


def _plain(value: str) -> str:
    return html.unescape(_TAG_RE.sub("", value)).strip()


def deck_notes() -> list[dict]:
    """Notes in the Names and Faces deck with plain-text fields and card ids."""
    ids = _invoke("findNotes", query=f'"deck:{DECK_NAME}"')
    if not ids:
        return []
    notes = []
    for n in _invoke("notesInfo", notes=ids) or []:
        fields = n.get("fields", {})
        face = _IMG_SRC_RE.search(fields.get("Face", {}).get("value", ""))
        notes.append(
            {
                "note_id": n["noteId"],
                "mod": n.get("mod", 0),
                "tags": n.get("tags", []),
                "name": _plain(fields.get("Name", {}).get("value", "")),
                "face": face.group(1) if face else "",
                "context": _plain(fields.get("Context", {}).get("value", "")),
                "card_ids": n.get("cards", []),
            }
        )
    return notes


def cards_info(card_ids: list[int]) -> list[dict]:
    if not card_ids:
        return []
    return _invoke("cardsInfo", timeout=120, cards=card_ids) or []


# --- mutations ---------------------------------------------------------------


def import_package(path: str) -> bool:
    """Import an .apkg from a path readable by Anki (same machine)."""
    return bool(_invoke("importPackage", timeout=300, path=path))


def sync() -> None:
    _invoke("sync", timeout=300)


def set_due_date(card_ids: list[int], days: str = "0") -> None:
    """Anki "Set Due Date" syntax: "0" today, "1" tomorrow, "0-2" range, "!" suffix resets interval."""
    if card_ids:
        _invoke("setDueDate", cards=card_ids, days=days)


def forget_cards(card_ids: list[int]) -> None:
    if card_ids:
        _invoke("forgetCards", cards=card_ids)


def suspend_cards(card_ids: list[int]) -> None:
    if card_ids:
        _invoke("suspend", cards=card_ids)


def unsuspend_cards(card_ids: list[int]) -> None:
    if card_ids:
        _invoke("unsuspend", cards=card_ids)


def delete_notes(note_ids: list[int]) -> None:
    if note_ids:
        _invoke("deleteNotes", notes=note_ids)
