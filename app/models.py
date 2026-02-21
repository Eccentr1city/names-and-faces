import uuid
from datetime import datetime, timezone

from app import db


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Person(db.Model):  # type: ignore[name-defined]
    __tablename__ = "people"

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    name = db.Column(db.Text, nullable=False)
    face_filename = db.Column(db.Text, nullable=True)
    context = db.Column(db.Text, nullable=True, default="")

    card_face_to_name = db.Column(db.Boolean, default=True, nullable=False)
    card_name_to_face = db.Column(db.Boolean, default=True, nullable=False)
    card_name_face_to_context = db.Column(db.Boolean, default=True, nullable=False)
    card_context_to_person = db.Column(db.Boolean, default=False, nullable=False)

    source = db.Column(db.Text, default="manual")
    source_url = db.Column(db.Text, nullable=True, default="")

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def has_context(self) -> bool:
        return bool(self.context and self.context.strip())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "face_filename": self.face_filename,
            "context": self.context or "",
            "card_face_to_name": self.card_face_to_name,
            "card_name_to_face": self.card_name_to_face,
            "card_name_face_to_context": self.card_name_face_to_context,
            "card_context_to_person": self.card_context_to_person,
            "source": self.source,
            "source_url": self.source_url or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
