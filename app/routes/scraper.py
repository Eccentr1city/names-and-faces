import os
import re
import uuid

import requests
from bs4 import BeautifulSoup
from flask import Blueprint, jsonify, request

from app import MEDIA_DIR
from app.services.llm import summarize_context

scraper_bp = Blueprint("scraper", __name__)

_LINKEDIN_COOKIE = os.environ.get("LINKEDIN_LI_AT", "")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _extract_og_tags(soup: BeautifulSoup) -> dict[str, str]:
    og: dict[str, str] = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        if prop.startswith("og:"):
            og[prop[3:]] = meta.get("content", "")
    return og


def _extract_twitter_tags(soup: BeautifulSoup) -> dict[str, str]:
    tw: dict[str, str] = {}
    for meta in soup.find_all("meta"):
        name = meta.get("name", "") or meta.get("property", "")
        if name.startswith("twitter:"):
            tw[name[8:]] = meta.get("content", "")
    return tw


def _detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "linkedin.com" in url_lower:
        return "linkedin"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    elif "facebook.com" in url_lower:
        return "facebook"
    return "other"


def _clean_name(raw_name: str, platform: str) -> str:
    if not raw_name:
        return ""
    name = raw_name.strip()
    name = re.sub(r"\s*[|\-–—].*$", "", name)
    name = re.sub(
        r"\s*on (LinkedIn|Twitter|Facebook|X).*$", "", name, flags=re.IGNORECASE
    )
    # LinkedIn sometimes includes credentials after the name
    name = re.sub(r",\s*(PhD|MD|MBA|CPA|PE|PMP|CFA|JD|Esq)\.?.*$", "", name)
    name = name.strip()

    # Title-case if the name is all lowercase or all uppercase
    if name == name.lower() or name == name.upper():
        name = name.title()

    return name


