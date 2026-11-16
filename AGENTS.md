# AGENTS.md

A single-file web UI (`index.html`) plus a Python proxy (`serve.py`) for bulk-correcting
misassigned faces in Immich. Python 3 standard library only: no package manager, build
step, test suite, or linter. All CSS and JS live inline in `index.html`.

## Run

- `python3 serve.py` — serves http://localhost:8080 and opens a browser.
- Config resolution per value: CLI flag > environment variable > `.env` file > default.
  `serve.py` looks for `.env` beside itself, then in its parent directory. `.env` is
  gitignored; `.env.example` documents the keys.
- Several API keys can share one `.env`; pick one with `--api-key-var NAME`. The Immich URL
  is read from `IMMICH_URL` or `URL_IMMICH`.
- Do not test the UI with `python3 -m http.server` or `file://`: every `/api/*` request
  must go through `serve.py`, which injects `x-api-key` server-side. The key must never
  reach browser code.
- If a `dist/` directory exists next to `serve.py`, it is served instead of the repo root.
  Nothing in this repo generates it.

## Verify changes

- No automated tests. Minimum check is `python3 -m py_compile serve.py` plus a manual
  browser pass against a real Immich instance; most of the logic in `index.html` is only
  exercised that way.
- UI edits need only a browser reload: `serve.py` sends `Cache-Control: no-store` for
  non-`/api/` responses so `index.html` is never cached.

## Immich API quirks used by the app

- Reassign a face: `PUT /api/faces/{targetPersonId}` with body `{"id": faceId}`. The path
  segment is the person, not the face.
- Unassign ("not this person"): `POST /api/people` with `{}` to create an unnamed person,
  then reassign the face to it. Undo reassigns the face back and deletes that person.
- Top suggestion for a face: `GET /api/people?closestAssetId={faceId}&withHidden=true&page=1&size=1`.
- Assets for a person: `POST /api/search/metadata` with `personIds`, paginated. Faces of an
  asset: `GET /api/faces?id={assetId}` (falls back to `?assetId=`).
- The proxy spoofs a desktop-browser `User-Agent` because CDN/WAF-fronted Immich instances
  reject `urllib`'s default. Keep that header when touching `serve.py`.
- Code relies on current response shapes: `faces[].person.id`, `boundingBoxX1..Y2`, and
  paged `assets.items` + `nextPage`.

## State and review loop

- Progress persists in `localStorage`: `facefix_people` for the selected pair, and
  `facefix_{wrongPersonId}_{correctPersonId}` for reviewed assets, stats, and the undo
  stack. Persisted undo entries are replayed against the API, so changing their shape
  breaks existing sessions.
- Undo sets `skipAutoFixOnce` so auto-fix does not immediately redo the undone action;
  preserve that interaction when editing the review flow.
- Reassignment and unassignment are immediate API calls (no confirmation), which is why
  the undo stack is the only rollback path.

## Git

- This repository is public. Never commit personal information: no real names, email
  addresses, Immich URLs or hostnames, API keys/tokens, `.env` contents, or screenshots
  showing identifiable people. Use placeholders (`photos.example.com`, `your-api-key`)
  as in `README.md` and `.env.example`.
- `origin` is a personal fork; `upstream` is `pabera/immich-face-fix`, the target for
  upstream PRs.
