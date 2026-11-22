# The MCP server: a decision record

Mountains & Maggi has its own [MCP](https://modelcontextprotocol.io/specification/2026-07-28)
server, so an AI agent on [Sujash Bharadwaj's portfolio](https://sujash-bharadwaj.vercel.app/)
can find treks, check seats, book and cancel on this app while a visitor watches. The bookings
are real: afterwards the app's public trek page shows fewer seats.

This page records what was built, the decisions behind it and what each one costs, the risks of
putting a public demo in front of an AI agent and how each is handled, and how to run it.

## How it fits together

```text
 Visitor's browser          Portfolio (Vercel)                  This app (Render: Flask + SQLite)
 -----------------          ------------------                  ---------------------------------
 types a task ---------->   agent loop: the model
                            picks one tool at a time
                            POST /mcp ------------------------> routes/mcp_routes.py    token, Origin, 8 KB
                              Authorization: Bearer <token>     mcp_server/protocol.py  JSON-RPC and MCP
                              MM-Visit-Id: <uuid v4>            mcp_server/tools.py     the five tools
                                                                mcp_server/visits.py    walkers, limits, tidying
                                                                services/bookings.py    rules shared with the website
                                                                SQLite                  treks, bookings, walkers
 watches each step <------  streams the steps
 "See it in the app" -------------------------------------->  GET /trek/<id>  (the public trek page)

 The browser agent (below): headless Chrome on the portfolio's server
                            POST /demo/walker {visit_id} -----> routes/demo_routes.py   the same door; a password
                            Chrome: /login, /trek/<id>,         the website's own pages, as the visit's walker
                              POST /book/<id>, /booking/cancel
 watches its screen <-----  streams the frames
```

The portfolio's server is the only intended client. It holds the token, so the token never
reaches a browser.

## The five tools

Every tool acts as the visit's own throwaway trekker (a "walker", below). Dates are
`YYYY-MM-DD`, money is whole rupees, and names are cut at 80 characters.

| Tool | What it does | Arguments | Returns (`structuredContent`) | Hints |
| :--- | :--- | :--- | :--- | :--- |
| `list_treks` | Open departures that haven't started, soonest first, at most 10. A past month is refused with the month it probably meant ("June 2026 has already passed. Try 2027-06."). | All optional: `month` `YYYY-MM`, `region` (North, East, West, South), `difficulty` (Easy, Moderate, Hard), `max_price_inr`, `min_seats` 1 to 4 | `{treks: [{id, name, region, difficulty, start_date, end_date, days, price_inr, seats_left}], total}` | read-only |
| `check_availability` | Seats left, whether this visit can book it (and why not), and a price quote | `trek_id`; `seats` 1 to 4, default 1; `insurance`, default false | `{trek_id, name, start_date, seats_left, can_book, reason, quote: {base_inr, insurance_inr, total_inr}}`, with `reason` null when `can_book` | read-only |
| `book_trek` | Books seats with the website's own rules | `trek_id`, `seats` 1 to 4; `insurance`, default false | `{booking_id, trek_id, name, start_date, seats, insurance, total_inr, status: "Booked", seats_left_after}` | not idempotent |
| `cancel_booking` | Cancels one of this visit's bookings and gives its seats back. Cancelling it again changes nothing. | `booking_id` | `{booking_id, trek_id, name, status: "Cancelled", seats_returned, seats_left_after}` | destructive, idempotent |
| `my_bookings` | This visit's bookings, active and cancelled, oldest first | none | `{bookings: [{booking_id, trek_id, name, start_date, seats, total_inr, status}]}` | read-only |

Every input schema has `additionalProperties: false`, and every tool has a title, a description
and an output schema. The read tools work without a visit id; the write tools refuse without one.

## What a client sends and gets back

One JSON-RPC 2.0 request per `POST /mcp`, in MCP 2026-07-28's shape:

```http
POST /mcp HTTP/1.1
Content-Type: application/json
Accept: application/json, text/event-stream
Authorization: Bearer <MCP_TOKEN>
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: book_trek
MM-Visit-Id: 3b8f2c1a-9d4e-4f6a-8b2c-1d3e5f7a9b0c

{"jsonrpc": "2.0", "id": 7, "method": "tools/call",
 "params": {"name": "book_trek", "arguments": {"trek_id": 40, "seats": 2},
            "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                      "io.modelcontextprotocol/clientCapabilities": {}}}}
```

- `Mcp-Method` goes on every request, and `Mcp-Name` (the tool's name) on `tools/call`. Both must
  match the body, and `_meta`'s protocol version must match the header.
- The methods are `server/discover`, `tools/list`, `tools/call` and `ping`.
- Every reply is a single `application/json` body. Nothing is streamed.
- Every result has `resultType: "complete"` and the server's name and version in
  `_meta["io.modelcontextprotocol/serverInfo"]`. `server/discover` and `tools/list` also carry
  `ttlMs` (an hour) and `cacheScope: "public"`.
- A tool's result has `content` (one text block holding the same JSON), `structuredContent` and
  `isError: false`. A refusal has `isError: true` and one plain sentence in `content`, such as
  "Only 1 seat is left on that date.", and no `structuredContent`.

**Older clients.** MCP Inspector's default mode and other 2025-11-25 or 2025-06-18 clients open
with `initialize`. The server answers it without a session id, then serves their requests by the
version in their `MCP-Protocol-Version` header alone, with no `_meta` and no `Mcp-*` headers
needed. Their results leave out the fields 2026-07-28 added. `ping`, which 2026-07-28 removed, is
still answered.

### Status codes

| HTTP | JSON-RPC code | When |
| :--- | :--- | :--- |
| 200 | none | A result, including a tool's refusal (`isError: true`) |
| 200 | -32602 | An unknown tool, a malformed `tools/call`, or a cursor (everything fits on one page) |
| 202 | none, empty body | A notification, such as an older client's `notifications/initialized` |
| 400 | -32700 | The body isn't JSON (or repeats a key, or uses NaN or Infinity) |
| 400 | -32600 | Not one JSON-RPC request: a batch, no `"jsonrpc": "2.0"`, no `method`, an `id` that is null or a boolean |
| 400 | -32602 | A 2026-07-28 request whose `_meta` lacks the protocol version or the client capabilities |
| 400 | -32020 | A header missing or not matching the body (`MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`) |
| 400 | -32022 | An unsupported protocol version, with `data: {supported, requested}` |
| 401 | -31401 | No bearer token, or the wrong one |
| 403 | -31403 | An `Origin` header that isn't on the allowlist |
| 404 | none | The endpoint is off (no `MCP_TOKEN`): the app's ordinary 404 page |
| 404 | -32601 | An unknown method (an older client gets it with 200) |
| 405 | -31405 | Any HTTP method but POST |
| 413 | -31413 | A body over 8 KB |
| 500 | -32603 | A bug or a database failure |

When the request's id can't be read, the error leaves `id` out, as MCP's schema allows. The 31xxx
codes are this app's own, outside JSON-RPC's reserved range, as MCP asks for application errors.

## The browser agent's sign-in: `POST /demo/walker`

The portfolio's live demo now also drives a real, headless Chrome through this website, and a
visitor watches its screen. That agent books the way a person does: it signs in on `/login`,
opens a trek page, presses "Book Now" and fills in the booking form. So it needs a trekker it can
sign in as, and this endpoint gives it one:

```http
POST /demo/walker HTTP/1.1
Content-Type: application/json
Authorization: Bearer <MCP_TOKEN>

{"visit_id": "3b8f2c1a-9d4e-4f6a-8b2c-1d3e5f7a9b0c"}
```

```json
{"username": "walker-3b8f2c1a", "password": "<22 random characters>"}
```

- **The same walker as the MCP agent's.** The visit id picks the visit's walker (the table, the
  naming and the hour's life are those of decision 4 below), made now if the visit has none. A
  booking made over MCP and one made in the browser land in the same dashboard.
- **A password per call, which dies with the walker.** Each call sets a new random password
  (`secrets.token_urlsafe(16)`, 128 bits, 22 characters) and returns it once; the last one stops
  working. It's hashed like every password in the app (Werkzeug's `pbkdf2:sha256`), with 1,000
  rounds as for every walker, because stretching only protects guessable passwords. After an
  hour, housekeeping deletes the walker with its bookings, and the password goes with it.
- **Kept private by the token.** The door is `/mcp`'s (`routes/door.py`): a 404 without
  `MCP_TOKEN`, POST only, the `Origin` allowlist, the bearer token in constant time, and a body
  of 1 KB at most. Only the portfolio's server holds the token, so only it can get a password,
  and the reply is `Cache-Control: no-store`. It never reads the login session or sets a cookie.
- **Tidying up and a cap.** Each call runs the same housekeeping as an MCP call first. At most 30
  new walkers are made a minute across every visit, over MCP and this endpoint together, so the
  endpoint can't fill the database; a visit that already has a walker can still get a new
  password.
- **The demo's limits on the website too.** A walker booking through the website's form gets
  the MCP agent's limits (4 seats a booking, 3 active bookings), with plain sentences such as
  "You can book at most 4 seats at a time." Real accounts (user1 to user5) keep the website's
  rules. Both live in `services/bookings.py` (`limits_for()`).

| HTTP | Body | When |
| :--- | :--- | :--- |
| 200 | `{username, password}` | The visit's walker, with its new password |
| 400 | `{error}` | The body isn't exactly `{"visit_id": "<uuid v4>"}` |
| 401 | `{error}` | No bearer token, or the wrong one (with `WWW-Authenticate: Bearer`) |
| 403 | `{error}` | An `Origin` header that isn't on the allowlist |
| 404 | the app's 404 page | The endpoint is off (no `MCP_TOKEN`) |
| 405 | `{error}` | Any HTTP method but POST (with `Allow: POST`) |
| 413 | `{error}` | A body over 1 KB |
| 429 | `{error}` | 30 new walkers this minute already (with `Retry-After: 60`) |
| 503 | `{error}` | The walker couldn't be set up (housekeeping removed it a moment ago) |
| 500 | `{error}` | A bug or a database failure |

Signing out a stale session: SQLite gives a deleted user's id to the next new account, so a
browser still signed in as a walker that housekeeping removed could have carried on as the next
visit's walker. The login check now also compares the session's username with the account's
(usernames never change), and signs such a session out.

## Decisions and trade-offs

**1. MCP written by hand inside Flask, not with the official Python SDK.**
- Context: the app is plain Flask on Render's free tier, run by gunicorn.
- Why: the SDK's HTTP server runs only under ASGI, which would mean uvicorn, about ten more
  packages and a new start command on Render. MCP 2026-07-28 (stateless, POST only, JSON replies)
  is small enough to write with the standard library: about 1,000 lines with comments, a third of
  them the tools' schemas.
- Cost: the protocol is checked by hand, with the unit tests in `tests/` and MCP Inspector in
  both eras, and a future revision of the spec has to be followed here by hand.

**2. One JSON reply per request, no streaming.** Every tool finishes in milliseconds, so there's
nothing to stream. Cost: no progress notifications, which nothing here needs.

**3. A visit header instead of sessions.** 2026-07-28 removed sessions: state that spans calls is
named on each request. Here that's `MM-Visit-Id`, a UUID v4 the portfolio makes for each visit.
Cost: the portfolio must send it on every call, and a lost id means a fresh, empty trekker.

**4. A throwaway trekker per visit.** Rather than one shared demo account, each visit's first
booking makes a trekker called `walker-<first 8 hex digits>`, with a `.invalid` email (a domain
reserved never to exist) and a password nobody knows (until `/demo/walker`, above, gives the
browser agent one). So visitors never see each other's bookings,
and the agent never touches a real user's. Walkers are listed in their own table
(`mcp_walkers`), so tidying up can never delete a real account that happens to be called
walker-something. Cost: extra rows to clean up, hence the next decision.

**5. Tidying up on every call, not on a schedule.** Render's free tier has no cron or background
worker, and its sleep wipes the database anyway. Each MCP call first deletes walkers older than an
hour, with their bookings, giving back the seats of any still booked. Cost: two small reads per
call, and a few writes when something is due.

**6. The booking rules moved into a service.** `services/bookings.py` holds them once, for the
website and the tools alike, so the two can't drift apart: booking, cancelling, moving a booking
to another date and toggling its insurance. Moving them fixed old bugs: a trek that had already
started could still be booked (or a booking moved onto or off it), and two requests at the same
moment could both take the last seats.

**7. Seats are taken with a conditional UPDATE.**
`UPDATE treks SET available_slots = available_slots - n WHERE id = ? AND status = 'Open' AND start_date > today AND available_slots >= n`,
then the row count says whether it worked. SQLite has no `SELECT ... FOR UPDATE`, but one
statement is atomic, and from that UPDATE until the commit the request holds SQLite's write lock,
so the "already booked" and "3 active bookings" checks made inside it can't race either. A test
fires six bookings at once at two seats and expects exactly two to succeed. Cost: the second half
leans on SQLite's single writer. On a database with row locks, such as Postgres, those checks
would need `SELECT ... FOR UPDATE` or a unique index.

**8. Limits counted in SQLite.** One row per tool call, kept for an hour, and the count and the
insert are a single `INSERT ... SELECT ... WHERE count < limit`, so two calls can't both take the
last place. Why: no Redis or other paid service. Cost: the counts vanish whenever Render's sleep
wipes the database, which is why the per-IP limits live on the portfolio's side.

**9. A small JSON Schema checker instead of a package.** It checks exactly the keywords the five
schemas use and answers in plain sentences a model can act on (`"seats" must be from 1 to 4.`).
Cost: a schema that used another keyword wouldn't be checked until the checker learned it, so the
tests check every tool's output against its own schema too.

**10. A bearer token, not OAuth.** There is one client, the portfolio's server, so a shared secret
is enough. MCP's OAuth flow is for many clients acting for many users. Cost: changing the token
means changing it on Render and on Vercel. Without `MCP_TOKEN` the endpoint is a plain 404, so it
stays off until it's set.

**11. Departures across the next 12 months.** The seed adds Open departures of the existing
routes in each of the next 12 calendar months (ids 17 on), roughly in each route's season, so
"a June trek" always exists. The home page now shows each trek once, at its soonest departure,
and the trek page lists the others under "Other Available Dates". Treks 1 to 16 and their
bookings are unchanged.

**12. Older clients answered too.** A stateless answer to `initialize` lets MCP Inspector's
default mode, and other 2025-11-25 clients, work without sessions. Cost: two eras to keep right,
and the tests cover both.

## Threat model

| Risk | How it's handled |
| :--- | :--- |
| Someone finds the URL and calls it | A bearer token, compared in constant time over SHA-256 digests; the endpoint is off (404) without `MCP_TOKEN`; the token lives only in Render's and Vercel's settings. |
| A web page in a visitor's browser calls it (cross-site requests, DNS rebinding) | A request with an `Origin` header that isn't on `MCP_ALLOWED_ORIGINS` (empty by default) gets 403. There are no CORS headers, and the endpoint never reads cookies. |
| The agent acts as a signed-in user or an admin | `/mcp` never reads the Flask session or uses the login decorators, the five tools are fixed in code, and every write is tied to the visit's walker. A test signs in as the admin first and checks the agent still acts as the walker. |
| Prompt injection through the data | Trek names are the only text that other people can write (the admin login is published). They're cut at 80 characters, with control and format characters (such as right-to-left overrides) removed. A name that gives orders can change what the agent says, never what it can do. Descriptions and other free text are never returned. |
| One visitor sees or cancels another's bookings | Every lookup is scoped to the visit's walker. Cancelling someone else's booking gets "You have no booking with that number.", the same as a booking that doesn't exist, so it reveals nothing. |
| Two bookings sell the same seat | The conditional UPDATE, tested with six bookings at once. |
| Personal data leaks | Results carry only the fields in the table above: no descriptions, phone numbers, emails, medical notes or user ids. A test looks for them. |
| Flooding | 12 tool calls per visit per hour, 60 a minute in all, 30 new walkers a minute in all, 3 active bookings per visit and 4 seats per booking (over MCP and on the website alike), and 8 KB per body (1 KB for `/demo/walker`). The portfolio adds per-IP limits and a Vercel Firewall rule. |
| Hostile JSON | Bodies over 8 KB are refused before they're read; NaN, Infinity, repeated keys, deep nesting and batches are refused; every argument is checked against its schema before anything runs. |
| Signing in as a walker | Until `/demo/walker` is called, its password hash is of 32 random bytes that nobody keeps. That endpoint needs the token, and each call replaces the password with 128 new random bits, so only the newest run's password works, and only until housekeeping removes the walker. A session left over from a removed walker is signed out, even if its id goes to a new account. |
| A signed-in walker leaves things behind | Housekeeping deletes a walker's bookings, staff application, reviews and photo records with it, so no admin page meets a row whose user is gone. The portfolio's browser also only lets its agent reach the sign-in, trek, dashboard, booking and cancelling pages. |
| Demo data piling up | Walkers go after an hour, and Render's sleep wipes the database. |
| Guessing a visit id | A UUID v4 has 122 random bits, and only well-formed v4 ids are accepted. |

What this doesn't cover, on purpose:
- The token is one shared key. Whoever holds it can call the tools, though only as walkers.
- The app's own security stays as it is (the published demo logins, the fallback `SECRET_KEY`):
  it's a student project with made-up data.
- The caller picks the visit id, so the per-visit limits slow an agent down but don't stop a
  determined caller with the token. That's the portfolio's job, with its per-IP limits.

## Limits

| Limit | Value | Where |
| :--- | :--- | :--- |
| Tool calls per visit | 12 an hour | `CALLS_PER_VISIT_PER_HOUR` in `mcp_server/visits.py` |
| Tool calls in all | 60 a minute | `CALLS_PER_MINUTE` in `mcp_server/visits.py` |
| A walker's life | 60 minutes | `WALKER_LIFETIME` in `mcp_server/visits.py` |
| New walkers in all | 30 a minute | `NEW_WALKERS_PER_MINUTE` in `mcp_server/visits.py` |
| Seats per booking (a walker's, over MCP or on the website) | 1 to 4 | `WALKER_MAX_SEATS` in `services/bookings.py` |
| Active bookings per visit (likewise) | 3 | `WALKER_MAX_ACTIVE` in `services/bookings.py` |
| Treks per `list_treks` | 10 | `LIST_LIMIT` in `mcp_server/tools.py` |
| Request body | 8 KB | `MAX_BODY_BYTES` in `routes/mcp_routes.py` |
| `/demo/walker` body | 1 KB | `MAX_BODY_BYTES` in `routes/demo_routes.py` |

Over a limit, the tool returns `isError` with a plain sentence.

## Running it locally

Set `MCP_TOKEN` to any value for a local run, and start the app:

```powershell
# Windows, PowerShell
$env:MCP_TOKEN = "dev-token"; venv\Scripts\python.exe -m flask --app app run --port 5000
```

```bash
# Windows, Git Bash
MCP_TOKEN=dev-token venv/Scripts/python.exe -m flask --app app run --port 5000
# macOS, zsh
MCP_TOKEN=dev-token venv/bin/python -m flask --app app run --port 5000
```

`python app.py` works too (port 4200, debug mode). The seed runs only on an empty database, so
delete an old `trekking.db` to get the 12 months of departures. The MCP tables are created on
their own. Add `DATABASE_URL=sqlite:///C:/path/to/scratch.db` to try it without touching
`trekking.db`.

A real token for Render: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

### Tests

```powershell
venv\Scripts\python.exe -m unittest discover -s tests -v   # Windows, PowerShell
```

```bash
venv/Scripts/python.exe -m unittest discover -s tests -v   # Windows, Git Bash
venv/bin/python -m unittest discover -s tests -v           # macOS, zsh
```

They use the standard library's `unittest` and Flask's test client on a throwaway database.

### MCP Inspector

[MCP Inspector](https://modelcontextprotocol.io/docs/2026-07-28/tools/inspector/cli.md) runs
with `npx`, so nothing is installed. Its default mode is the older handshake; `--protocol-era
modern` pins 2026-07-28 and `auto` tries `server/discover` first.

```bash
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:5000/mcp --transport http \
  --method tools/list --header "Authorization: Bearer dev-token"

npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:5000/mcp --transport http \
  --protocol-era modern --method tools/call --tool-name book_trek \
  --tool-arg trek_id=40 --tool-arg seats=2 \
  --header "Authorization: Bearer dev-token" \
  --header "MM-Visit-Id: 3b8f2c1a-9d4e-4f6a-8b2c-1d3e5f7a9b0c"
```

Then open `http://127.0.0.1:5000/trek/40`: "Slots Available" has dropped by two.

### curl

```bash
curl -s http://127.0.0.1:5000/mcp \
  -H "Authorization: Bearer dev-token" -H "Content-Type: application/json" \
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/call" -H "Mcp-Name: list_treks" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_treks","arguments":{"month":"2027-06"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
```

## Environment variables

| Variable | Default | What it does |
| :--- | :--- | :--- |
| `MCP_TOKEN` | unset | Turns `/mcp` and `/demo/walker` on, and is the bearer token they require. Unset, both are a 404. |
| `MCP_ALLOWED_ORIGINS` | empty | Comma-separated browser origins allowed to call `/mcp`, such as `https://example.com`. Empty refuses every request that has an `Origin` header; server-to-server calls send none. |
| `DATABASE_URL` | `sqlite:///trekking.db` beside `app.py` | Where the database lives. The tests point it at a temporary file. |

`GET /healthz` answers `{"ok": true}` with no cookie and no database work, so the portfolio can
wake the app on Render before a run.

## Files

| File | What's in it |
| :--- | :--- |
| `routes/mcp_routes.py` | The door: on or off, POST only, Origin, token, body size |
| `routes/door.py` | Those checks, shared with `/demo/walker` |
| `routes/demo_routes.py` | `POST /demo/walker`: the browser agent's sign-in details |
| `mcp_server/protocol.py` | JSON-RPC 2.0 and MCP: versions, headers, `_meta`, the methods |
| `mcp_server/tools.py` | The five tools, their schemas and what they return |
| `mcp_server/visits.py` | Walkers, tidying up, and the call limits |
| `mcp_server/schema.py` | The small JSON Schema checker |
| `services/bookings.py` | The booking rules, shared with the website |
| `services/catalogue.py` | `list_treks`'s search and fields, shared with the public JSON API ([API.md](API.md)) |
| `models.py` | Two new tables at the end: `mcp_walkers` and `mcp_tool_calls` |
| `tests/` | `test_mcp.py`, `test_demo_walker.py`, `test_api.py`, `test_website.py`, `test_schema.py`, and `support.py` for the throwaway database |
