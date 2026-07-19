# Mountains & Maggi — Trekking Management Application

A web-based platform for adventure organizations to manage treks, staff assignments, bookings, and trekker history. Built with Flask, Jinja2, Bootstrap 5, and SQLite.

## Project Setup & Running

### 1. Prerequisites
Ensure you have Python 3.8+ installed.

### 2. Project Setup
From the `trekking_manager` root folder, create a virtual environment, activate it, and install the required packages:

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
- Seed the database with mock data including the default admin account.
- Start the server at `http://127.0.0.1:4200`.

**Default Admin Credentials:**
* **Username**: `admin`
* **Password**: `adminisadmin@123?!?!`

**Default Staff Credentials:**
* **Username**: `staff1` or `staff2` | **Password**: `staff123`

**Default Trekker Credentials:**
* **Username**: `user1` through `user5` | **Password**: `user123`

---

## Architecture

The application follows the **Flask Blueprints** pattern for modularity:

```text
trekking_manager/
│
├── app.py                  # App factory, blueprint registration, seed data
├── models.py               # SQLAlchemy models (User, Trek, Booking, Review, TrekPhoto, StaffProfile)
├── config.py               # Configuration (secret key, SQLite URI, upload settings)
│
├── routes/                 # Flask Blueprints (modular route files)
│   ├── __init__.py         # Exports all blueprints
│   ├── utils.py            # Shared decorators (login_required, role_required), helpers
│   ├── auth_routes.py      # Login, Register, Logout
│   ├── admin_routes.py     # Admin dashboard, trek/staff/user CRUD, photo uploads
│   ├── staff_routes.py     # Staff workspace, trek editing, participants, photo uploads
│   ├── trekker_routes.py   # Trekker dashboard, booking, search, reviews, photo uploads
│   └── main_routes.py      # Public homepage
│
├── static/
│   ├── css/style.css       # Global CSS stylesheet
│   └── uploads/photos/     # User-uploaded trek photos
│
└── templates/              # Jinja2 HTML templates
    ├── base.html           # Global layout (navbar, alerts, footer)
    ├── index.html           # Public homepage
    ├── login.html           # Login form
    ├── register.html        # Registration form
    ├── admin/               # Admin panel templates
    ├── staff/               # Staff panel templates
    └── user/                # Trekker panel templates
```

---

## Roles and Access Controls

1. **Admin**:
   - Manages all treks (Create, Read, Update, Delete).
   - Approves newly registered staff profiles or blacklists/deactivates staff & users.
   - Assigns approved staff members to treks.
   - Uploads promotional photos for treks.
   - Searches and views all treks, staff, users, and historical booking logs.
2. **Trek Staff**:
   - Registration requires Admin approval status to gain access to the dashboard.
   - Updates available slots, price, or description for their assigned treks.
   - Views registered trekkers list for their treks.
   - Uploads photos for assigned treks.
   - Transitions trek status: `Pending` → `Approved` → `Open` → `Closed` → `Completed`.
3. **User (Trekker)**:
   - Registers and browses open treks.
   - Filters treks by **location**, **difficulty**, and **best season** on the homepage.
   - Views **day-wise itinerary** pages for treks (published by staff, approved by admin).
   - Books treks with optional **insurance** add-on (₹500/slot). Sees total price breakdown.
   - Views history of booked, cancelled, and completed treks with insurance/total details.
   - Leaves ratings (1-5 stars) and comments for completed treks.
   - Uploads photos for completed treks.
   - Can **apply as staff** by submitting Aadhar/Passport, region, certifications, and experience level.
   - Updates contact details and user profile.

---

## Features Beyond Core Requirements

- **Photo Uploads**: Admin, Staff, and Trekkers can upload trek photos (.png, .jpg, .jpeg, max 2MB).
- **Ratings & Reviews**: Trekkers can rate and review completed treks with 1-5 star ratings.
- **Star Rating Display**: Average star ratings are displayed on trek cards across the application.
- **Blueprint Architecture**: Codebase is modular with Flask Blueprints for scalability.
- **Homepage Filtering**: Filter treks by region, difficulty level, and season without page reloads.
- **Itinerary Pages**: Day-wise trek itineraries with distance per day, managed by staff and approved by admin.
- **Insurance & Payment Details**: Users can opt into insurance at booking. Total price (base + insurance) is stored and displayed.
- **Staff Application**: Trekkers can apply to become guides by submitting ID, region, certifications, and experience level.
- **Travel Inclusion Indicator**: Each trek shows whether transport to the base camp is included in the price.
- **UI & Typography Enhancements**: Uses Copperplate Gothic for headers, and displays single vibrant scenery cards.
- **Staff Attendance & Expenses**: Staff can mark trekker attendance and log on-ground expenses for admin reimbursement.


