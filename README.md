# Names & Faces

Generate multi-directional [Anki](https://apps.ankiweb.net/) flashcards for learning people's names and faces. Add people via profile URL scraping (LinkedIn, Twitter/X, Instagram, Facebook, personal sites), manual entry, or CSV import. Re-export your deck at any time without losing review progress.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
git clone https://github.com/adamkaufman/names-and-faces.git
cd names-and-faces
```

Optionally, configure a .env file with API keys (see below). Then run the setup script:

```bash
bash scripts/install-launchd.sh
```

The server is now running at [http://localhost:5050](http://localhost:5050) and will auto-start on login. To run manually instead: `uv run python run.py`.

To uninstall the auto-start: `bash scripts/uninstall-launchd.sh`

## Configuration (.env)

All optional. The app works without any of these, but they unlock better scraping and AI features.

```bash
# LinkedIn session cookie -- unlocks profiles blocked by LinkedIn's auth wall.
# Get it: open linkedin.com > DevTools (Cmd+Option+I) > Application > Cookies > li_at
LINKEDIN_LI_AT=

# Anthropic API key -- auto-summarizes scraped bios into concise context lines.
ANTHROPIC_API_KEY=

# Custom data directory (default: ~/.names-and-faces).
# Set to an iCloud path for automatic backup:
# NAMES_AND_FACES_DATA_DIR=~/Library/Mobile Documents/com~apple~CloudDocs/names-and-faces-data
```

After editing `.env`, run `bash scripts/install-launchd.sh` to apply.

## CSV Import

Required column: `name`. Optional: `photo_url`, `context`.

```csv
name,photo_url,context
Jane Doe,https://example.com/jane.jpg,CEO at Acme Corp
John Smith,,Engineer at Widgets Inc
```

## Development

```bash
uv run python run.py           # Dev server with auto-reload
uvx ruff format . && uvx ruff check .  # Format + lint
uv run python scripts/optimize-images.py  # Resize existing photos
```
