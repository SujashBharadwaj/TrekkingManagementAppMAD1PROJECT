# Mountains & Maggi: Trekking Management Application

A web-based platform for adventure organizations to manage treks, staff assignments, bookings, expenses, and trekker history. Built with Flask, Jinja2, Bootstrap 5, and SQLite. It also has an [MCP server](#mcp-server-for-ai-agents), so an AI agent can find, book and cancel treks.

## Project Setup & Running

### 1. Prerequisites
Ensure you have Python 3.9+ installed (Flask 3.1 needs it).

### 2. Project Setup
From the root folder, create a virtual environment, activate it, and install the required packages:

```bash
# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install the required packages
pip install -r requirements.txt
```

### 3. Run the Application
Start the Flask development server:
```bash
python app.py
```
This will automatically:
- Create the SQLite database (`trekking.db`) if it doesn't exist.
- Seed the database with mock data including default admin, staff, and user accounts.
- Start the server at `http://127.0.0.1:4200`.

**Default Credentials:**
* **Admin**: `admin` | **Password**: `admin123`
* **Staff**: `staff1` or `staff2` | **Password**: `staff123`
* **Trekker**: `user1` through `user5` | **Password**: `user123`

The seed also adds departures of the same routes in each of the next 12 months, so every month has treks to book. The home page shows each trek once, at its soonest departure, and the trek page lists the other dates.

### 4. Run the Tests
From the root folder, with the virtual environment's Python:
```bash
python -m unittest discover -s tests -v
```
The tests use a throwaway database, so they never touch `trekking.db`.

---

## MCP Server for AI Agents

`POST /mcp` is a [Model Context Protocol](https://modelcontextprotocol.io/specification/2026-07-28) server (revision 2026-07-28, and older clients that start with `initialize`). It lets an AI agent, such as the live demo on [Sujash Bharadwaj's portfolio](https://sujash-bharadwaj.vercel.app/), use five tools on the real app:

| Tool | What it does |
| :--- | :--- |
| `list_treks` | Open departures that haven't started, soonest first, filtered by month, region, difficulty, price or free seats |
| `check_availability` | Seats left on one departure, whether it can be booked, and a price quote |
| `book_trek` | Books 1 to 4 seats with the website's own rules |
| `cancel_booking` | Cancels one of the visit's bookings and gives the seats back |
| `my_bookings` | The visit's bookings |

- **Off by default.** The endpoint answers 404 until `MCP_TOKEN` is set, and then needs `Authorization: Bearer <MCP_TOKEN>`. Requests from browser origins are refused unless listed in `MCP_ALLOWED_ORIGINS`.
- **One throwaway trekker per visit.** The `MM-Visit-Id` header (a UUID v4) picks a demo trekker that nobody can log in as, and it's deleted with its bookings after an hour.
- **A browser agent too.** `POST /demo/walker` with `{"visit_id": "<uuid v4>"}` (same token and door) returns that visit's trekker with a fresh random password, so the portfolio's headless Chrome can sign in on `/login` and book through the website's own forms like a person. The password changes on every call and goes with the trekker after the hour.
- **Limits.** 12 tool calls per visit per hour, 60 a minute in all, 30 new demo trekkers a minute, 3 active bookings and 4 seats a booking for a demo trekker (over MCP and on the website alike), and 8 KB per request.
- `GET /healthz` answers `{"ok": true}`, for waking the app up.

Run it locally with a token of your choice:
```bash
MCP_TOKEN=dev-token python -m flask --app app run --port 5000
```
On Windows PowerShell: `$env:MCP_TOKEN = "dev-token"; python -m flask --app app run --port 5000`.

[docs/MCP.md](docs/MCP.md) has the protocol details, the decisions and their trade-offs, the threat model, and how to check it with MCP Inspector.

---

## Public JSON API

`GET /api/treks` (filtered by `month`, `region` or `difficulty`), `GET /api/treks/<id>` and `GET /api/treks/<id>/itinerary` answer in JSON for anyone, with no token: read-only, only what the public trek pages show, open to any site (`Access-Control-Allow-Origin: *`) and cacheable for a minute. The list is the MCP `list_treks` tool's own search. [docs/API.md](docs/API.md) has the endpoints, examples and errors.

---

## Architecture

The application follows the **Flask Application Factory** pattern and **Flask Blueprints** for modularity:

```text
MAD - 1 Project/
│
├── app.py                  # Application factory (create_app), blueprint registration, seed data
├── models.py               # SQLAlchemy models (User, StaffProfile, Trek, Booking, Review, TrekPhoto, etc.)
├── config.py               # Central configuration (Secret Key, DB URI, Upload Folder)
│
├── routes/                 # Flask Blueprints (Modular route handlers)
│   ├── __init__.py         # Exports all blueprints
│   ├── utils.py            # Shared decorators (login_required, role_required), validation helpers
│   ├── auth_routes.py      # Authentication (Login, Register, Logout)
│   ├── admin_routes.py     # Core Admin CRUD (Treks, Staff, Users, Bookings, Photos)
│   ├── admin_finance_routes.py # Financial P&L breakdown and Payout logic
│   ├── admin_ops_routes.py # Operations (Occupancy, Trek Cloning, Announcements)
│   ├── staff_routes.py     # Staff Workspace & Trek editing
│   ├── staff_ops_routes.py # Staff operations (Checklists, Gear checks, Debriefs, Availability)
│   ├── trekker_routes.py   # Trekker Dashboard, Booking, Reviews, Staff Applications
│   ├── main_routes.py      # Public homepage & Trek detail pages
│   ├── mcp_routes.py       # POST /mcp for AI agents: token, Origin and size checks
│   ├── demo_routes.py      # POST /demo/walker: sign-in details for the browser agent
│   ├── door.py             # The token, Origin and size checks both share
│   └── api_routes.py       # GET /api/treks...: the public, read-only JSON API
│
├── services/
│   ├── bookings.py         # Booking, cancelling, date-change and insurance rules, shared with the MCP tools
│   └── catalogue.py        # The trek search and public fields, shared by the JSON API and the MCP tools
│
├── mcp_server/             # The MCP server: protocol, the five tools, demo trekkers, schema checks
├── tests/                  # unittest suite (MCP endpoint, JSON API, website, schema checker)
├── docs/MCP.md             # The MCP server's design, decisions and threat model
├── docs/API.md             # The public JSON API: endpoints, examples, errors
│
├── static/
│   ├── css/style.css       # Global stylesheet
│   └── uploads/photos/     # Trek image upload storage
│
└── templates/              # Jinja2 HTML templates
    ├── base.html           # Master layout template (Navbar, Alerts, Back Button, Footer)
    ├── index.html          # Public Homepage with Trek search & filters
    ├── trek_detail.html    # Detailed trek view & booking modal
    ├── login.html          # Login view
    ├── register.html       # Register view
    ├── admin/              # Admin Panel templates (Dashboard, Treks, Financials, Occupancy, etc.)
    ├── staff/              # Staff Panel templates (Workspace, Checklists, Debriefs, Local Connects, etc.)
    └── user/               # Trekker Panel templates (Dashboard, Profile, Apply as Staff, etc.)
```

---

## Roles and Access Controls

1. **Admin**:
   - Comprehensive control over all Treks (Create, Edit, Clone, Delete, Assign Staff).
   - Approves staff applications and manages staff & trekker account statuses (Active, Pending, Blacklisted).
   - Monitors per-trek Financials (Revenue, Expenses, Staff Payouts, Net P&L).
   - Views Occupancy metrics and sends bulk announcements to booked trekkers.
   - Moderates trek photo submissions.

2. **Trek Staff**:
   - Access to dedicated Staff Workspace.
   - Manages day-wise itinerary checklists, gear checklists, and local connects.
   - Logs on-ground trek expenses for admin approval/reimbursement.
   - Submits post-trek debrief reports (weather, trail conditions).
   - Sets personal unavailability / time-off blocks.

3. **User (Trekker)**:
   - Browses open treks with filters for location, difficulty, region, and season.
   - Books trek slots with optional comprehensive trek insurance (₹500/slot).
   - Views upcoming and completed bookings, toggles insurance, or changes batch dates.
   - Submits 1-5 star ratings and reviews for completed treks and staff guides.
   - Can apply to become a staff guide by submitting credentials.

---

## Database Models Summary

- `User`: Accounts for Admin, Staff, and Trekkers with hashed passwords.
- `StaffProfile`: Extended metadata for staff members (home region, contact).
- `Trek`: Trek details, slots, pricing, dates, region, and staff payout rules.
- `Booking`: Slot transactions, insurance status, attendance, and medical/dietary notes.
- `Review`: Ratings and feedback left by trekkers for completed treks.
- `StaffReview`: Ratings and feedback given to staff guides by trekkers.
- `Expense`: On-ground cash expenses logged by staff.
- `StaffPayout`: Calculated earnings for staff per trek.
- `Itinerary`: Day-by-day trek itinerary items.
- `StaffApplication`: Applications submitted by trekkers to join as staff.
- `StaffAvailability`: Blocked dates for staff availability.
- `Announcement`: Broadcast messages sent by admins/staff to trekkers booked on a trek.
- `DebriefReport`: Post-trek condition reports submitted by staff guides.
- `McpWalker`: The throwaway demo trekker behind one MCP visit (deleted after an hour).
- `McpToolCall`: One row per MCP tool call, for the rate limits (kept for an hour).

---

## License

[MIT](LICENSE), Copyright (c) 2026 Sujash Bharadwaj.
