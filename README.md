# Names & Faces

A small personal web app for remembering who people are. You add someone by pasting their LinkedIn, X, or personal-site URL (or typing them in), the app grabs a photo and a one-line "context" such as *"CEO of Redwood Research"*, and it generates [Anki](https://apps.ankiweb.net/) flashcards in four directions: face → name, name → face, name + face → context, and context → person. You review the cards on your phone like any other Anki deck. When someone changes jobs you edit them here, push the deck again, and only the cards that actually changed come up for review; everything else keeps its schedule. It runs as an always-on service on a Mac, is reachable from your phone over Tailscale, and talks to Anki desktop directly so that pushing a deck, rescheduling cards, and cleaning up people you have suspended in Anki are each one click.

The rest of this document describes how the pieces fit together and how to reproduce the setup on another machine.

## How it fits together

```
 phone (Tailscale) ──► Flask app on the Mac (port 5050, launchd)
                          │  SQLite + photos in the data dir (iCloud)
                          │
                          ├─► .apkg export (genanki)  ──► import into Anki (by hand)
                          │
                          └─► AnkiConnect (Anki desktop add-on, localhost)
                                 push deck · reschedule · suspend · read stats
                                          │
                                     AnkiWeb sync ──► AnkiMobile on the phone
```

- **App**: Flask + SQLAlchemy, single `people` table, photos as JPEGs on disk. No auth; it is meant to be reachable only on localhost and your tailnet.
- **Deck**: one Anki deck called `Names and Faces`, one note per person. Note GUIDs derive from the person's database id, so re-importing updates content and never duplicates or resets scheduling.
- **AnkiConnect** (optional but recommended): when Anki desktop is open on the same Mac, the app pushes the deck, reschedules flagged cards, suspends notes of trashed people, pulls edits made in Anki, and shows review stats. Without it, you export an `.apkg` and import by hand.

## Current hosting

Runs on the home server `perihelion` in Docker: https://perihelion.tail18d97e.ts.net:5050/ (tailnet only).
Data (SQLite + photos) lives in `/srv/data/names-and-faces`, snapshotted hourly (a pre-backup hook takes a consistent
SQLite copy). Secrets are in `/srv/secrets/names-and-faces.env` on perihelion (source of truth: 1Password), not in the repo.
AnkiConnect is reached on the Mac over Tailscale (`tailscale serve --https=8766` on the Mac, with an `apiKey` set in the
add-on's config), so Anki features work whenever the Mac is awake with Anki open.

Deploy: `rsync -a --delete --exclude-from=.dockerignore ./ perihelion:/srv/apps/names-and-faces/ && ssh perihelion 'cd /srv/apps/names-and-faces && docker compose up -d --build'`.
Logs: `ssh perihelion 'docker logs names-and-faces-names-and-faces-1'`. The Mac LaunchAgent (`com.namesandfaces.server`) is disabled;
the macOS sections below describe how it ran before and still work for local use.

## Quick start (any OS)

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+ (uv will fetch Python if needed).

```bash
git clone https://github.com/adamkaufman/names-and-faces.git
cd names-and-faces
cp .env.example .env 2>/dev/null || true   # optional; see Configuration
uv run python run.py                        # http://localhost:5050
```

`run.py` loads `.env`, creates the data directory and database on first start, applies any schema migrations, and serves with Flask's debug reloader (code edits take effect immediately, including when running under launchd).

## Always-on service on macOS (launchd)

```bash
bash scripts/install-launchd.sh
```

The script:

1. Reads `.env` (if present) for `NAMES_AND_FACES_PORT`, `NAMES_AND_FACES_DATA_DIR`, `LINKEDIN_LI_AT`, `ANTHROPIC_API_KEY`.
2. Writes `~/Library/LaunchAgents/com.namesandfaces.server.plist` running `uv run python run.py` in the repo directory, `RunAtLoad` + `KeepAlive`, with stdout/stderr to `~/Library/Logs/names-and-faces.log`.
3. Boots the agent with `launchctl bootstrap gui/$(id -u) …`.
4. If Tailscale is running, registers `tailscale serve` for the port (see Phone access).

Re-run it after changing `.env` (it re-bakes the env vars into the plist). Uninstall with `bash scripts/uninstall-launchd.sh`.

Managing the service:

```bash
launchctl kickstart -k gui/$(id -u)/com.namesandfaces.server          # restart
launchctl bootout   gui/$(id -u)/com.namesandfaces.server              # stop
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.namesandfaces.server.plist   # start
launchctl print     gui/$(id -u)/com.namesandfaces.server | grep -E "state|last exit"
tail -f ~/Library/Logs/names-and-faces.log
```

Troubleshooting:

- `last exit code = 78: EX_CONFIG` with `runs` climbing and nothing in the log means launchd could not spawn the process at all. The usual cause is a path in the plist launchd cannot open. Notably, **do not point `StandardOutPath` at iCloud Drive**; after a machine restore launchd could not open those files and the service silently never started. Re-run the install script to regenerate the plist.
- The plist hard-codes the `uv` path found at install time (Homebrew's `/opt/homebrew/bin/uv` on Apple silicon). If `uv` moves, re-run the install script.
- Because the service runs Flask's reloader, saving a file in `app/` restarts the live server. Test risky changes against a copy of the database (see Data).

On Linux the equivalent is a systemd user unit running `uv run python run.py` with `WorkingDirectory` set to the repo and the same environment variables; nothing in the app is macOS-specific except the install scripts, the LinkedIn cookie helper, and the App Nap note below.

## Phone access (Tailscale)

The install script runs `tailscale serve --bg --https <port> http://127.0.0.1:<port>`, falling back to `--http` if HTTPS certificates are not enabled for the tailnet (enable them in the Tailscale admin console under DNS → HTTPS Certificates; HTTPS is what lets iOS "Add to Home Screen" install it as a standalone app using `app/static/manifest.json`). The URL is printed at the end of the install output and looks like `https://<machine>.<tailnet>.ts.net:5050`. Check or remove with `tailscale serve status` / `tailscale serve --https=5050 off`.

On the phone, type the scheme explicitly (`https://…`) or the browser may treat the hostname as a search.

## Configuration (`.env`)

All optional. Loaded by `run.py` via `python-dotenv` at process start, so restart the service after editing.

| Variable | Default | Purpose |
|---|---|---|
| `NAMES_AND_FACES_PORT` | `5050` | Port for the Flask server and the Tailscale serve entry. |
| `NAMES_AND_FACES_DATA_DIR` | `~/.names-and-faces` | Where the database and photos live. Set to an iCloud path for automatic backup, e.g. `"$HOME/Library/Mobile Documents/com~apple~CloudDocs/names-and-faces-data"`. |
| `LINKEDIN_LI_AT` | unset | LinkedIn `li_at` session cookie; unlocks profiles behind the login wall. Get it from Chrome DevTools → Application → Cookies → `linkedin.com`, or `eval $(bash scripts/get-linkedin-cookie.sh)` on macOS. Expires every few months; to refresh it on perihelion run `bash scripts/push-linkedin-cookie.sh` on the Mac. |
| `ANTHROPIC_API_KEY` | unset | Lets the scraper summarise a bio into a one-line context and extract profile info from arbitrary personal sites (`app/services/llm.py`). |
| `ANKICONNECT_URL` | `http://127.0.0.1:8765` | Where the AnkiConnect add-on listens. Change if you moved AnkiConnect off its default port. |

## Data

The data directory contains `names_and_faces.db` (SQLite) and `media/<uuid>.jpg` (photos, resized to 400px max on upload). Everything about a person is one row in `people`; the important columns beyond name, photo, context, and the four per-card toggles are:

- `review_soon_cards`: comma-separated card keys flagged for early review (see Editing).
- `deleted_at`: set when the person is in the trash. Trashed people are excluded from the grid, export, duplicate check, and Anki matching.
- `updated_at`: when the person's *content* last changed. Set explicitly on edits and when an Anki edit is applied, deliberately not on every write, because it is compared against Anki's note modification time to detect edits made in Anki.
- `anki_synced_at`: last time the person was pushed via AnkiConnect. Distinguishes "new, not yet in Anki" from "was in Anki, since deleted there".

Schema changes: `db.create_all()` creates tables; new columns on the existing table are added by `_add_missing_columns()` in `app/__init__.py` (a dict of `ALTER TABLE ADD COLUMN` statements run at startup if the column is absent). Add new columns there rather than editing the database by hand.

To test against real data without risk, copy the database to a scratch directory and start a second instance:

```bash
mkdir -p /tmp/naf/media && cp "$DATA_DIR/names_and_faces.db" /tmp/naf/
NAMES_AND_FACES_DATA_DIR=/tmp/naf NAMES_AND_FACES_PORT=5098 uv run python run.py
```

## The Anki deck

Defined in `app/services/deck_generator.py` with templates in `app/services/card_templates/`.

- Deck: `Names and Faces` (id `1704067338`). Note type: `Names and Faces` (id `1704067337`). If Anki shows the note type as `Names and Faces+`, that is Anki's rename after a schema change on import; the app does not care about the note type name.
- Fields: `Name`, `Face` (an `<img>` tag), `Context`, and four toggle fields `FaceToName`, `NameToFace`, `NameFaceToContext`, `ContextToPerson` holding `1` or empty. Each card template is wrapped in a conditional on its toggle, so Anki only generates the cards a person has enabled (and only when the photo/context needed for that card exists).
- Card templates, in order (Anki ordinals 0–3; `card:1`–`card:4` in searches): `Face to Name`, `Name to Face`, `Name and Face to Context`, `Context to Person`. The CSS shows and hides fields per card via `.card1`–`.card4`; the back shows everything.
- Note GUID = `genanki.guid_for(person.id)`. Importing an updated deck matches on GUID and updates fields and tags when the incoming note is newer (genanki stamps export time), leaving scheduling untouched. Importing never deletes notes.
- Media files are referenced by filename; the export bundles every photo in the deck.

## Workflows

**Adding people.** *Add Person* → paste a profile URL → *Fetch*. The scraper (`app/routes/scraper.py`) handles LinkedIn (needs the cookie for most profiles), X/Twitter, Instagram, Facebook, and generic pages (Open Graph tags, with LLM extraction if an API key is set). Review the name, photo, and context, then save. Duplicate names are flagged as you type. Photos can also be uploaded, dragged in, or pasted from the clipboard. *Import CSV* takes `name` plus optional `photo_url` and `context` columns and shows a preview before importing.

**Editing.** Change anything on a person's page and save. If the change should be re-learned, tick **Review changed cards soon** before saving: the app maps the changed fields to the card types that test them (context → the two context cards; name or photo → all four) and stores them in `review_soon_cards`. Flagged people show an amber badge on the grid and are listed in a banner on the home page. Flags are cleared when the cards are rescheduled (by Push, or by the banner's button after a manual import). Everything not flagged keeps its schedule.

**Trash.** Delete moves a person to the trash (undo link in the confirmation; `/trash` lists them with Restore, Delete forever, Empty trash). Trashed people vanish from exports; their photos are kept until purged. Their Anki notes are suspended (never deleted) on the next Push.

**Getting cards into Anki, with AnkiConnect (preferred).** Click **Push to Anki** on the home page. It exports, imports via AnkiConnect, brings forward exactly the flagged card types (dropdown: due today / tomorrow / within 3 days / reset to new), suspends notes of trashed people, stamps `anki_synced_at`, and syncs with AnkiWeb. Then sync on the phone.

**Getting cards into Anki, by hand.** **Export Deck** downloads `names_and_faces.apkg`; import it in Anki desktop or AnkiMobile. Flagged notes carry tags `nf::review-soon` and `nf::review-soon::<card_key>`. To reschedule them, copy the search string from the banner (it combines each tag with its `card:N` ordinal so only the affected card types match), paste it into Anki's browser, select all, and use *Set Due Date*. Then click *Clear flags*. Tags disappear from Anki on the next import after clearing.

## Anki desktop integration (AnkiConnect)

Setup on the Mac that runs the app:

1. Install Anki desktop and the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on: Tools → Add-ons → Get Add-ons → code `2055492159`, then restart Anki.
2. AnkiConnect listens on `127.0.0.1:8765` by default. If that port is taken (check with `lsof -nP -iTCP:8765 -sTCP:LISTEN`), change `webBindPort` in the add-on's config (Tools → Add-ons → AnkiConnect → Config, or the `config` key in `~/Library/Application Support/Anki2/addons21/2055492159/meta.json`), restart Anki, and set `ANKICONNECT_URL` in `.env` to match, then restart the service.
3. Stop macOS from putting Anki to sleep in the background, or requests will hang when Anki is not the frontmost app: `defaults write net.ankiweb.anki NSAppSleepDisabled -bool true`.
4. Verify: with Anki open and a profile loaded, `curl http://127.0.0.1:<port>` prints `AnkiConnect v.6`. The app checks for exactly that string, so another service on the port is not mistaken for Anki.
5. Log Anki desktop in to AnkiWeb so Push can sync. If Anki asks for a one-time full sync after a push, choose **Upload to AnkiWeb**: the desktop collection is the one the app writes to.

Anki only needs to be open on the Mac; the buttons work from the phone too because the app talks to AnkiConnect locally.

When connected, the home page shows an **Anki desktop connected** panel (`app/services/anki_sync.py`, driven by one JSON endpoint `GET /deck/anki/status` that reads the whole deck once and caches it for 20 s):

- **Push to Anki** (above).
- **Suspended or gone in Anki**: active people whose note is fully suspended in Anki, or who were pushed before but whose note no longer exists. One click moves them to the trash. This mirrors the habit of suspending a card in Anki when you meet it and decide the person should go.
- **Edited in Anki**: name or context whose Anki note was modified more recently than the person's `updated_at` and differs from the app. *Apply to app* copies Anki's value over; otherwise the next push overwrites the Anki edit.
- **Notes with no active person**: notes in the deck matching no active person (people removed before the trash existed, or in the trash). *Suspend in Anki* is the default action because it keeps review history; *Delete instead* is available. Notes already fully suspended are hidden and only counted.
- **Order people by** newest, lapses, shortest interval, never reviewed, or fewest reviews; each grid card gets a badge (`3 lapses · 14d`, `unseen`, `suspended`, `not in Anki`).

Matching notes to people: exact `Name` match first, then photo filename from the `Face` field. Using both means a rename or photo swap not yet pushed still matches its note. Server-side actions re-derive the allowed set before acting, so a request can only suspend/delete/trash items the panel is currently proposing.

## Development

```bash
uv run python run.py                        # dev server with reloader
uvx ruff format . && uvx ruff check .       # format + lint (a few pre-existing warnings are known)
uv run python scripts/optimize-images.py    # one-off: resize/convert existing photos
```

Layout:

```
run.py                         entry point: loads .env, create_app().run()
app/__init__.py                Flask factory, data dir, column migrations
app/models.py                  Person model (active()/trashed() queries, review-soon helpers, touch())
app/routes/people.py           grid, add/edit/delete, duplicate check, trash, media
app/routes/deck.py             export, review-soon clear/reschedule, all /deck/anki/* endpoints
app/routes/scraper.py          profile scraping per platform + LLM summarise endpoint
app/routes/import_csv.py       CSV upload and preview
app/services/deck_generator.py genanki model/deck; GUID = person id; tags for flagged cards
app/services/review_soon.py    card keys, field→card mapping, tag names, Anki search string
app/services/ankiconnect.py    thin AnkiConnect client (one function per action)
app/services/anki_sync.py      deck snapshot, note↔person matching, status(), push(), reconcile actions
app/services/images.py         resize/convert uploads
app/services/llm.py            Claude API calls (summarise bio, extract profile from HTML)
app/templates/                 Jinja + Tailwind (CDN) + Alpine.js; index.html holds the Anki panel JS
app/static/                    PWA manifest and icons
scripts/                       install/uninstall launchd, LinkedIn cookie helper, image optimiser
```

HTTP surface (all unauthenticated; JSON endpoints take and return JSON):

| Method, path | Purpose |
|---|---|
| `GET /` | Grid; `?q=` searches names |
| `GET,POST /add`, `GET,POST /edit/<id>`, `POST /delete/<id>` | Person CRUD (delete = trash) |
| `POST /check-duplicate` | `{name, exclude_id}` → `{duplicate, existing_*}` |
| `GET /trash`, `POST /trash/restore/<id>`, `POST /trash/purge/<id>`, `POST /trash/empty` | Trash |
| `GET /media/<file>` | Photos |
| `POST /scrape/url`, `POST /scrape/summarize` | Scraper and LLM summary |
| `GET,POST /import/csv`, `POST /import/csv/confirm` | CSV import |
| `POST /deck/export` | Download `.apkg` (optional `person_ids`) |
| `POST /deck/review-soon/clear`, `POST /deck/review-soon/reschedule` | Manual-import path for flagged cards |
| `GET /deck/anki/status` | Snapshot-derived panel data |
| `POST /deck/anki/push` (form `days`) | Push to Anki |
| `POST /deck/anki/pull` `{edits:[{person_id, field}]}` | Apply Anki edits |
| `POST /deck/anki/trash` `{person_ids}` | Trash people suspended/gone in Anki |
| `POST /deck/anki/stale/suspend` / `…/delete` `{note_ids}` | Act on orphaned notes |

Conventions: `uv` for everything Python, `ruff` via `uvx ruff`. Keep `Person.active()` rather than `Person.query` anywhere trashed people should not appear. Call `person.touch()` when content changes; do not reintroduce a column-level `onupdate`.
