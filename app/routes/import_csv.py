import csv
import io
import os

from flask import Blueprint, render_template, request, redirect, url_for, flash
import requests

from app import db
from app.models import Person

import_csv_bp = Blueprint("import_csv", __name__)


def _download_photo_from_url(photo_url):
    """Download a photo from a URL, optimize, and return the local filename."""
    if not photo_url or not photo_url.strip():
        return None
    try:
        import tempfile

        from app.services.images import save_and_optimize

        resp = requests.get(photo_url.strip(), timeout=10, stream=True)
        resp.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".img")
        for chunk in resp.iter_content(8192):
            tmp.write(chunk)
        tmp.close()
        try:
            return save_and_optimize(tmp.name)
        finally:
            if os.path.exists(tmp.name):
                os.remove(tmp.name)
    except Exception:
        return None


@import_csv_bp.route("/csv", methods=["GET", "POST"])
def import_csv_view():
    if request.method == "GET":
        return render_template("import_csv.html")

    file = request.files.get("csv_file")
    if not file or not file.filename:
        flash("Please select a CSV file.", "error")
        return render_template("import_csv.html")

    try:
        content = file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))

        required_fields = {"name"}
        if not required_fields.issubset(
            set(f.lower().strip() for f in (reader.fieldnames or []))
        ):
            flash("CSV must have at least a 'name' column.", "error")
            return render_template("import_csv.html")

        field_map = {f.lower().strip(): f for f in (reader.fieldnames or [])}

        def _get_field(row: dict, key: str) -> str:
            return row.get(field_map.get(key, ""), "").strip()

        rows = []
        for row in reader:
            name = _get_field(row, "name")
            if not name:
                continue
            rows.append(
                {
                    "name": name,
                    "photo_url": _get_field(row, "photo_url")
                    or _get_field(row, "photo"),
                    "context": _get_field(row, "context"),
                }
            )

        if not rows:
            flash("No valid rows found in CSV.", "error")
            return render_template("import_csv.html")

        return render_template("import_csv_preview.html", rows=rows)

    except Exception as e:
        flash(f"Error reading CSV: {str(e)}", "error")
        return render_template("import_csv.html")


@import_csv_bp.route("/csv/confirm", methods=["POST"])
def import_csv_confirm():
    names = request.form.getlist("name")
    photo_urls = request.form.getlist("photo_url")
    contexts = request.form.getlist("context")
    selected = request.form.getlist("selected")

    imported = 0
    for i in range(len(names)):
        if str(i) not in selected:
            continue
        name = names[i].strip()
        if not name:
            continue

        face_filename = _download_photo_from_url(
            photo_urls[i] if i < len(photo_urls) else ""
        )

        person = Person()
        person.name = name
        person.face_filename = face_filename
        person.context = contexts[i].strip() if i < len(contexts) else ""
        person.source = "csv"
        db.session.add(person)
        imported += 1

    db.session.commit()
    flash(f"Imported {imported} people from CSV.", "success")
    return redirect(url_for("people.index"))
