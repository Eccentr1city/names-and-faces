import os

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

from app import MEDIA_DIR, db
from app.models import Person

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
            Person.query.filter(Person.name.ilike(f"%{search}%"))
            .order_by(Person.created_at.desc())
            .all()
        )
    else:
        people = Person.query.order_by(Person.created_at.desc()).all()
    return render_template("index.html", people=people, search=search)


@people_bp.route("/check-duplicate", methods=["POST"])
def check_duplicate():
    """Check if a person with this name already exists."""
    from flask import jsonify

    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    exclude_id = data.get("exclude_id", "")
    if not name:
        return jsonify({"duplicate": False})

    query = Person.query.filter(db.func.lower(Person.name) == name.lower())
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

        db.session.commit()
        flash(f"Updated {person.name}.", "success")
        return redirect(url_for("people.index"))

    return render_template("person_form.html", person=person, mode="edit")


@people_bp.route("/delete/<person_id>", methods=["POST"])
def delete_person(person_id: str):
    person = Person.query.get_or_404(person_id)
    if person.face_filename:
        photo_path = os.path.join(MEDIA_DIR, person.face_filename)
        if os.path.exists(photo_path):
            os.remove(photo_path)
    name = person.name
    db.session.delete(person)
    db.session.commit()
    flash(f"Deleted {name}.", "success")
    return redirect(url_for("people.index"))


@people_bp.route("/media/<filename>")
def serve_media(filename: str):
    return send_from_directory(MEDIA_DIR, secure_filename(filename))
