import os
import re
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag
from flask import Blueprint, jsonify, request

from app.services.llm import extract_profile_from_html, summarize_context

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


def _meta_attr(tag: Tag, attr: str) -> str:
    """Safely get a string attribute from a BeautifulSoup tag."""
    val: Any = tag.get(attr, "")
    if isinstance(val, list):
        return val[0] if val else ""
    return str(val) if val else ""


def _extract_og_tags(soup: BeautifulSoup) -> dict[str, str]:
    og: dict[str, str] = {}
    for meta in soup.find_all("meta"):
        prop = _meta_attr(meta, "property") or _meta_attr(meta, "name")
        if prop.startswith("og:"):
            og[prop[3:]] = _meta_attr(meta, "content")
    return og


def _extract_twitter_tags(soup: BeautifulSoup) -> dict[str, str]:
    tw: dict[str, str] = {}
    for meta in soup.find_all("meta"):
        name = _meta_attr(meta, "name") or _meta_attr(meta, "property")
        if name.startswith("twitter:"):
            tw[name[8:]] = _meta_attr(meta, "content")
    return tw


def _detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "linkedin.com" in url_lower:
        return "linkedin"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    elif "instagram.com" in url_lower:
        return "instagram"
    elif "facebook.com" in url_lower or "fb.com" in url_lower:
        return "facebook"
    return "other"


_BOT_UA_PLATFORMS = {"twitter", "instagram", "facebook"}


def _clean_name(raw_name: str, platform: str) -> str:
    if not raw_name:
        return ""
    name = raw_name.strip()
    name = re.sub(r"\s*[|\-–—].*$", "", name)
    name = re.sub(
        r"\s*on (LinkedIn|Twitter|Facebook|X).*$", "", name, flags=re.IGNORECASE
    )
    name = re.sub(r",\s*(PhD|MD|MBA|CPA|PE|PMP|CFA|JD|Esq)\.?.*$", "", name)
    name = name.strip()

    if name == name.lower() or name == name.upper():
        name = name.title()

    return name


