import html
import os

import genanki

from app import MEDIA_DIR

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "card_templates")

MODEL_ID = 1704067337
DECK_ID = 1704067338


def _load_template(name: str) -> str:
    with open(os.path.join(_TEMPLATE_DIR, name)) as f:
        return f.read()


def _build_model() -> genanki.Model:
    """Build a genanki Model with conditional card generation.

    Uses four toggle fields to control which card directions are generated
    per person. Anki skips a card when its front template evaluates to empty,
    so wrapping each template in a conditional on the toggle field gives us
    per-person control.
    """
    card_html = _load_template("card.html")
    card_css = _load_template("style.css")

    back_html = '<div class="back">{{FrontSide}}</div>'

    return genanki.Model(
        MODEL_ID,
        "Names and Faces",
        fields=[
            {"name": "Name"},
            {"name": "Face"},
            {"name": "Context"},
            {"name": "FaceToName"},
            {"name": "NameToFace"},
            {"name": "NameFaceToContext"},
            {"name": "ContextToPerson"},
        ],
        templates=[
            {
                "name": "Face to Name",
                "qfmt": "{{#FaceToName}}{{#Face}}"
                + card_html
                + "{{/Face}}{{/FaceToName}}",
                "afmt": back_html,
            },
            {
                "name": "Name to Face",
                "qfmt": "{{#NameToFace}}" + card_html + "{{/NameToFace}}",
                "afmt": back_html,
            },
            {
                "name": "Name and Face to Context",
                "qfmt": "{{#NameFaceToContext}}" + card_html + "{{/NameFaceToContext}}",
                "afmt": back_html,
            },
            {
                "name": "Context to Person",
                "qfmt": "{{#ContextToPerson}}" + card_html + "{{/ContextToPerson}}",
                "afmt": back_html,
            },
        ],
        css=card_css,
    )


class PersonNote(genanki.Note):
    """Note subclass with a stable GUID based on the person's database UUID.

    This ensures re-importing an updated deck matches existing notes and
    preserves all Anki scheduling data.
    """

    def __init__(self, person_id: str, **kwargs: object) -> None:
        self._person_id = person_id
        super().__init__(**kwargs)

    @property
    def guid(self) -> str:
        return genanki.guid_for(self._person_id)


def _make_face_html(face_filename: str | None) -> str:
    if not face_filename:
        return ""
    return f'<img src="{html.escape(face_filename)}">'


def generate_deck(people: list, output_path: str) -> None:
    model = _build_model()
    deck = genanki.Deck(DECK_ID, "Names and Faces")
    media_files: list[str] = []

    for person in people:
        face_html = _make_face_html(person.face_filename)
        name_val = html.escape(person.name) if person.name else ""
        ctx_val = html.escape(person.context) if person.context else ""

        has_face = bool(person.face_filename)
        has_context = person.has_context()

        toggle_face_to_name = "1" if (person.card_face_to_name and has_face) else ""
        toggle_name_to_face = "1" if person.card_name_to_face else ""
        toggle_nf_to_ctx = (
            "1"
            if (person.card_name_face_to_context and has_face and has_context)
            else ""
        )
        toggle_ctx_to_person = (
            "1" if (person.card_context_to_person and has_context) else ""
        )

        fields = [
            name_val,
            face_html,
            ctx_val,
            toggle_face_to_name,
            toggle_name_to_face,
            toggle_nf_to_ctx,
            toggle_ctx_to_person,
        ]

        note = PersonNote(person_id=person.id, model=model, fields=fields)
        deck.add_note(note)

        if person.face_filename:
            media_path = os.path.join(MEDIA_DIR, person.face_filename)
            if os.path.exists(media_path):
                media_files.append(media_path)

    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(output_path)
