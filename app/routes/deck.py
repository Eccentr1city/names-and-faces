import os
import tempfile

from flask import Blueprint, flash, jsonify, redirect, request, send_file, url_for

from app import db
from app.models import Person
from app.services import anki_sync, ankiconnect
from app.services.deck_generator import generate_deck

deck_bp = Blueprint("deck", __name__)


@deck_bp.route("/export", methods=["POST"])
def export_deck():
    person_ids = request.form.getlist("person_ids")

    if person_ids:
        people = Person.active().filter(Person.id.in_(person_ids)).all()
    else:
        people = Person.active().all()

    if not people:
        flash("No people to export.", "error")
        return redirect(url_for("people.index"))

    output_dir = tempfile.mkdtemp()
    output_path = os.path.join(output_dir, "names_and_faces.apkg")

    generate_deck(people, output_path)

    return send_file(
        output_path,
        as_attachment=True,
        download_name="names_and_faces.apkg",
        mimetype="application/octet-stream",
    )


def _clear_review_soon_flags() -> int:
    count = (
        Person.active()
        .filter(Person.review_soon_cards.isnot(None))
        .filter(Person.review_soon_cards != "")
        .update({"review_soon_cards": ""})
    )
    db.session.commit()
    return count


@deck_bp.route("/review-soon/clear", methods=["POST"])
def clear_review_soon():
    count = _clear_review_soon_flags()
    flash(
        f"Cleared early-review flags for {count} {'person' if count == 1 else 'people'}.",
        "success",
    )
    return redirect(url_for("people.index"))


@deck_bp.route("/review-soon/reschedule", methods=["POST"])
def reschedule_review_soon():
    """Bring flagged cards forward via AnkiConnect (deck already imported by hand)."""
    days = request.form.get("days", "0").strip() or "0"
    try:
        cards, people = anki_sync.reschedule_flagged(days)
    except (ankiconnect.AnkiConnectError, anki_sync.AnkiSyncError) as e:
        flash(f"AnkiConnect error: {e}", "error")
        return redirect(url_for("people.index"))
    if cards == 0:
        flash(
            "No matching cards found in Anki for the flagged people. Import the latest "
            "export first (or use Push to Anki, which does both).",
            "error",
        )
        return redirect(url_for("people.index"))
    what = "reset to new" if days == "forget" else f"due in {days} day(s)"
    flash(
        f"Rescheduled {cards} card{'s' if cards != 1 else ''} for {people} {'person' if people == 1 else 'people'} ({what}).",
        "success",
    )
    return redirect(url_for("people.index"))


def _explain_sync_error(err: str) -> str:
    """Turn AnkiConnect's raw sync failure into an instruction."""
    if "auth not configured" in err:
        return "Anki desktop is not logged in to AnkiWeb. Log in via Sync in Anki, then sync by hand this time."
    if "Sync status" in err:
        return (
            "Anki needs a one-time full sync. Click Sync in Anki desktop and choose "
            "Upload to AnkiWeb (the desktop collection is the one this app writes to). "
            "Later pushes sync normally."
        )
    return f"{err}. Sync by hand in Anki."


def _anki_error(e: Exception):
    return jsonify({"error": str(e)}), 502


@deck_bp.route("/anki/status", methods=["GET"])
def anki_status():
    """Everything the Anki panel shows: stale notes, people to trash, edits made
    in Anki, and per-person review stats."""
    try:
        return jsonify(anki_sync.status())
    except (ankiconnect.AnkiConnectError, anki_sync.AnkiSyncError) as e:
        return _anki_error(e)


@deck_bp.route("/anki/push", methods=["POST"])
def anki_push():
    """Export, import into Anki, reschedule flagged cards, suspend trashed people's notes, sync."""
    days = request.form.get("days", "0").strip() or "0"
    try:
        r = anki_sync.push(days)
    except (ankiconnect.AnkiConnectError, anki_sync.AnkiSyncError) as e:
        flash(f"Push to Anki failed: {e}", "error")
        return redirect(url_for("people.index"))

    parts = [f"Pushed {r['people']} people to Anki"]
    if r["new"]:
        parts.append(f"{r['new']} new")
    if r["rescheduled_cards"]:
        what = "reset to new" if r["days"] == "forget" else f"due in {r['days']} day(s)"
        parts.append(
            f"{r['rescheduled_cards']} card{'s' if r['rescheduled_cards'] != 1 else ''} "
            f"for {r['rescheduled_people']} flagged {'person' if r['rescheduled_people'] == 1 else 'people'} {what}"
        )
    if r["suspended_cards"]:
        parts.append(
            f"suspended {r['suspended_cards']} card{'s' if r['suspended_cards'] != 1 else ''} "
            f"of {r['suspended_people']} trashed {'person' if r['suspended_people'] == 1 else 'people'}"
        )
    flash("; ".join(parts) + ".", "success")
    if r["sync_error"]:
        flash(
            f"Imported and rescheduled, but AnkiWeb sync did not run: {_explain_sync_error(r['sync_error'])}",
            "error",
        )
    else:
        flash("Synced with AnkiWeb. Sync on your phone to pick up the changes.", "info")
    return redirect(url_for("people.index"))


@deck_bp.route("/anki/pull", methods=["POST"])
def anki_pull():
    """Apply field values edited in Anki to the app."""
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({"done": anki_sync.apply_edits(data.get("edits", []))})
    except (ankiconnect.AnkiConnectError, anki_sync.AnkiSyncError) as e:
        return _anki_error(e)


@deck_bp.route("/anki/trash", methods=["POST"])
def anki_trash():
    """Trash people whose notes are suspended or gone in Anki."""
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            {
                "done": anki_sync.trash_people(
                    [str(i) for i in data.get("person_ids", [])]
                )
            }
        )
    except (ankiconnect.AnkiConnectError, anki_sync.AnkiSyncError) as e:
        return _anki_error(e)


@deck_bp.route("/anki/stale/<action>", methods=["POST"])
def anki_stale_act(action: str):
    """Suspend (default) or delete stale notes in Anki. Only ids currently stale are touched."""
    if action not in ("suspend", "delete"):
        return jsonify({"error": "unknown action"}), 404
    data = request.get_json(silent=True) or {}
    try:
        note_ids = [int(i) for i in data.get("note_ids", [])]
    except (TypeError, ValueError):
        return jsonify({"error": "note_ids must be integers"}), 400
    try:
        return jsonify({"done": anki_sync.act_on_stale(action, note_ids)})
    except (ankiconnect.AnkiConnectError, anki_sync.AnkiSyncError) as e:
        return _anki_error(e)
