from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

# Initialize db instance to be bound to Flask app later
db = SQLAlchemy()

class User(db.Model):
    """User model representing Admins, Trek Staff, and Trekkers (Users)."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'staff', 'trekker'
    status = db.Column(db.String(20), nullable=False, default='active')  # 'active', 'pending', 'blacklisted'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    # One-to-One relationship with StaffProfile if user is staff
    staff_profile = db.relationship('StaffProfile', backref='user', uselist=False, cascade="all, delete-orphan")
    # One-to-Many relationship with bookings
    bookings = db.relationship('Booking', backref='user', cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"

class StaffProfile(db.Model):
    """Detailed profile data for Trek Staff."""
    __tablename__ = 'staff_profiles'

    # Primary key is also foreign key linking to users table
    id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact_details = db.Column(db.String(200), nullable=True)
    home_region = db.Column(db.String(100), nullable=True)  # Feature #3/#19: staff home region

    def __repr__(self):
        return f"<StaffProfile {self.name} (ID: {self.id})>"

class Trek(db.Model):
    """Trek routes and active trekking runs."""
    __tablename__ = 'treks'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    region = db.Column(db.String(20), nullable=True)  # 'North', 'South', 'East', 'West', 'Central'
    difficulty = db.Column(db.String(20), nullable=False)  # 'Easy', 'Moderate', 'Hard'
    duration = db.Column(db.Integer, nullable=False)  # in days
    best_season = db.Column(db.String(30), nullable=True)  # 'Winter', 'Summer', 'Monsoon', 'Autumn'
    route_kms = db.Column(db.Float, nullable=True)  # total distance in km
    exit_points = db.Column(db.Text, nullable=True)  # comma-separated exit points
    travel_included = db.Column(db.Boolean, default=True)  # is transport included in price
    available_slots = db.Column(db.Integer, nullable=False)
    total_slots = db.Column(db.Integer, nullable=False)
    
    # Staff assignment (User with role='staff')
    assigned_staff_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    
    # Status flows: 'Pending', 'Approved', 'Open', 'Closed', 'Completed', 'Emergency'
    status = db.Column(db.String(20), nullable=False, default='Pending')
    
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=True)
    base_camp_info = db.Column(db.Text, nullable=True)  # logistics/info about how to reach base camp
    price = db.Column(db.Float, nullable=False, default=0.0)

    # Feature #2: Staff payout config
    staff_commission_pct = db.Column(db.Float, default=10.0)  # default 10% commission
    staff_flat_salary = db.Column(db.Float, nullable=True)  # if set, overrides commission

    # Feature #6: Safety guide link
    safety_guide_id = db.Column(db.Integer, db.ForeignKey('safety_guides.id', ondelete='SET NULL'), nullable=True)

    # Feature #18: Equipment/gear checklist (comma-separated items)
    gear_checklist = db.Column(db.Text, nullable=True)

    # Feature #20: Local connects directory (stored as text, line-separated entries)
    local_connects = db.Column(db.Text, nullable=True)

    # Relationships
    assigned_staff = db.relationship('User', backref=db.backref('assigned_treks', lazy=True))
    bookings = db.relationship('Booking', backref='trek', cascade="all, delete-orphan")
    safety_guide = db.relationship('SafetyGuide', backref=db.backref('treks', lazy=True))

    def __repr__(self):
        return f"<Trek {self.name} - {self.status}>"

class Booking(db.Model):
    """Trek bookings placed by trekkers."""
    __tablename__ = 'bookings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    trek_id = db.Column(db.Integer, db.ForeignKey('treks.id', ondelete='CASCADE'), nullable=False)
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    slots_booked = db.Column(db.Integer, nullable=False, default=1)
    has_insurance = db.Column(db.Boolean, default=False)  # did user opt for insurance
    total_price = db.Column(db.Float, nullable=True)  # calculated price at booking time

    # Status flows: 'Booked', 'Cancelled', 'Completed'
    status = db.Column(db.String(20), nullable=False, default='Booked')
    attendance_status = db.Column(db.String(20), nullable=True)  # 'Present', 'No-Show'

    # Feature #7: Discount code applied
    discount_code_id = db.Column(db.Integer, db.ForeignKey('discount_codes.id', ondelete='SET NULL'), nullable=True)
    discount_amount = db.Column(db.Float, default=0.0)

    # Feature #15: Medical & dietary info
    medical_info = db.Column(db.Text, nullable=True)
    dietary_needs = db.Column(db.Text, nullable=True)

    discount_code = db.relationship('DiscountCode', backref=db.backref('bookings_used', lazy=True))

    def __repr__(self):
        return f"<Booking {self.id} - User: {self.user_id} - Trek: {self.trek_id}>"

class Review(db.Model):
    """Ratings and reviews left by trekkers after completing a trek."""
    __tablename__ = 'reviews'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    trek_id = db.Column(db.Integer, db.ForeignKey('treks.id', ondelete='CASCADE'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1 to 5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('reviews', lazy=True))
    trek = db.relationship('Trek', backref=db.backref('reviews', lazy=True))

    def __repr__(self):
        return f"<Review {self.id} - User: {self.user_id} - Trek: {self.trek_id} - Rating: {self.rating}>"

class TrekPhoto(db.Model):
    """Photos uploaded for treks by admin, staff, or trekkers."""
    __tablename__ = 'trek_photos'

    id = db.Column(db.Integer, primary_key=True)
    trek_id = db.Column(db.Integer, db.ForeignKey('treks.id', ondelete='CASCADE'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    trek = db.relationship('Trek', backref=db.backref('photos', lazy=True))
    uploader = db.relationship('User', backref=db.backref('uploaded_photos', lazy=True))

    def __repr__(self):
        return f"<TrekPhoto {self.id} - Trek: {self.trek_id}>"


class Itinerary(db.Model):
    """Day-wise itinerary for a trek. Staff creates, admin approves."""
    __tablename__ = 'itineraries'

    id = db.Column(db.Integer, primary_key=True)
    trek_id = db.Column(db.Integer, db.ForeignKey('treks.id', ondelete='CASCADE'), nullable=False)
    day_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(150), nullable=False)  # e.g. 'Base Camp to Summit'
    description = db.Column(db.Text, nullable=True)
    distance_km = db.Column(db.Float, nullable=True)
    is_approved = db.Column(db.Boolean, default=False)  # admin must approve
    is_completed = db.Column(db.Boolean, default=False)  # Feature #17: staff marks days as done

    trek = db.relationship('Trek', backref=db.backref('itineraries', lazy=True, order_by='Itinerary.day_number'))

    def __repr__(self):
        return f"<Itinerary Day {self.day_number} - Trek: {self.trek_id}>"


class StaffApplication(db.Model):
    """Trekkers applying to become staff. Admin reviews these."""
    __tablename__ = 'staff_applications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    aadhar_or_passport = db.Column(db.String(50), nullable=False)
    region = db.Column(db.String(100), nullable=False)  # home region
    certification = db.Column(db.String(200), nullable=True)  # mountaineering certs
    experience_level = db.Column(db.String(30), nullable=False)  # 'Beginner', 'Intermediate', 'Advanced'
    status = db.Column(db.String(20), default='Pending')  # 'Pending', 'Approved', 'Rejected'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('staff_application', uselist=False))

    def __repr__(self):
        return f"<StaffApplication User: {self.user_id} - {self.status}>"


class StaffReview(db.Model):
    """Trekker rates their trek guide/staff after completing a trek."""
    __tablename__ = 'staff_reviews'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    trek_id = db.Column(db.Integer, db.ForeignKey('treks.id', ondelete='CASCADE'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1 to 5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('staff_reviews_given', lazy=True))
    staff = db.relationship('User', foreign_keys=[staff_id], backref=db.backref('staff_reviews_received', lazy=True))
    trek = db.relationship('Trek', backref=db.backref('staff_reviews', lazy=True))

    def __repr__(self):
        return f"<StaffReview User:{self.user_id} Staff:{self.staff_id} Rating:{self.rating}>"

class Expense(db.Model):
    """Expenses logged by staff for a trek."""
    __tablename__ = 'expenses'

    id = db.Column(db.Integer, primary_key=True)
    trek_id = db.Column(db.Integer, db.ForeignKey('treks.id', ondelete='CASCADE'), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Pending')  # 'Pending', 'Approved', 'Paid', 'Rejected'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    trek = db.relationship('Trek', backref=db.backref('expenses', lazy=True, cascade="all, delete-orphan"))
    staff = db.relationship('User', backref=db.backref('expenses_logged', lazy=True))

    def __repr__(self):
        return f"<Expense {self.id} - Trek: {self.trek_id} - Amount: {self.amount}>"


# =====================================================
# NEW MODELS FOR FEATURES #1-#20
# =====================================================

class StaffPayout(db.Model):
    """Feature #2/#10: Staff payout records per trek."""
    __tablename__ = 'staff_payouts'

    id = db.Column(db.Integer, primary_key=True)
    trek_id = db.Column(db.Integer, db.ForeignKey('treks.id', ondelete='CASCADE'), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    payout_type = db.Column(db.String(20), nullable=False, default='commission')  # 'commission' or 'flat'
    commission_pct = db.Column(db.Float, nullable=True)  # e.g. 10.0 for 10%
    flat_amount = db.Column(db.Float, nullable=True)  # flat salary amount
    calculated_amount = db.Column(db.Float, default=0.0)  # final calculated payout
    is_paid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    trek = db.relationship('Trek', backref=db.backref('staff_payouts', lazy=True))
    staff = db.relationship('User', backref=db.backref('payouts', lazy=True))

    def __repr__(self):
        return f"<StaffPayout Trek:{self.trek_id} Staff:{self.staff_id} Amount:{self.calculated_amount}>"


class SafetyGuide(db.Model):
    """Feature #6/#13: Safety protocols and emergency guides created by admin."""
    __tablename__ = 'safety_guides'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)  # main guide body (protocols, instructions)
    emergency_contacts = db.Column(db.Text, nullable=True)  # line-separated emergency contacts
    exit_points = db.Column(db.Text, nullable=True)  # line-separated exit points
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<SafetyGuide {self.title}>"


