# Names & Faces

A locally-hosted web tool for generating multi-directional [Anki](https://apps.ankiweb.net/) flashcards to help you learn people's names and faces.

Add people via manual entry, profile URL scraping, or CSV import. Each person becomes up to four Anki cards that test your recall from different angles. Re-export your deck at any time without losing review progress.

## Card Directions

Each person can generate up to four card types (all enabled by default, individually toggleable):

| Card | Front (Question) | Back (Answer) |
|------|-----------------|---------------|
| **Face → Name** | Photo | Name + context |
| **Name → Face** | Name | Photo + context |
| **Name + Face → Context** | Photo + name | Context details |
| **Context → Person** | Context clues | Photo + name |

Cards are only generated when the required data exists (e.g., "Face → Name" requires a photo, context cards require at least one context field).

## Quick Start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
git clone https://github.com/yourusername/names-and-faces.git
cd names-and-faces
uv run python run.py
```

Open [http://localhost:5050](http://localhost:5050).

## Auto-Start on Login (macOS)

Run the install script once to start the server automatically when you log in:

```bash
bash scripts/install-launchd.sh
```

The server will always be available at [http://localhost:5050](http://localhost:5050) with no terminal needed.

To remove:

```bash
bash scripts/uninstall-launchd.sh
```

## Data Storage

Your database and photos are stored outside the repo at `~/.names-and-faces/` by default. This keeps your personal data separate from the codebase.

To customize the location (e.g., for iCloud backup):

```bash
export NAMES_AND_FACES_DATA_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/names-and-faces-data"
```

Set this before running `install-launchd.sh` and it will be baked into the launch agent.

## Input Modes

### Manual Entry

Add a person with a name, photo upload, and optional context fields. Select which card directions to generate.

### Profile URL Scraping

Paste a LinkedIn, Twitter/X, Facebook, or other profile URL. The tool extracts name, photo, and bio via OpenGraph meta tags and pre-fills the form for you to review before saving.

### CSV Import

Upload a CSV file for bulk import. Required column: `name`. Optional columns: `photo_url`, `context1`, `context2`.

```csv
name,photo_url,context1,context2
Jane Doe,https://example.com/jane.jpg,CEO at Acme Corp,Met at tech conference
John Smith,,Engineer at Widgets Inc,College roommate
```

## Deck Export

Click **Export Deck** to download a `.apkg` file. Import it into Anki. On subsequent exports, existing cards are updated in place — your review history, intervals, and scheduling are fully preserved thanks to stable note GUIDs.

## Development

```bash
uv run python run.py         # Start dev server
uvx ruff format .             # Format code
uvx ruff check .              # Lint
```
