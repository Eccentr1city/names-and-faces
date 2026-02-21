"""Image processing utilities. Resizes and compresses profile photos."""

import os
import uuid
from typing import IO

from PIL import Image
from PIL.Image import Resampling

from app import MEDIA_DIR

MAX_DIMENSION = 400
JPEG_QUALITY = 85


def save_and_optimize(input_path_or_fileobj: str | IO[bytes]) -> str:
    """Resize an image to MAX_DIMENSION and save as JPEG.

    Accepts either a file path (str) or a file-like object.
    Returns the filename of the saved image in MEDIA_DIR.
    """
    img = Image.open(input_path_or_fileobj)

    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if img.width > MAX_DIMENSION or img.height > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Resampling.LANCZOS)

    filename = f"{uuid.uuid4()}.jpg"
    filepath = os.path.join(MEDIA_DIR, filename)
    img.save(filepath, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return filename


def optimize_existing(filepath: str) -> str | None:
    """Optimize an existing image file in-place. Returns new filename or None on error."""
    try:
        new_filename = save_and_optimize(filepath)
        if os.path.abspath(filepath) != os.path.abspath(
            os.path.join(MEDIA_DIR, new_filename)
        ):
            os.remove(filepath)
        return new_filename
    except Exception:
        return None
