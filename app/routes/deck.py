import os
import tempfile

from flask import Blueprint, flash, jsonify, redirect, request, send_file, url_for

from app import db
from app.models import Person
from app.services import ankiconnect
from app.services.deck_generator import generate_deck
from app.services.review_soon import anki_search

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
    """Bring flagged cards forward via AnkiConnect, then clear the flags."""
    days = request.form.get("days", "0").strip() or "0"
    try:
        count = ankiconnect.reschedule(anki_search(), days)
    except ankiconnect.AnkiConnectError as e:
        flash(f"AnkiConnect error: {e}", "error")
        return redirect(url_for("people.index"))

    if count == 0:
        flash(
            "AnkiConnect found no flagged cards. Export the deck and import it into "
            "Anki first so the tags are present, then try again.",
            "error",
        )
        return redirect(url_for("people.index"))

    _clear_review_soon_flags()
    what = "reset to new" if days == "forget" else f"due in {days} day(s)"
    flash(
        f"Rescheduled {count} card{'s' if count != 1 else ''} in Anki ({what}).",
        "success",
    )
    return redirect(url_for("people.index"))


def _stale_notes():
    return ankiconnect.stale_notes(Person.active().all())


@deck_bp.route("/anki/stale", methods=["GET"])
def anki_stale():
    """Notes in Anki's deck that no longer correspond to a person in the app."""
    try:
        return jsonify({"stale": _stale_notes()})
    except ankiconnect.AnkiConnectError as e:
        return jsonify({"error": str(e)}), 502


@deck_bp.route("/anki/stale/<action>", methods=["POST"])
def anki_stale_act(action: str):
    """Suspend or delete stale notes in Anki. Only ids currently stale are touched."""
    if action not in ("suspend", "delete"):
        return jsonify({"error": "unknown action"}), 404
    data = request.get_json(silent=True) or {}
    try:
        requested = {int(i) for i in data.get("note_ids", [])}
    except (TypeError, ValueError):
        return jsonify({"error": "note_ids must be integers"}), 400
    try:
        allowed = {n["note_id"] for n in _stale_notes()}
        ids = sorted(requested & allowed)
        if not ids:
            return jsonify({"done": 0, "stale": sorted(allowed)})
        if action == "delete":
            ankiconnect.delete_notes(ids)
        else:
            ankiconnect.suspend_notes(ids)
        return jsonify({"done": len(ids)})
    except ankiconnect.AnkiConnectError as e:
        return jsonify({"error": str(e)}), 502
