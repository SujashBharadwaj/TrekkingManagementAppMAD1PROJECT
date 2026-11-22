# The public JSON API

Mountains & Maggi has a small REST API: three read-only endpoints that answer in JSON. Anyone can
call them, with no account or token. They're the real examples in the "What is an API?" post on
[Sujash Bharadwaj's portfolio](https://sujash-bharadwaj.vercel.app/), and they show only what the
public trek pages already show.

| Endpoint | What it returns |
| :--- | :--- |
| `GET /api/treks` | Upcoming departures that are open for booking, soonest first, at most 10 |
| `GET /api/treks/<id>` | One departure, as its public trek page shows it |
| `GET /api/treks/<id>/itinerary` | That departure's day-by-day plan, as far as it's published |

The examples below come from a freshly seeded database on 2026-11-22. The seed dates its treks
from the day it runs, so the ids, dates and seat counts differ on another day.

## `GET /api/treks`

Departures that are Open and haven't started, soonest first (and by id on the same day). `treks`
holds at most 10, and `total` says how many match. Three optional filters:

| Parameter | Values |
| :--- | :--- |
| `month` | A year and month, `YYYY-MM`: departures that start in that month. This month or later. |
| `region` | `North`, `East`, `West` or `South` |
| `difficulty` | `Easy`, `Moderate` or `Hard` |

```http
GET /api/treks?month=2027-06 HTTP/1.1
```

```json
{
  "treks": [
    {
      "id": 40,
      "name": "Hampta Pass Trek",
      "region": "North",
      "difficulty": "Moderate",
      "start_date": "2027-06-06",
      "end_date": "2027-06-11",
      "days": 5,
      "price_inr": 8500,
      "seats_left": 20
    },
    {
      "id": 41,
      "name": "Roopkund Trek",
      "region": "North",
      "difficulty": "Hard",
      "start_date": "2027-06-13",
      "end_date": "2027-06-21",
      "days": 8,
      "price_inr": 12500,
      "seats_left": 15
    },
    {
      "id": 42,
      "name": "Kalsubai Peak Trek",
      "region": "West",
      "difficulty": "Easy",
      "start_date": "2027-06-20",
      "end_date": "2027-06-21",
      "days": 1,
      "price_inr": 1800,
      "seats_left": 40
    },
    {
      "id": 43,
      "name": "Dzukou Valley Trek",
      "region": "East",
      "difficulty": "Moderate",
      "start_date": "2027-06-27",
      "end_date": "2027-06-30",
      "days": 3,
      "price_inr": 4800,
      "seats_left": 20
    }
  ],
  "total": 4
}
```

Dates are `YYYY-MM-DD`, `days` is the trek's length, and `price_inr` is the price of one seat in
whole rupees. A trek such as Hampta Pass runs on several dates, and each date is a departure with
its own id.

## `GET /api/treks/<id>`

One departure, with the fields of the list and the rest of what its trek page shows. Any
departure the website shows is here, including ones that are full, running or over. One still
waiting for an admin's approval (Pending) isn't public yet, so it's a 404.

```http
GET /api/treks/1 HTTP/1.1
```

```json
{
  "id": 1,
  "name": "Hampta Pass Trek",
  "location": "Manali, Himachal Pradesh",
  "region": "North",
  "difficulty": "Moderate",
  "start_date": "2026-12-02",
  "end_date": "2026-12-07",
  "days": 5,
  "price_inr": 8500,
  "seats_left": 18,
  "total_seats": 20,
  "status": "Open",
  "best_season": "Summer",
  "route_kms": 26.0,
  "description": "A crossover trek from Manali to Spiti Valley through green meadows and snow-covered passes."
}
```

`status` is `Open`, `Approved`, `In Progress`, `Closed` or `Completed`. `best_season`,
`route_kms` and `description` are `null` when the trek doesn't have them. Seats come and go with
bookings: book two on the website and `seats_left` here drops by two.

## `GET /api/treks/<id>/itinerary`

The days an admin has approved, in order. A departure with none published yet has an empty list.

```http
GET /api/treks/1/itinerary HTTP/1.1
```

```json
{
  "trek_id": 1,
  "days": [
    {"day": 1, "title": "Manali to Jobra", "details": "Drive to Jobra and short acclimatisation walk."},
    {"day": 2, "title": "Jobra to Balu Ka Ghera", "details": "Trek through forests and meadows to riverside campsite."},
    {"day": 3, "title": "Balu Ka Ghera to Shea Goru via Hampta Pass", "details": "Cross the pass at 14,100 ft. Dramatic landscape change."},
    {"day": 4, "title": "Shea Goru to Chatru", "details": "Descend to Chatru on the Spiti side."}
  ]
}
```

(The API indents every level; the days are shown one per line here to save space.)

## Errors

A refusal is one plain sentence in `error`:

```json
{
  "error": "June 2026 has already passed. Try 2027-06."
}
```

| HTTP | When | Example `error` |
| :--- | :--- | :--- |
| 400 | `month` isn't `YYYY-MM` | `"month" must be a year and month written YYYY-MM, with a two-digit month.` |
| 400 | `month` has passed (it names the one you probably meant) | `June 2026 has already passed. Try 2027-06.` |
| 400 | `region` or `difficulty` isn't one of its values (they're case-sensitive) | `"region" must be North, East, West or South.` |
| 400 | A parameter the API doesn't have | `Unknown parameter "sort". The parameters are month, region and difficulty.` |
| 400 | The same parameter twice | `Give "region" only once.` |
| 404 | No such id, an id that isn't a whole number, or a trek still Pending | `No trek with id 999.` |
| 404 | Any other path under `/api` | `Not found. The API has /api/treks, /api/treks/<id> and /api/treks/<id>/itinerary.` |
| 405 | POST, PUT, PATCH or DELETE, with `Allow: GET, HEAD, OPTIONS` | `Method not allowed: the API is read-only, so it answers GET, HEAD and OPTIONS only.` |

