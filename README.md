# Mountains & Maggi — Trekking Management Application

A web-based platform for adventure organizations to manage treks, staff assignments, bookings, expenses, and trekker history. Built with Flask, Jinja2, Bootstrap 5, and SQLite.

## Project Setup & Running

### 1. Prerequisites
Ensure you have Python 3.8+ installed.

### 2. Project Setup
From the root folder, create a virtual environment, activate it, and install the required packages:

```bash
# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install the required packages
pip install Flask Flask-SQLAlchemy
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
│   └── main_routes.py      # Public homepage & Trek detail pages
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
