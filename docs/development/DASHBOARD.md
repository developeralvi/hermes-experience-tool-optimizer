# EBTTO Dashboard

`hermes-ebtto` ships a **read-only, loopback-only** web dashboard that makes
the recorded tool history and learned memory understandable without writing
SQL by hand.

## Launch

```bash
# from an installed package (any Python with hermes-experience-tool-optimizer installed)
python -m hermes_ebtto.dashboard

# options
python -m hermes_ebtto.dashboard --port 8797     # fixed port (default: first free from 8797)
python -m hermes_ebtto.dashboard --no-browser    # print URL, don't open a browser
python -m hermes_ebtto.dashboard --db /path/to/ebtto.db   # or a directory
```

The command prints the exact URL (default `http://127.0.0.1:8797/`), opens
your default browser unless `--no-browser`, and stops with **Ctrl+C**.
Port collisions are handled by trying the next free port (up to 20).

The dashboard is a standalone process: it never starts with Hermes and a
normal Hermes run is unaffected whether it is running or not.

## Database discovery

The dashboard opens exactly the database the plugin writes to:
`storage.get_storage_path()` → `$HERMES_HOME/.hermes-ebtto/ebtto.db`
(falling back to `~/.hermes-ebtto/ebtto.db`). Override with `--db`.

## Security boundary

- Binds `127.0.0.1` only — never `0.0.0.0`, never LAN/public.
- Opens SQLite with `mode=ro` + `PRAGMA query_only` — no insert/update/delete,
  no migrations, no reset/prune/replay endpoints exist.
- No mutating API endpoint at all (`/api/reset`, `/api/mode`, `/api/sql`, …
  return 404 — verified by test).
- Static assets ship inside the wheel; no CDN, no external requests.
- All user values are bound SQL parameters; page sizes are clamped
  (max 200); table/column names are never taken from a request.
- The frontend renders every server string via `textContent` — never
  `innerHTML` — so task text, tool names and error messages cannot inject
  markup (verified by test with an XSS payload).
- If the DB is missing or schema-incompatible you get an explicit error
  state — the dashboard never creates a replacement database and never
  shows demo data.

## Pages

| Page | What it shows |
|---|---|
| **Overview** | Tool-call counts, success/failure rate (with denominator + window), tasks, patterns, strategies (total/qualified), guidance-delivered counts (when schema v4 telemetry exists), 14-day success/failure trend, most-used tools, DB integrity. Time filter: 1h / 24h / 7d / 30d / all. |
| **Activity / Tool Calls** | Paginated table: time, tool, status, duration, attempt, error class, task. Filters: window, status, tool, free-text search over sanitized fields. Click a row for sanitized args, sanitized error message, sibling attempts, outcomes, errors. |
| **Failures** | Failure categories, failing tools, failed→recovered pairs (proven by session + time ordering, never claimed to be strategy-caused), paginated failure list with sanitized messages. |
| **Trajectories** | Task list → per-task timeline: every persisted stage (tool_call / outcome / error) in order, with missing stages stated explicitly. |
| **Memory** | Patterns + strategies with confidence, evidence/success/failure/context counts, qualification status, family, timestamps. Detail view shows the sequence, a real evidence sample (outcome rows for the strategy's family), and retrieval events that selected it. Displays the lifecycle explicitly: RAW OBSERVATION → … → BEHAVIORAL EFFECT MEASURED. |
| **Guidance** | Retrieval/guidance audit: one row per hook retrieval with reason code (`guidance_returned` / `no_candidate` / `candidate_below_threshold`), candidate/qualified counts, selected strategy. States plainly that these events do **not** prove model delivery or behavioral effect. On a pre-v4 database the page says the telemetry is unavailable instead of showing nothing. |
| **System** | Schema version, DB path, integrity check, last event timestamp, row counts, what telemetry is missing. Read-only, no secrets. |

Refresh: 5s default (adjustable 0/5/15/60s), pauses when the tab is
hidden, refreshes on focus, shows last-refresh time + connection dot,
manual Refresh button, honest empty/error states.

## Honesty rules baked into the UI

- Success/failure is computed from the `outcomes` table (session-prefix
  linkage — the two hook writers assign independent task ids); the UI never
  fabricates a percentage when the denominator is zero.
- **BEHAVIORAL IMPROVEMENT NOT YET PROVEN** is displayed on the Guidance
  page until a controlled benchmark exists.
- "Not recorded" / "Not verified" is shown wherever the underlying
  telemetry does not exist.

## Telemetry note (schema v4)

`migrations/4.sql` adds `retrieval_guidance_events` so the plugin records
what each `pre_llm_call` / `pre_tool_call` retrieval actually did
(reason_code, candidate/qualified counts, selected strategy,
guidance_returned). Pre-v4 databases remain fully supported — the dashboard
reports the telemetry as unavailable rather than inventing rows. The plugin
write path is fail-open: a telemetry failure never interrupts a Hermes turn.

## Troubleshooting

- **"EBTTO database not found"** — run Hermes with the plugin enabled at
  least once, or pass `--db <path>`.
- **"Database schema incompatible"** — the file is not an EBTTO database.
- **Port in use** — the launcher auto-increments; or pass `--port`.
- **DB busy warnings** — the live plugin writes in WAL mode; dashboard
  reads use `busy_timeout` and never block the agent.

## Development

```bash
python -m pytest tests              # 43 tests incl. 27 dashboard tests
python -m hermes_ebtto.dashboard    # run from source checkout
```

Dashboard tests cover: count reconciliation, filters, date boundaries,
pagination clamping, empty results, invalid input, read-only enforcement
(write attempts raise), missing/bad-schema DB handling, no auto-DB-creation,
concurrent writer+reader, loopback-only binding, no mutation endpoints,
no POST, no external resources, XSS inertness, and CLI entrypoint.
