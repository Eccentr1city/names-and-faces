import os
import tempfile

from flask import Blueprint, request, send_file, redirect, url_for, flash

from app.models import Person
from app.services.deck_generator import generate_deck

deck_bp = Blueprint("deck", __name__)


@deck_bp.route("/export", methods=["POST"])
def export_deck():
    person_ids = request.form.getlist("person_ids")

    if person_ids:
        people = Person.query.filter(Person.id.in_(person_ids)).all()
    else:
        people = Person.query.all()

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