def _clean_linkedin_description(desc: str) -> str:
    """Extract meaningful content from LinkedIn's OG description format.

    LinkedIn descriptions typically look like:
    'Experience: Company · Education: School · Location: City · 500+ connections'
    or just a headline like 'Software Engineer at Google'
    """
    if not desc:
        return ""

    # Remove common LinkedIn boilerplate
    desc = re.sub(r"\s*·\s*\d+\+?\s*connections?\s*", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s*·\s*Connect\s*$", "", desc, flags=re.IGNORECASE)

    # If it's the structured "Experience: X · Education: Y" format, extract parts
    parts = [p.strip() for p in desc.split("·") if p.strip()]
    cleaned_parts = []
    for part in parts:
        # Skip location-only entries
        if re.match(r"^(Location|Connections):", part, re.IGNORECASE):
            continue
        # Remove field labels
        part = re.sub(r"^(Experience|Education|Location):\s*", "", part)
        if part:
            cleaned_parts.append(part)

    return " · ".join(cleaned_parts) if cleaned_parts else desc.strip()


def _is_valid_profile_image(url: str) -> bool:
    """Check if an image URL is likely a real profile photo, not a placeholder."""
    if not url:
        return False
    lower = url.lower()
    # LinkedIn default/ghost profile SVGs (the aero-v1/sc/h/ path is their sprite CDN)
    if "/aero-v1/sc/h/" in lower:
        return False
    if "ghost" in lower or "default" in lower:
        return False
    # Generic placeholder patterns
    if "placeholder" in lower or "no-photo" in lower or "no_photo" in lower:
        return False
    return True


def _download_image(
    image_url: str, cookies: dict[str, str] | None = None
) -> tuple[str | None, str | None]:
    """Download an image and return (filename, error_message)."""
    if not image_url:
        return None, "No image URL found"

    if not _is_valid_profile_image(image_url):
        return None, "Image appears to be a placeholder, not a real profile photo"

    try:
        resp = requests.get(
            image_url,
            headers=_HEADERS,
            cookies=cookies,
            timeout=15,
            stream=True,
            allow_redirects=True,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return None, f"URL returned {content_type}, not an image"

        if "svg" in content_type:
            return None, "Image is an SVG (LinkedIn default avatar), not a real photo"

        content_length = resp.headers.get("content-length")
        if content_length and int(content_length) < 1000:
            return None, "Image is too small (likely a placeholder)"

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
        total_bytes = 0
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
                total_bytes += len(chunk)

        if total_bytes < 1000:
            os.remove(filepath)
            return None, "Downloaded image is too small (likely a placeholder)"

        return filename, None
    except requests.RequestException as e:
        return None, f"Failed to download image: {e}"


def _extract_linkedin_profile_text(soup: BeautifulSoup, name: str) -> dict[str, str]:
    """Extract profile data from authenticated LinkedIn HTML.

    Authenticated pages render profile data as individual <p> tags inside
    the profile card container (identified by "Contact info" text nearby).
    Images are loaded via JS and can't be downloaded server-side.
    """
    result: dict[str, str] = {"headline": "", "company": "", "location": ""}

    # Find "Contact info" text and walk up to the profile card container
    contact_el = soup.find(string=re.compile("Contact info"))
    if not contact_el:
        return result

    container = contact_el.parent
    for _ in range(5):
        if container and container.parent:
            container = container.parent

    if not container:
        return result

    _SKIP = {
        "contact info",
        "he/him",
        "she/her",
        "they/them",
        "message",
        "more",
        "connect",
        "follow",
        "pending",
    }

    name_lower = name.lower() if name else ""
    fields: list[str] = []

    for p_tag in container.find_all("p", recursive=True):
        text = p_tag.get_text(strip=True)
        if not text or len(text) < 3 or len(text) > 200:
            continue
        text_lower = text.lower()
        # Skip the name itself, pronouns, connection degrees, boilerplate
        if text_lower in _SKIP:
            continue
        if name_lower and text_lower == name_lower:
            continue
        if re.match(r"^[\s·\u00b7\u00c2]*(1st|2nd|3rd|\d+th)", text):
            continue
        if re.match(r"^[\s·\u00b7\u00c2]+", text) and len(text) < 15:
            continue
        fields.append(text)

    if len(fields) >= 1:
        result["headline"] = fields[0]
    if len(fields) >= 2:
        result["company"] = fields[1]
    if len(fields) >= 3:
        result["location"] = fields[2]

    return result


def _extract_linkedin_photo_url(html_text: str) -> str:
    """Extract the best profile photo URL from authenticated LinkedIn HTML.

    Authenticated pages embed photo URLs as rootUrl + suffixUrl fragments
    in their RSC/JSON data. We reconstruct a full URL from these pieces.
    """
    # Find root URLs for profile display photos
    roots = re.findall(
        r"(https://media\.licdn\.com/dms/image/v2/[A-Za-z0-9_-]+/profile-displayphoto-)",
        html_text,
    )
    if not roots:
        return ""

    # Find the largest suffix with auth token (prefer 400x400)
    for size in ("400_400", "800_800", "200_200", "100_100"):
        pattern = rf"shrink_{size}(/[^\"\\<>\s]+(?:\\u0026[^\"\\<>\s]+)*)"
        suffixes = re.findall(pattern, html_text)
        if suffixes:
            suffix = f"shrink_{size}{suffixes[0]}"
            full_url = roots[0] + suffix
            full_url = full_url.encode("utf-8").decode("unicode_escape")
            return full_url

    return ""


def _scrape_linkedin(url: str, soup: BeautifulSoup) -> dict:
    """LinkedIn-specific scraping with fallbacks.

    Public pages have OG tags. Authenticated pages have richer HTML text
    content but images can't be downloaded server-side.
    """
    og = _extract_og_tags(soup)
    tw = _extract_twitter_tags(soup)

    # Name: try OG tags first, then page title
    raw_name = og.get("title", "") or tw.get("title", "")
    if not raw_name:
        title_tag = soup.find("title")
        raw_name = title_tag.get_text() if title_tag else ""
    name = _clean_name(raw_name, "linkedin")

    # Description: try OG tags first
    raw_desc = og.get("description", "") or tw.get("description", "")
    description = _clean_linkedin_description(raw_desc)

    # If OG tags are missing (authenticated page), extract from HTML text
    is_authenticated_page = not og.get("description")
    if is_authenticated_page:
        profile_text = _extract_linkedin_profile_text(soup, name)
        if profile_text["headline"] and not description:
            parts = [profile_text["headline"]]
            if profile_text["company"]:
                parts.append(profile_text["company"])
            description = " · ".join(parts)
            raw_desc = description

    # Image: try OG tag first, then extract from authenticated HTML
    image_url = og.get("image", "") or tw.get("image", "")
    if not _is_valid_profile_image(image_url):
        image_url = ""

    if not image_url and is_authenticated_page:
        image_url = _extract_linkedin_photo_url(str(soup))

    return {
        "name": name,
        "raw_description": raw_desc,
        "description": description,
        "image_url": image_url,
        "_is_authenticated": is_authenticated_page,
    }


def _scrape_twitter(url: str, soup: BeautifulSoup) -> dict:
    """Twitter/X scraping using OG tags (served to bot UAs)."""
    og = _extract_og_tags(soup)
    tw = _extract_twitter_tags(soup)

    raw_name = og.get("title", "") or tw.get("title", "")
    # OG title format: "Kayo Yin (@kayo_yin) on X"
    name_match = re.match(r"^(.+?)\s*\(@\w+\)", raw_name)
    name = (
        name_match.group(1).strip() if name_match else _clean_name(raw_name, "twitter")
    )

    description = og.get("description", "") or tw.get("description", "")
    image_url = og.get("image", "") or tw.get("image:src", "") or tw.get("image", "")

    # Twitter image URLs often have _200x200; request the larger _400x400
    if image_url and "_200x200" in image_url:
        image_url = image_url.replace("_200x200", "_400x400")

    return {
        "name": name,
        "raw_description": description,
        "description": description,
        "image_url": image_url,
    }


def _scrape_generic(url: str, soup: BeautifulSoup) -> dict:
    """Generic scraping for any URL using OG/Twitter tags."""
    og = _extract_og_tags(soup)
    tw = _extract_twitter_tags(soup)

    raw_name = og.get("title", "") or tw.get("title", "")
    if not raw_name:
        title_tag = soup.find("title")
        raw_name = title_tag.get_text() if title_tag else ""
    name = _clean_name(raw_name, "other")

    description = og.get("description", "") or tw.get("description", "")
    image_url = og.get("image", "") or tw.get("image", "")

    return {
        "name": name,
        "raw_description": description,
        "description": description,
        "image_url": image_url,
    }


@scraper_bp.route("/url", methods=["POST"])
def scrape_url():
    """Scrape a profile URL and return extracted data for form pre-fill."""
    url = request.json.get("url", "").strip()  # type: ignore[union-attr]
    if not url:
        return jsonify({"error": "URL is required"}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    platform = _detect_platform(url)

    # Normalize Twitter URLs to the canonical profile path
    if platform == "twitter":
        match = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)", url)
        if match:
            url = f"https://x.com/{match.group(1)}"
    warnings: list[str] = []

    # Twitter/X serves OG tags to bot UAs but not browser UAs
    req_headers = (
        {**_HEADERS, "User-Agent": "Twitterbot/1.0"}
        if platform == "twitter"
        else _HEADERS
    )
    cookies: dict[str, str] = {}
    if platform == "linkedin" and _LINKEDIN_COOKIE:
        cookies["li_at"] = _LINKEDIN_COOKIE

    try:
        resp = requests.get(
            url, headers=req_headers, cookies=cookies, timeout=15, allow_redirects=True
        )
    except requests.RequestException as e:
        return jsonify({"error": f"Failed to fetch URL: {e}"}), 400

    # LinkedIn returns 999 when it blocks the request (auth wall)
    if resp.status_code == 999 or (
        platform == "linkedin" and "authwall" in resp.text.lower()
    ):
        hint = (
            "Set LINKEDIN_LI_AT in your environment to enable authenticated scraping. "
            "Get this cookie from your browser dev tools (Application > Cookies > li_at)."
            if not _LINKEDIN_COOKIE
            else "Your LinkedIn session cookie may have expired. Refresh it from your browser."
        )
        return (
            jsonify(
                {
                    "error": f"LinkedIn blocked this request (auth wall). {hint}",
                }
            ),
            400,
        )

    if resp.status_code >= 400:
        return (
            jsonify({"error": f"Page returned HTTP {resp.status_code}"}),
            400,
        )

    soup = BeautifulSoup(resp.text, "html.parser")

    if platform == "linkedin":
        data = _scrape_linkedin(url, soup)
    elif platform == "twitter":
        data = _scrape_twitter(url, soup)
    else:
        data = _scrape_generic(url, soup)

    if not data["name"]:
        warnings.append("Could not extract name from this page")

    if not data["description"]:
        warnings.append("No description/bio found on this page")

    # Download profile image
    face_filename = None
    if data["image_url"]:
        face_filename, img_error = _download_image(data["image_url"], cookies=cookies)
        if img_error:
            if platform == "linkedin" and "403" in str(img_error):
                warnings.append(
                    "Found the profile photo but LinkedIn blocked the download. "
                    "Copy the image from your browser (right-click > Copy Image) "
                    "and paste it here with Cmd+V."
                )
            else:
                warnings.append(img_error)
    else:
        warnings.append(
            "No profile image found. "
            "You can copy the photo from your browser and paste here with Cmd+V."
        )

    raw_context = data["description"][:300] if data["description"] else ""

    return jsonify(
        {
            "name": data["name"],
            "face_filename": face_filename,
            "context1": raw_context,
            "raw_description": data.get("raw_description", raw_context),
            "source": platform,
            "source_url": url,
            "warnings": warnings,
        }
    )


@scraper_bp.route("/summarize", methods=["POST"])
def summarize():
    """Summarize a description using LLM. Called async after scrape returns."""
    description = request.json.get("description", "").strip()  # type: ignore[union-attr]
    name = request.json.get("name", "").strip()  # type: ignore[union-attr]

    if not description:
        return jsonify({"summary": ""}), 200

    result = summarize_context(description, name)
    if result:
        return jsonify({"summary": result})
    return jsonify({"summary": ""}), 200