def _clean_linkedin_description(desc: str) -> str:
    """Extract meaningful content from LinkedIn's OG description format."""
    if not desc:
        return ""

    desc = re.sub(r"\s*·\s*\d+\+?\s*connections?\s*", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s*·\s*Connect\s*$", "", desc, flags=re.IGNORECASE)

    parts = [p.strip() for p in desc.split("·") if p.strip()]
    cleaned_parts = []
    for part in parts:
        if re.match(r"^(Location|Connections):", part, re.IGNORECASE):
            continue
        part = re.sub(r"^(Experience|Education|Location):\s*", "", part)
        if part:
            cleaned_parts.append(part)

    return " · ".join(cleaned_parts) if cleaned_parts else desc.strip()


def _is_valid_profile_image(url: str) -> bool:
    """Check if an image URL is likely a real profile photo, not a placeholder."""
    if not url:
        return False
    lower = url.lower()
    if "/aero-v1/sc/h/" in lower:
        return False
    if "ghost" in lower or "default" in lower:
        return False
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

        # Save raw download to a temp file, then optimize
        import tempfile

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
        total_bytes = 0
        for chunk in resp.iter_content(8192):
            tmp.write(chunk)
            total_bytes += len(chunk)
        tmp.close()

        if total_bytes < 1000:
            os.remove(tmp.name)
            return None, "Downloaded image is too small (likely a placeholder)"

        from app.services.images import save_and_optimize

        try:
            filename = save_and_optimize(tmp.name)
        finally:
            if os.path.exists(tmp.name):
                os.remove(tmp.name)

        return filename, None
    except requests.RequestException as e:
        return None, f"Failed to download image: {e}"


def _extract_linkedin_profile_text(soup: BeautifulSoup, name: str) -> dict[str, str]:
    """Extract profile data from authenticated LinkedIn HTML."""
    result: dict[str, str] = {"headline": "", "company": "", "location": ""}

    contact_el = soup.find(string=re.compile("Contact info"))
    if not contact_el:
        return result

    container = contact_el
    for _ in range(6):
        if hasattr(container, "parent") and container.parent:
            container = container.parent

    if not isinstance(container, Tag):
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
    """Extract the best profile photo URL from authenticated LinkedIn HTML."""
    roots = re.findall(
        r"(https://media\.licdn\.com/dms/image/v2/[A-Za-z0-9_-]+/profile-displayphoto-)",
        html_text,
    )
    if not roots:
        return ""

    for size in ("400_400", "800_800", "200_200", "100_100"):
        pattern = rf'shrink_{size}(/[^"\\<>\s]+(?:\\u0026[^"\\<>\s]+)*)'
        suffixes = re.findall(pattern, html_text)
        if suffixes:
            suffix = f"shrink_{size}{suffixes[0]}"
            full_url = roots[0] + suffix
            full_url = full_url.encode("utf-8").decode("unicode_escape")
            return full_url

    return ""


def _scrape_linkedin(url: str, soup: BeautifulSoup) -> dict[str, Any]:
    """LinkedIn-specific scraping with fallbacks."""
    og = _extract_og_tags(soup)
    tw = _extract_twitter_tags(soup)

    raw_name = og.get("title", "") or tw.get("title", "")
    if not raw_name:
        title_tag = soup.find("title")
        raw_name = title_tag.get_text() if isinstance(title_tag, Tag) else ""
    name = _clean_name(raw_name, "linkedin")

    raw_desc = og.get("description", "") or tw.get("description", "")
    description = _clean_linkedin_description(raw_desc)

    is_authenticated_page = not og.get("description")
    if is_authenticated_page:
        profile_text = _extract_linkedin_profile_text(soup, name)
        if profile_text["headline"] and not description:
            parts = [profile_text["headline"]]
            if profile_text["company"]:
                parts.append(profile_text["company"])
            description = " · ".join(parts)
            raw_desc = description

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


def _scrape_twitter(url: str, soup: BeautifulSoup) -> dict[str, Any]:
    """Twitter/X scraping using OG tags (served to bot UAs)."""
    og = _extract_og_tags(soup)
    tw = _extract_twitter_tags(soup)

    raw_name = og.get("title", "") or tw.get("title", "")
    name_match = re.match(r"^(.+?)\s*\(@\w+\)", raw_name)
    name = (
        name_match.group(1).strip() if name_match else _clean_name(raw_name, "twitter")
    )

    description = og.get("description", "") or tw.get("description", "")
    image_url = og.get("image", "") or tw.get("image:src", "") or tw.get("image", "")

    if image_url and "_200x200" in image_url:
        image_url = image_url.replace("_200x200", "_400x400")

    return {
        "name": name,
        "raw_description": description,
        "description": description,
        "image_url": image_url,
    }


def _scrape_instagram(url: str, soup: BeautifulSoup) -> dict[str, Any]:
    """Instagram scraping using OG tags (served to bot UAs)."""
    og = _extract_og_tags(soup)

    raw_name = og.get("title", "")
    # OG title: "Erez Abrams (@eiis1000) • Instagram photos and videos"
    name_match = re.match(r"^(.+?)\s*\(@\w+\)", raw_name)
    name = (
        name_match.group(1).strip()
        if name_match
        else _clean_name(raw_name, "instagram")
    )

    # The meta description has the real bio:
    # '313 Followers, 358 Following, 0 Posts - Erez Abrams (@eiis1000) on Instagram: "physics, music, enthusiasm | MIT '26"'
    description = ""
    raw_desc = ""
    for meta in soup.find_all("meta"):
        attr_name = _meta_attr(meta, "name")
        if attr_name == "description":
            raw_desc = _meta_attr(meta, "content")
            break

    if raw_desc:
        # Extract the quoted bio if present
        bio_match = re.search(r'["""](.+?)["""]', raw_desc)
        if bio_match:
            description = bio_match.group(1)
        else:
            description = raw_desc

    image_url = og.get("image", "")
    # Instagram OG images are small (100x100). Try to get a larger version.
    if image_url and "s100x100" in image_url:
        image_url = image_url.replace("s100x100", "s320x320")

    return {
        "name": name,
        "raw_description": raw_desc,
        "description": description,
        "image_url": image_url,
    }


def _scrape_facebook(url: str, soup: BeautifulSoup) -> dict[str, Any]:
    """Facebook scraping using OG tags (served to bot UAs)."""
    og = _extract_og_tags(soup)

    name = og.get("title", "")
    # Facebook OG title is usually just the name, clean
    name = _clean_name(name, "facebook")

    # Facebook's OG description is generic boilerplate, not useful
    # But the actual page content might have better info
    raw_desc = og.get("description", "")
    description = ""
    if raw_desc and "is on Facebook" not in raw_desc:
        description = raw_desc

    image_url = og.get("image", "")

    return {
        "name": name,
        "raw_description": raw_desc,
        "description": description,
        "image_url": image_url,
    }


def _collect_page_images(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    """Collect image entries from a page, resolving relative URLs."""
    from urllib.parse import urljoin

    entries: list[dict[str, str]] = []
    for img in soup.find_all("img"):
        src = _meta_attr(img, "src")
        if not src or src.startswith("data:"):
            continue
        alt = _meta_attr(img, "alt")
        full_src = urljoin(base_url, src)
        entries.append({"src": full_src, "alt": alt})
    return entries


def _find_profile_image_heuristic(images: list[dict[str, str]], name: str) -> str:
    """Try to pick the profile photo from page images using simple heuristics."""
    name_lower = name.lower() if name else ""
    profile_keywords = {"profile", "photo", "headshot", "avatar", "portrait", "pfp"}

    for img in images:
        src_lower = img["src"].lower()
        alt_lower = img["alt"].lower()
        if name_lower and name_lower in alt_lower:
            return img["src"]
        if any(kw in src_lower or kw in alt_lower for kw in profile_keywords):
            return img["src"]
    return ""


def _scrape_generic(url: str, soup: BeautifulSoup) -> dict[str, Any]:
    """Generic scraping: OG tags first, then HTML heuristics, then LLM."""
    og = _extract_og_tags(soup)
    tw = _extract_twitter_tags(soup)

    name = og.get("title", "") or tw.get("title", "")
    if not name:
        title_tag = soup.find("title")
        name = title_tag.get_text() if isinstance(title_tag, Tag) else ""
    name = _clean_name(name, "other")

    description = og.get("description", "") or tw.get("description", "")
    image_url = og.get("image", "") or tw.get("image", "")

    page_images = _collect_page_images(soup, url)

    # If OG tags gave us enough, return early
    if name and description and image_url:
        return {
            "name": name,
            "raw_description": description,
            "description": description,
            "image_url": image_url,
        }

    # Try LLM extraction from the page content
    page_text = soup.get_text(separator="\n", strip=True)
    llm_result = extract_profile_from_html(page_text, page_images, url)

    if llm_result:
        if not name and llm_result.get("name"):
            name = llm_result["name"]
        if not description and llm_result.get("context"):
            description = llm_result["context"]
        if not image_url and llm_result.get("image_url"):
            image_url = llm_result["image_url"]

    # Heuristic fallbacks if LLM wasn't available or missed something
    if not name:
        for tag in soup.find_all(["h1", "h2"]):
            text = tag.get_text(strip=True)
            if 2 < len(text) < 60:
                name = text
                break

    if not image_url:
        image_url = _find_profile_image_heuristic(page_images, name)

    return {
        "name": name,
        "raw_description": description,
        "description": description,
        "image_url": image_url,
    }


@scraper_bp.route("/url", methods=["POST"])
def scrape_url():
    """Scrape a profile URL and return extracted data for form pre-fill."""
    data = request.get_json(silent=True) or {}
    url: str = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    platform = _detect_platform(url)

    if platform == "twitter":
        match = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)", url)
        if match:
            url = f"https://x.com/{match.group(1)}"
    warnings: list[str] = []

    req_headers = (
        {**_HEADERS, "User-Agent": "facebookexternalhit/1.1"}
        if platform in _BOT_UA_PLATFORMS
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

    if resp.status_code == 999 or (
        platform == "linkedin" and "authwall" in resp.text.lower()
    ):
        hint = (
            "Set LINKEDIN_LI_AT in your .env to enable authenticated scraping. "
            "Get this cookie from your browser dev tools (Application > Cookies > li_at)."
            if not _LINKEDIN_COOKIE
            else "Your LinkedIn session cookie may have expired. Refresh it from your browser."
        )
        return (
            jsonify({"error": f"LinkedIn blocked this request (auth wall). {hint}"}),
            400,
        )

    if resp.status_code == 404:
        hint = (
            " This account may not exist or may have a different handle."
            if platform == "twitter"
            else ""
        )
        return jsonify({"error": f"Page not found (404).{hint}"}), 400

    if resp.status_code >= 400:
        return jsonify({"error": f"Page returned HTTP {resp.status_code}"}), 400

    soup = BeautifulSoup(resp.text, "html.parser")

    if platform == "linkedin":
        result = _scrape_linkedin(url, soup)
    elif platform == "twitter":
        result = _scrape_twitter(url, soup)
    elif platform == "instagram":
        result = _scrape_instagram(url, soup)
    elif platform == "facebook":
        result = _scrape_facebook(url, soup)
    else:
        result = _scrape_generic(url, soup)

    if not result["name"]:
        warnings.append("Could not extract name from this page")

    if not result["description"]:
        warnings.append("No description/bio found on this page")

    face_filename = None
    if result["image_url"]:
        face_filename, img_error = _download_image(result["image_url"], cookies=cookies)
        if img_error:
            if "403" in str(img_error) and platform in (
                "linkedin",
                "instagram",
                "facebook",
            ):
                warnings.append(
                    "Found the profile photo but the download was blocked. "
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

    raw_context = result["description"][:300] if result["description"] else ""

    return jsonify(
        {
            "name": result["name"],
            "face_filename": face_filename,
            "context1": raw_context,
            "raw_description": result.get("raw_description", raw_context),
            "source": platform,
            "source_url": url,
            "warnings": warnings,
        }
    )


@scraper_bp.route("/summarize", methods=["POST"])
def summarize():
    """Summarize a description using LLM. Called async after scrape returns."""
    req_data = request.get_json(silent=True) or {}
    description: str = req_data.get("description", "").strip()
    name: str = req_data.get("name", "").strip()

    if not description:
        return jsonify({"summary": ""}), 200

    llm_result = summarize_context(description, name)
    if llm_result:
        return jsonify({"summary": llm_result})
    return jsonify({"summary": ""}), 200
