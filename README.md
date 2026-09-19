# Names & Faces

Generate multi-directional [Anki](https://apps.ankiweb.net/) flashcards for learning people's names and faces. Add people via profile URL scraping (LinkedIn, Twitter/X, Instagram, Facebook, personal sites), manual entry, or CSV import. Re-export your deck at any time without losing review progress.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
git clone https://github.com/adamkaufman/names-and-faces.git
cd names-and-faces
```

Optionally, configure a .env file with API keys (see below). Then run the setup script (note that this was written for mac, maybe ask an LLM to update it for you if you're running something else):

```bash
bash scripts/install-launchd.sh
```

The server is now running at [http://localhost:5050](http://localhost:5050) and will auto-start on login. To run manually instead: `uv run python run.py`.

If [Tailscale](https://tailscale.com/) is running, the install script automatically configures `tailscale serve` so you can access the app from any device on your tailnet (e.g. your phone). The tailnet URL is printed at the end of the install output. It uses HTTPS if certificates are enabled for your tailnet (admin console, DNS, "HTTPS Certificates"), which lets phone browsers install the app to the home screen; otherwise it falls back to HTTP.

To uninstall the auto-start: `bash scripts/uninstall-launchd.sh`

### Managing the service

The LaunchAgent is `~/Library/LaunchAgents/com.namesandfaces.server.plist`. It starts at login and restarts if it crashes. Logs go to `~/Library/Logs/names-and-faces.log`.

```bash
# restart (e.g. after pulling changes)
launchctl kickstart -k gui/$(id -u)/com.namesandfaces.server

# stop / start
launchctl bootout gui/$(id -u)/com.namesandfaces.server
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.namesandfaces.server.plist

# check status and tail logs
launchctl print gui/$(id -u)/com.namesandfaces.server | grep -E "state|last exit"
tail -f ~/Library/Logs/names-and-faces.log
```

If the service shows `last exit code = 78: EX_CONFIG` and never starts, launchd could not spawn it (typically because a path in the plist is unavailable). Re-run `bash scripts/install-launchd.sh` to regenerate the plist.

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
# NAMES_AND_FACES_DATA_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/names-and-faces-data"
```

After editing `.env`, run `bash scripts/install-launchd.sh` to apply.

## Keeping cards fresh after edits

Re-exporting and importing the deck never touches your review schedule: notes are matched by a stable ID, so Anki just updates their content. That is usually what you want, but when someone's name, photo, or context changes, the cards that test that information are effectively new material.

On a person's edit page, tick **Review changed cards soon** before saving. The app works out which card types the edit affects (a context change flags only the two context cards; a name or photo change flags all four) and remembers them. Then:

1. **Export** the deck and import it into Anki as usual. Flagged notes carry `nf::review-soon::<card>` tags (Anki replaces tags on re-import).
2. **Reschedule** the cards. A banner on the home page lists the flagged people and offers two routes:
   - If Anki desktop is open with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on, click **Reschedule in Anki** (due today, tomorrow, within 3 days, or reset to new). Set `ANKICONNECT_URL` in `.env` if it is not on the default `http://127.0.0.1:8765`.
   - Otherwise copy the search string from the banner into Anki's browser (desktop or AnkiMobile), select all, and use **Set Due Date**. The search matches only the affected card types, not the person's other cards.
3. **Clear flags** (done automatically after an AnkiConnect reschedule). The tags disappear from Anki on the next export + import.

## Anki desktop integration (AnkiConnect)

With Anki desktop open on the same machine and the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on installed, an "Anki desktop connected" panel appears on the home page. Set `ANKICONNECT_URL` in `.env` if the add-on is not on the default `http://127.0.0.1:8765`.

- **Push to Anki** replaces export/download/import: it builds the deck, imports it, brings forward the cards of anyone flagged for early review (today / tomorrow / within 3 days / reset), suspends the notes of people in the trash, and syncs with AnkiWeb. Then sync on your phone.
- **Suspended or gone in Anki**: people you suspended or deleted on the Anki side but who are still active here, with a one-click move to the trash.
- **Edited in Anki**: name or context fields changed in Anki more recently than in the app (for example fixed on your phone mid-review). Apply them here, otherwise the next push overwrites them.
- **Notes with no active person**: notes left in Anki for people removed here. Suspend is the default action (keeps review history); delete is available too.
- **Order people by** lapses, shortest interval, never reviewed, or fewest reviews, with a badge on each card showing lapses and current interval.

Notes are matched to people by exact name, falling back to the photo filename, so a rename or photo swap you have not pushed yet still matches.

## Trash

Deleting a person moves them to the trash (linked from the count on the home page) rather than removing them. Trashed people are excluded from the grid, exports, and duplicate checks, and their photos are kept, so a mistaken deletion can be undone with **Restore**. **Delete forever** or **Empty trash** removes them and their photos for good. Anki notes for trashed people show up in the stale-notes list when AnkiConnect is connected.

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
