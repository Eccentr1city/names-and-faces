"""Optional LLM integration for processing scraped content.

Set ANTHROPIC_API_KEY in the environment to enable. If not set, LLM features
are silently skipped and the raw scraped text is used as-is.
"""

import json
import os

_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_SUMMARIZE_PROMPT = """You are a concise summarizer. Given a person's bio or description
from a social media profile, extract ONLY the most memorable and identifying information.

Output a single short line (under 100 characters) that captures their role and organization,
or the most distinctive thing about them. No filler, no adjectives like "experienced" or
"passionate". Just the facts that would help someone remember who this person is.

Examples:
- "ML researcher at DeepMind, works on language models"
- "CEO of Stripe"
- "Philosophy professor at NYU"
- "Cofounder of Reddit, investor"

Many of the people will be related to AI safety; often an org name suffices and you don't need to specify that they work on AI safety or alignment. Only specify if it's a larger org that has many plausible roles. Abbreviate Google DeepMind as "GDM".
"""

_EXTRACT_PROMPT = """You are extracting structured profile information from a personal webpage.

Given the visible text content and a list of image URLs from the page, extract:
1. The person's full name
2. A concise context line (under 100 chars) -- their role, organization, or most identifying fact
3. The URL of their profile/headshot photo (if any)

Respond with ONLY a JSON object, no markdown:
{"name": "...", "context": "...", "image_url": "..."}

For image_url, pick the image most likely to be a profile photo/headshot based on its
filename or alt text (look for words like "profile", "photo", "headshot", "avatar", or
the person's name). If no suitable image exists, use an empty string.

If you can't determine a field, use an empty string for it."""


def _call_claude(system: str, user_content: str, max_tokens: int = 150) -> str | None:
    if not _API_KEY:
        return None
    try:
        import requests

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user_content}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()
    except Exception:
        return None


def summarize_context(description: str, name: str = "") -> str | None:
    """Distill a verbose bio into a concise context line."""
    if not description.strip():
        return None
    result = _call_claude(_SUMMARIZE_PROMPT, f"Person: {name}\nBio: {description}")
    if result and result.startswith('"') and result.endswith('"'):
        result = result[1:-1]
    return result


def extract_profile_from_html(
    text_content: str, image_entries: list[dict[str, str]], page_url: str
) -> dict[str, str] | None:
    """Use Claude to extract profile info from a webpage's text and images.

    Args:
        text_content: Visible text from the page (first ~2000 chars).
        image_entries: List of {"src": url, "alt": alt_text} for images on the page.
        page_url: The URL of the page being scraped.

    Returns:
        {"name": ..., "context": ..., "image_url": ...} or None if LLM unavailable.
    """
    if not _API_KEY:
        return None

    images_desc = "\n".join(
        f'  - src="{e["src"]}" alt="{e["alt"]}"' for e in image_entries[:20]
    )
    user_msg = (
        f"Page URL: {page_url}\n\n"
        f"Page text:\n{text_content[:3000]}\n\n"
        f"Images on page:\n{images_desc}"
    )

    result = _call_claude(_EXTRACT_PROMPT, user_msg, max_tokens=200)
    if not result:
        return None

    try:
        # Strip markdown fences if present
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        return None
