"""Minimal client for the AnkiConnect add-on (https://git.foosoft.net/alex/anki-connect).

Optional: if Anki desktop is running on this machine with AnkiConnect installed,
flagged cards can be rescheduled directly instead of via a manual search.
Set ANKICONNECT_URL to override the default endpoint.
"""

import os

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
    try:
        requests.get(URL, timeout=1).raise_for_status()
        return True
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
