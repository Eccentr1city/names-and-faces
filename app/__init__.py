import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

_DEFAULT_DATA_DIR = os.path.expanduser("~/.names-and-faces")

DATA_DIR = os.environ.get("NAMES_AND_FACES_DATA_DIR", _DEFAULT_DATA_DIR)
MEDIA_DIR = os.path.join(DATA_DIR, "media")


def create_app() -> Flask:
    app = Flask(__name__)

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(MEDIA_DIR, exist_ok=True)

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"sqlite:///{os.path.join(DATA_DIR, 'names_and_faces.db')}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    app.config["SECRET_KEY"] = "dev-secret-key-change-in-production"

    db.init_app(app)

    from app.routes.deck import deck_bp
    from app.routes.import_csv import import_csv_bp
    from app.routes.people import people_bp
    from app.routes.scraper import scraper_bp

    app.register_blueprint(people_bp)
    app.register_blueprint(deck_bp, url_prefix="/deck")
    app.register_blueprint(scraper_bp, url_prefix="/scrape")
    app.register_blueprint(import_csv_bp, url_prefix="/import")

    with app.app_context():
        from app import models  # noqa: F401

        db.create_all()

    return app
