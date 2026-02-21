"""Optional LLM integration for processing scraped content.

Set ANTHROPIC_API_KEY in the environment to enable. If not set, LLM features
are silently skipped and the raw scraped text is used as-is.
"""

import os

_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_SYSTEM_PROMPT = """You are a concise summarizer. Given a person's bio or description
from a social media profile, extract ONLY the most memorable and identifying information.

Output a single short line (under 100 characters) that captures their role and organization,
or the most distinctive thing about them. No filler, no adjectives like "experienced" or
"passionate". Just the facts that would help someone remember who this person is.

Examples:
- "ML researcher at DeepMind, works on language models"
- "CEO of Stripe"
- "Philosophy professor at NYU"
- "Cofounder of Reddit, investor"
"""


def summarize_context(description: str, name: str = "") -> str | None:
    """Use Claude to distill a verbose bio into a concise context line.

    Returns None if LLM is not configured or the call fails, so callers
    can fall back to the raw description.
    """
    if not _API_KEY or not description.strip():
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
                "max_tokens": 100,
                "system": _SYSTEM_PROMPT,
                "messages": [
                    {
                        "role": "user",
                        "content": f"Person: {name}\nBio: {description}",
                    },
                ],
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        content = result["content"][0]["text"].strip()
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        return content
    except Exception:
        return None
