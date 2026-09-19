import os
from datetime import datetime, timezone

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from markupsafe import Markup, escape
from werkzeug.utils import secure_filename

from app import MEDIA_DIR, db
from app.models import Person
from app.services import ankiconnect
from app.services.review_soon import CARD_LABELS, anki_search, cards_for_changes

people_bp = Blueprint("people", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_photo(file) -> str:  # type: ignore[type-arg]
    from app.services.images import save_and_optimize

    return save_and_optimize(file)


def _read_card_toggles() -> dict:
    return {
        "card_face_to_name": "card_face_to_name" in request.form,
        "card_name_to_face": "card_name_to_face" in request.form,
        "card_name_face_to_context": "card_name_face_to_context" in request.form,
        "card_context_to_person": "card_context_to_person" in request.form,
    }


@people_bp.route("/")
def index():
    search = request.args.get("q", "").strip()
    if search:
        people = (
            Person.active()
            .filter(Person.name.ilike(f"%{search}%"))
            .order_by(Person.created_at.desc())
            .all()
        )
    else:
        people = Person.active().order_by(Person.created_at.desc()).all()

    pending = (
        Person.active()
        .filter(Person.review_soon_cards.isnot(None))
        .filter(Person.review_soon_cards != "")
        .order_by(Person.name)
        .all()
    )
    return render_template(
        "index.html",
        people=people,
        search=search,
        pending=pending,
        trash_count=Person.trashed().count(),
        anki_search=anki_search() if pending else "",
        anki_available=ankiconnect.is_available(),
    )


@people_bp.route("/check-duplicate", methods=["POST"])
def check_duplicate():
    """Check if a person with this name already exists."""
    from flask import jsonify

    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    exclude_id = data.get("exclude_id", "")
    if not name:
        return jsonify({"duplicate": False})

    query = Person.active().filter(db.func.lower(Person.name) == name.lower())
    if exclude_id:
        query = query.filter(Person.id != exclude_id)
    existing = query.first()

    if existing:
        return jsonify(
            {
                "duplicate": True,
                "existing_id": existing.id,
                "existing_name": existing.name,
                "existing_context": existing.context or "",
                "existing_face": existing.face_filename or "",
            }
        )
    return jsonify({"duplicate": False})


@people_bp.route("/add", methods=["GET", "POST"])
def add_person():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "error")
            return render_template("person_form.html", person=None, mode="add")

        person = Person()
        person.name = name
        person.context = request.form.get("context", "").strip()
        person.source = request.form.get("source", "manual")
        person.source_url = request.form.get("source_url", "").strip()
        for key, val in _read_card_toggles().items():
            setattr(person, key, val)

        photo = request.files.get("photo")
        if photo and photo.filename and _allowed_file(photo.filename):
            person.face_filename = _save_photo(photo)
        elif request.form.get("scraped_face_filename"):
            person.face_filename = request.form["scraped_face_filename"]

        db.session.add(person)
        db.session.commit()
        flash(f"Added {person.name}.", "success")
        return redirect(url_for("people.index"))

    return render_template("person_form.html", person=None, mode="add")


@people_bp.route("/edit/<person_id>", methods=["GET", "POST"])
def edit_person(person_id: str):
    person = Person.query.get_or_404(person_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "error")
            return render_template("person_form.html", person=person, mode="edit")

        before = {
            "name": person.name,
            "context": (person.context or "").strip(),
            "face": person.face_filename,
        }

        person.name = name
        person.context = request.form.get("context", "").strip()
        person.source_url = request.form.get("source_url", "").strip()

        for key, val in _read_card_toggles().items():
            setattr(person, key, val)

        photo = request.files.get("photo")
        if photo and photo.filename and _allowed_file(photo.filename):
            if person.face_filename:
                old_path = os.path.join(MEDIA_DIR, person.face_filename)
                if os.path.exists(old_path):
                    os.remove(old_path)
            person.face_filename = _save_photo(photo)
        elif request.form.get("scraped_face_filename") and not person.face_filename:
            person.face_filename = request.form["scraped_face_filename"]

        person.touch()

        if "review_soon" in request.form:
            after = {
                "name": person.name,
                "context": (person.context or "").strip(),
                "face": person.face_filename,
            }
            changed = [f for f in before if before[f] != after[f]]
            flagged = cards_for_changes(changed)
            if flagged:
                person.flag_review_soon(flagged)
                labels = ", ".join(CARD_LABELS[k] for k in flagged)
                flash(f"Flagged for early review: {labels}.", "info")
            else:
                flash(
                    "Name, photo, and context are unchanged, so no cards were flagged.",
                    "info",
                )

        db.session.commit()
        flash(f"Updated {person.name}.", "success")
        return redirect(url_for("people.index"))

    return render_template("person_form.html", person=person, mode="edit")


@people_bp.route("/delete/<person_id>", methods=["POST"])
def delete_person(person_id: str):
    """Move a person to the trash. The photo stays until permanent deletion."""
    person = Person.query.get_or_404(person_id)
    person.deleted_at = datetime.now(timezone.utc)
    person.review_soon_cards = ""
    db.session.commit()
    undo = url_for("people.restore_person", person_id=person.id)
    flash(
        Markup(
            f"Moved {escape(person.name)} to the trash. "
            f'<form method="POST" action="{undo}" class="inline">'
            f'<button type="submit" class="underline font-semibold">Undo</button></form>'
        ),
        "success",
    )
    return redirect(url_for("people.index"))


@people_bp.route("/trash")
def trash():
    return render_template("trash.html", people=Person.trashed().all())


@people_bp.route("/trash/restore/<person_id>", methods=["POST"])
def restore_person(person_id: str):
    person = Person.query.get_or_404(person_id)
    person.deleted_at = None
    db.session.commit()
    flash(f"Restored {person.name}.", "success")
    return redirect(request.referrer or url_for("people.index"))


def _purge(person: Person) -> None:
    if person.face_filename:
        photo_path = os.path.join(MEDIA_DIR, person.face_filename)
        if os.path.exists(photo_path):
            os.remove(photo_path)
    db.session.delete(person)


@people_bp.route("/trash/purge/<person_id>", methods=["POST"])
def purge_person(person_id: str):
    """Permanently delete one trashed person and their photo."""
    person = Person.trashed().filter(Person.id == person_id).first_or_404()
    name = person.name
    _purge(person)
    db.session.commit()
    flash(f"Permanently deleted {name}.", "success")
    return redirect(url_for("people.trash"))


@people_bp.route("/trash/empty", methods=["POST"])
def empty_trash():
    people = Person.trashed().all()
    for person in people:
        _purge(person)
    db.session.commit()
    flash(
        f"Permanently deleted {len(people)} {'person' if len(people) == 1 else 'people'}.",
        "success",
    )
    return redirect(url_for("people.index"))


@people_bp.route("/media/<filename>")
def serve_media(filename: str):
    return send_from_directory(MEDIA_DIR, secure_filename(filename))