class DiscountCode(db.Model):
    """Feature #7: Promo/discount codes for trekkers at checkout."""
    __tablename__ = 'discount_codes'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(10), nullable=False, default='percent')  # 'percent' or 'flat'
    value = db.Column(db.Float, nullable=False)  # e.g. 10.0 for 10% or 500 for ₹500
    max_uses = db.Column(db.Integer, nullable=True)  # null = unlimited
    times_used = db.Column(db.Integer, default=0)
    expiry_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DiscountCode {self.code} ({self.discount_type}: {self.value})>"


class Announcement(db.Model):
    """Feature #8: Bulk announcements tied to a trek for booked trekkers."""
    __tablename__ = 'announcements'

    id = db.Column(db.Integer, primary_key=True)
    trek_id = db.Column(db.Integer, db.ForeignKey('treks.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    trek = db.relationship('Trek', backref=db.backref('announcements', lazy=True, order_by='Announcement.created_at.desc()'))

    def __repr__(self):
        return f"<Announcement {self.title} - Trek:{self.trek_id}>"


class DebriefReport(db.Model):
    """Feature #16: Post-trek debrief submitted by staff."""
    __tablename__ = 'debrief_reports'

    id = db.Column(db.Integer, primary_key=True)
    trek_id = db.Column(db.Integer, db.ForeignKey('treks.id', ondelete='CASCADE'), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    trail_conditions = db.Column(db.Text, nullable=True)
    weather_report = db.Column(db.Text, nullable=True)
    general_feedback = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    trek = db.relationship('Trek', backref=db.backref('debrief_reports', lazy=True))
    staff = db.relationship('User', backref=db.backref('debrief_reports', lazy=True))

    def __repr__(self):
        return f"<DebriefReport Trek:{self.trek_id} Staff:{self.staff_id}>"


class StaffAvailability(db.Model):
    """Feature #19: Staff blocked/unavailable date ranges."""
    __tablename__ = 'staff_availability'

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    unavailable_from = db.Column(db.Date, nullable=False)
    unavailable_to = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    staff = db.relationship('User', backref=db.backref('availability_blocks', lazy=True))

    def __repr__(self):
        return f"<StaffAvailability Staff:{self.staff_id} {self.unavailable_from} to {self.unavailable_to}>"
