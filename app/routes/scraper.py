import os
import uuid
import re

from flask import Blueprint, request, jsonify
import requests
from bs4 import BeautifulSoup

from app import MEDIA_DIR

scraper_bp = Blueprint("scraper", __name__)


def _extract_og_tags(soup):
    """Extract OpenGraph meta tags from parsed HTML."""
    og = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        if prop.startswith("og:"):
            og[prop[3:]] = meta.get("content", "")
    return og


def _extract_twitter_tags(soup):
    """Extract Twitter Card meta tags from parsed HTML."""
    tw = {}
    for meta in soup.find_all("meta"):
        name = meta.get("name", "") or meta.get("property", "")
        if name.startswith("twitter:"):
            tw[name[8:]] = meta.get("content", "")
    return tw


def _detect_platform(url):
    url_lower = url.lower()
    if "linkedin.com" in url_lower:
        return "linkedin"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    elif "facebook.com" in url_lower:
        return "facebook"
    return "other"


def _clean_name(raw_name, platform):
    """Clean up extracted name, removing platform-specific suffixes."""
    if not raw_name:
        return ""
    name = raw_name.strip()
    name = re.sub(r"\s*[|\-–—].*$", "", name)
    name = re.sub(
        r"\s*on (LinkedIn|Twitter|Facebook|X).*$", "", name, flags=re.IGNORECASE
    )
    return name.strip()


def _download_image(image_url):
    """Download an image from a URL and save it to the media directory."""
    if not image_url:
        return None
    try:
        resp = requests.get(image_url, timeout=10, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "jpeg" in content_type or "jpg" in content_type:
            ext = "jpg"
        elif "png" in content_type:
            ext = "png"
        elif "webp" in content_type:
            ext = "webp"
        elif "gif" in content_type:
            ext = "gif"
        else:
            ext = "jpg"

        filename = f"{uuid.uuid4()}.{ext}"
        filepath = os.path.join(MEDIA_DIR, filename)
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return filename
    except Exception:
        return None


@scraper_bp.route("/url", methods=["POST"])
def scrape_url():
    """Scrape a profile URL and return extracted data for form pre-fill."""
    url = request.json.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    platform = _detect_platform(url)

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        return jsonify({"error": f"Failed to fetch URL: {str(e)}"}), 400

    soup = BeautifulSoup(resp.text, "html.parser")
    og = _extract_og_tags(soup)
    tw = _extract_twitter_tags(soup)

    raw_name = og.get("title", "") or tw.get("title", "")
    if not raw_name:
        title_tag = soup.find("title")
        raw_name = title_tag.get_text() if title_tag else ""

    name = _clean_name(raw_name, platform)

    description = og.get("description", "") or tw.get("description", "")
    image_url = og.get("image", "") or tw.get("image", "")

    face_filename = None
    if image_url:
        face_filename = _download_image(image_url)

    context1 = ""
    if description:
        context1 = description[:200].strip()

    return jsonify(
        {
            "name": name,
            "face_filename": face_filename,
            "context1": context1,
            "context2": "",
            "source": platform,
            "source_url": url,
        }
    )
