"""One-time script to optimize all existing images in the media directory.

Resizes to 400x400 max and converts to JPEG. Updates database references.

Usage: uv run python scripts/optimize-images.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app import MEDIA_DIR, create_app, db  # noqa: E402
from app.models import Person  # noqa: E402
from app.services.images import save_and_optimize  # noqa: E402

app = create_app()

with app.app_context():
    people = Person.query.all()
    optimized = 0
    saved_bytes = 0

    for person in people:
        if not person.face_filename:
            continue

        old_path = os.path.join(MEDIA_DIR, person.face_filename)
        if not os.path.exists(old_path):
            print(f"  SKIP {person.name}: file missing ({person.face_filename})")
            continue

        old_size = os.path.getsize(old_path)

        try:
            new_filename = save_and_optimize(old_path)
        except Exception as e:
            print(f"  FAIL {person.name}: {e}")
            continue

        new_path = os.path.join(MEDIA_DIR, new_filename)
        new_size = os.path.getsize(new_path)

        # Remove old file if different
        if person.face_filename != new_filename and os.path.exists(old_path):
            os.remove(old_path)

        person.face_filename = new_filename
        saved_bytes += old_size - new_size
        optimized += 1
        print(f"  OK {person.name}: {old_size // 1024}KB -> {new_size // 1024}KB")

    db.session.commit()
    print(f"\nOptimized {optimized} images, saved {saved_bytes // 1024}KB")