## Methods

- **GET** reads, as above.
- **HEAD** gets exactly what GET would (status and headers, including `Content-Length`), without
  the body. RFC 9110 asks every general-purpose server to answer HEAD wherever it answers GET.
- **OPTIONS** gets `204 No Content` with `Allow: GET, HEAD, OPTIONS`,
  `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods: GET, HEAD, OPTIONS` and
  `Access-Control-Allow-Headers: Content-Type`. That's the answer a browser's CORS preflight
  needs, so a cross-site request that sends a `Content-Type` header works too. (A plain `fetch()`
  sends no preflight at all.)
- Anything else gets 405. Under any other path in `/api`, every method gets the 404.

## Headers

Every answer, refusals included, carries:

- `Content-Type: application/json; charset=utf-8`, with non-English text sent as UTF-8 rather than
  `\u` escapes (except the 204, which has no body).
- `Access-Control-Allow-Origin: *`: the data is public and read-only, so a page on any site, or a
  browser's console, may read it.
- `Cache-Control: public, max-age=60`: browsers and proxies may reuse an answer for a minute, so
  seat counts can be up to a minute old.
- `X-Content-Type-Options: nosniff`, so a browser never treats an answer as a page.

The API never reads the login session and never sets a cookie: a signed-in admin gets exactly
what everyone gets.

## Try it

Start the app (see the README), then:

```bash
curl -i "http://127.0.0.1:5000/api/treks?region=West&difficulty=Easy"
curl "http://127.0.0.1:5000/api/treks/1"
curl "http://127.0.0.1:5000/api/treks/1/itinerary"
curl -I "http://127.0.0.1:5000/api/treks/1"            # HEAD: the headers only
curl -i -X OPTIONS "http://127.0.0.1:5000/api/treks"   # what a browser's preflight gets
```

Or, from a browser's console on any page:

```js
const response = await fetch('http://127.0.0.1:5000/api/treks?month=2027-06');
console.log(response.status, await response.json());
```

On the live app, put its address in place of `http://127.0.0.1:5000`.

## How it relates to the MCP tools

The app also has an MCP server ([MCP.md](MCP.md)) that lets an AI agent find, book and cancel
treks. The two share their code where they overlap:

- **One search.** `GET /api/treks` and the MCP tool `list_treks` both call `search()` in
  `services/catalogue.py`: the same departures, in the same order, with the same fields
  (`summary()`), and the same sentence for the same mistake. A test checks that both return the
  same for the same filters.
- **Different readers, different doors.** The API is for people and programs: public, anonymous,
  cacheable and read-only. MCP is for an AI agent: behind a token, with a fixed set of tools it can
  discover (names, schemas and descriptions), including two that write (`book_trek` and
  `cancel_booking`) for the visit's own throwaway trekker, and with limits per visit.
- **What each shows.** The API's single-trek endpoints add `location`, `description` and the
  itinerary, because the trek page shows them to everyone. The MCP tools leave free text out on
  purpose: it goes to a model, and text that other people can write is where prompt injection
  hides.
- **Filters.** The API takes `month`, `region` and `difficulty`. The tool also takes
  `max_price_inr` and `min_seats`.

## Decisions and trade-offs

- **No token and no rate limit.** Everything here is already public, each answer is at most 10
  small rows, and answers may be cached for a minute. Cost: anyone can poll it, and heavy use
  would slow Render's free tier; a per-IP limit at the edge would be the next step.
- **Strict parameters.** An unknown or repeated parameter is a 400, not ignored, so a typo such
  as `regoin=North` doesn't quietly return every trek.
- **Pending treks are hidden,** because they're waiting for an admin's approval. The website's own
  trek page still opens one by its URL; the API doesn't.
- **GET and HEAD, plus OPTIONS for preflights; nothing that writes.** HEAD follows RFC 9110, and
  OPTIONS lets browsers on other sites send a `Content-Type` header. Cost: none worth noting,
  since every answer is public anyway; writes stay with the website's forms and the MCP tools.
- **Indented JSON,** because people read these answers in a terminal or a browser tab as often as
  programs do. It costs a few hundred bytes.

## Files

| File | What's in it |
| :--- | :--- |
| `routes/api_routes.py` | The three endpoints, their refusals and headers |
| `services/catalogue.py` | The shared search, the fields each endpoint shows, and the text cleaning |
| `tests/test_api.py` | Every endpoint and refusal, the headers, and the check against `list_treks` |
