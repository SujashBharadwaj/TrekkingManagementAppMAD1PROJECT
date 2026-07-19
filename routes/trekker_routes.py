# pyrefly: ignore [missing-import]
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session
# pyrefly: ignore [missing-import]
from werkzeug.security import generate_password_hash
from models import db, User, Trek, Booking, Review, TrekPhoto, Itinerary, StaffApplication, StaffReview
from .utils import login_required, role_required, LIMITS, _truncate, allowed_file, save_photo

trekker_bp = Blueprint('trekker', __name__)


@trekker_bp.route('/user/dashboard')
@login_required
@role_required('trekker')
def user_dashboard():
    my_bookings = Booking.query.filter_by(user_id=session['user_id']).order_by(Booking.booking_date.desc()).all()

    upcoming = [b for b in my_bookings if b.status == 'Booked']
    completed = [b for b in my_bookings if b.status == 'Completed']
    cancelled = [b for b in my_bookings if b.status == 'Cancelled']

    # Which treks has the user already reviewed (trek review)
    reviewed_trek_ids = set()
    if completed:
        reviewed = Review.query.filter(
            Review.user_id == session['user_id'],
            Review.trek_id.in_([b.trek_id for b in completed])
        ).all()
        reviewed_trek_ids = {r.trek_id for r in reviewed}

    # Which staff has the user already reviewed
    reviewed_staff_ids = set()
    if completed:
        staff_reviewed = StaffReview.query.filter(
            StaffReview.user_id == session['user_id'],
            StaffReview.trek_id.in_([b.trek_id for b in completed])
        ).all()
        reviewed_staff_ids = {(sr.staff_id, sr.trek_id) for sr in staff_reviewed}

    # For "Change Date" - find recurring treks for each upcoming booking
    recurring_map = {}
    for b in upcoming:
        alts = Trek.query.filter(
            Trek.name == b.trek.name,
            Trek.id != b.trek_id,
            Trek.status == 'Open'
        ).order_by(Trek.start_date.asc()).all()
        if alts:
            recurring_map[b.id] = alts

    return render_template('user/dashboard.html',
        upcoming=upcoming, completed=completed, cancelled=cancelled,
        reviewed_trek_ids=reviewed_trek_ids,
        reviewed_staff_ids=reviewed_staff_ids,
        recurring_map=recurring_map)


@trekker_bp.route('/search')
@login_required
@role_required('trekker')
def search_treks():
    """Kept for backwards compatibility - redirects to homepage."""
    return redirect(url_for('main.index'))


@trekker_bp.route('/book/<int:id>', methods=['POST'])
@login_required
@role_required('trekker')
def book_trek(id):
    from models import DiscountCode
    trek = db.session.get(Trek, id) or abort(404)
    slots_requested = request.form.get('slots', 1, type=int)
    wants_insurance = request.form.get('insurance') == 'on'

    discount_code_str = request.form.get('discount_code', '').strip().upper()
    medical_info = request.form.get('medical_info', '').strip()
    dietary_needs = request.form.get('dietary_needs', '').strip()

    if slots_requested < 1:
        flash('Must book at least 1 slot.', 'danger')
        return redirect(url_for('main.trek_detail', id=id))
    if trek.status != 'Open':
        flash('This trek is not open for bookings.', 'danger')
        return redirect(url_for('main.trek_detail', id=id))
    if trek.available_slots < slots_requested:
        flash('Not enough available slots.', 'danger')
        return redirect(url_for('main.trek_detail', id=id))

    existing = Booking.query.filter_by(user_id=session['user_id'], trek_id=trek.id, status='Booked').first()
    if existing:
        flash('You have already booked this trek.', 'warning')
        return redirect(url_for('main.trek_detail', id=id))

    # Calculate total price: base * slots + optional insurance (500 per slot)
    base_cost = trek.price * slots_requested
    insurance_cost = 500.0 * slots_requested if wants_insurance else 0.0
    
    discount_amount = 0.0
    if discount_code_str:
        from datetime import date
        code = DiscountCode.query.filter_by(code=discount_code_str, is_active=True).first()
        if not code:
            flash('Invalid or inactive discount code.', 'warning')
        elif code.expiry_date and code.expiry_date < date.today():
            flash('Discount code has expired.', 'warning')
        elif code.max_uses and code.times_used >= code.max_uses:
            flash('Discount code has reached maximum uses.', 'warning')
        else:
            if code.discount_type == 'percent':
                discount_amount = base_cost * (code.value / 100.0)
            else:
                discount_amount = code.value
            discount_amount = min(discount_amount, base_cost)
            code.times_used += 1

    total = base_cost + insurance_cost - discount_amount

    trek.available_slots -= slots_requested
    db.session.add(Booking(
        user_id=session['user_id'], trek_id=trek.id,
        slots_booked=slots_requested, status='Booked',
        has_insurance=wants_insurance, total_price=total,
        discount_amount=discount_amount,
        medical_info=medical_info, dietary_needs=dietary_needs
    ))
    db.session.commit()
    
    msg = f'Trek "{trek.name}" booked for {slots_requested} slot(s). Total: ₹{total:.2f}'
    if discount_amount > 0:
        msg += f' (Discount applied: -₹{discount_amount:.2f})'
    flash(msg, 'success')
    return redirect(url_for('trekker.user_dashboard'))


@trekker_bp.route('/booking/cancel/<int:id>', methods=['POST'])
@login_required
@role_required('trekker')
def cancel_booking(id):
    booking = db.session.get(Booking, id) or abort(404)
    if booking.user_id != session['user_id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))
    if booking.status != 'Booked':
        flash('Only active bookings can be cancelled.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    trek = booking.trek
    trek.available_slots += booking.slots_booked
    booking.status = 'Cancelled'
    db.session.commit()
    flash(f'Booking for "{trek.name}" cancelled. Refund will be processed.', 'success')
    return redirect(url_for('trekker.user_dashboard'))


@trekker_bp.route('/booking/<int:id>/toggle-insurance', methods=['POST'])
@login_required
@role_required('trekker')
def toggle_insurance(id):
    """Toggle insurance on/off for an upcoming booking."""
    booking = db.session.get(Booking, id) or abort(404)
    if booking.user_id != session['user_id'] or booking.status != 'Booked':
        flash('Cannot modify this booking.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    booking.has_insurance = not booking.has_insurance
    # Recalculate price
    base = booking.trek.price * booking.slots_booked
    ins = 500.0 * booking.slots_booked if booking.has_insurance else 0.0
    booking.total_price = base + ins
    db.session.commit()

    status = 'added' if booking.has_insurance else 'removed'
    flash(f'Insurance {status}. New total: ₹{booking.total_price:.2f}', 'success')
    return redirect(url_for('trekker.user_dashboard'))


@trekker_bp.route('/booking/<int:id>/change-date', methods=['POST'])
@login_required
@role_required('trekker')
def change_date(id):
    """Move booking to a different batch of the same recurring trek."""
    booking = db.session.get(Booking, id) or abort(404)
    if booking.user_id != session['user_id'] or booking.status != 'Booked':
        flash('Cannot modify this booking.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    new_trek_id = request.form.get('new_trek_id', type=int)
    new_trek = db.session.get(Trek, new_trek_id) or abort(404)

    # Validate: same trek name, different ID, Open status, enough slots
    if new_trek.name != booking.trek.name:
        flash('Can only switch to another batch of the same trek.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))
    if new_trek.status != 'Open' or new_trek.available_slots < booking.slots_booked:
        flash('The selected batch is not available.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    # Release old slots, assign new
    booking.trek.available_slots += booking.slots_booked
    new_trek.available_slots -= booking.slots_booked
    booking.trek_id = new_trek.id
    # Recalculate price with new trek's price
    base = new_trek.price * booking.slots_booked
    ins = 500.0 * booking.slots_booked if booking.has_insurance else 0.0
    booking.total_price = base + ins
    db.session.commit()

    flash(f'Booking moved to {new_trek.start_date.strftime("%d-%m-%Y")} batch.', 'success')
    return redirect(url_for('trekker.user_dashboard'))


@trekker_bp.route('/user/profile', methods=['GET', 'POST'])
@login_required
@role_required('trekker')
def profile():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        email = _truncate(request.form.get('email', '').strip(), LIMITS['email_max'])
        new_password = request.form.get('password', '')

        if not email:
            flash('Email cannot be empty.', 'danger')
            return render_template('user/profile.html', user=user)
        other = User.query.filter(User.email == email, User.id != user.id).first()
        if other:
            flash('Email is already in use.', 'danger')
            return render_template('user/profile.html', user=user)

        user.email = email
        if new_password:
            if len(new_password) < LIMITS['password_min'] or len(new_password) > LIMITS['password_max']:
                flash(f'Password must be {LIMITS["password_min"]}-{LIMITS["password_max"]} characters.', 'danger')
                return render_template('user/profile.html', user=user)
            user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')

        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('trekker.user_dashboard'))

    return render_template('user/profile.html', user=user)


@trekker_bp.route('/trek/<int:id>/review', methods=['POST'])
@login_required
@role_required('trekker')
def submit_review(id):
    trek = db.session.get(Trek, id) or abort(404)

    # Only allow reviews for completed bookings
    booking = Booking.query.filter_by(
        user_id=session['user_id'], trek_id=trek.id, status='Completed'
    ).first()
    if not booking:
        flash('You can only review treks you have completed.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    # Prevent duplicate reviews
    existing = Review.query.filter_by(user_id=session['user_id'], trek_id=trek.id).first()
    if existing:
        flash('You have already reviewed this trek.', 'warning')
        return redirect(url_for('trekker.user_dashboard'))

    rating = request.form.get('rating', type=int)
    comment = _truncate(request.form.get('comment', '').strip(), LIMITS['review_comment_max'])

    if not rating or rating < 1 or rating > 5:
        flash('Rating must be between 1 and 5.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    review = Review(user_id=session['user_id'], trek_id=trek.id, rating=rating, comment=comment)
    db.session.add(review)
    db.session.commit()
    flash(f'Review submitted for "{trek.name}". Thank you!', 'success')
    return redirect(url_for('trekker.user_dashboard'))


@trekker_bp.route('/trek/<int:trek_id>/rate-staff', methods=['POST'])
@login_required
@role_required('trekker')
def rate_staff(trek_id):
    """Rate the assigned staff/guide for a completed trek."""
    trek = db.session.get(Trek, trek_id) or abort(404)

    if not trek.assigned_staff_id:
        flash('No staff was assigned to this trek.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    booking = Booking.query.filter_by(
        user_id=session['user_id'], trek_id=trek.id, status='Completed'
    ).first()
    if not booking:
        flash('You can only rate staff for treks you have completed.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    # Prevent duplicate staff reviews
    existing = StaffReview.query.filter_by(
        user_id=session['user_id'], staff_id=trek.assigned_staff_id, trek_id=trek.id
    ).first()
    if existing:
        flash('You have already rated the guide for this trek.', 'warning')
        return redirect(url_for('trekker.user_dashboard'))

    rating = request.form.get('staff_rating', type=int)
    comment = _truncate(request.form.get('staff_comment', '').strip(), LIMITS['review_comment_max'])

    if not rating or rating < 1 or rating > 5:
        flash('Rating must be between 1 and 5.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    sr = StaffReview(
        user_id=session['user_id'],
        staff_id=trek.assigned_staff_id,
        trek_id=trek.id,
        rating=rating,
        comment=comment
    )
    db.session.add(sr)
    db.session.commit()
    flash('Staff review submitted. Thank you!', 'success')
    return redirect(url_for('trekker.user_dashboard'))


@trekker_bp.route('/trek/<int:id>/upload-photo', methods=['POST'])
@login_required
@role_required('trekker')
def trekker_upload_photo(id):
    trek = db.session.get(Trek, id) or abort(404)

    # Only allow photo uploads for completed bookings
    booking = Booking.query.filter_by(
        user_id=session['user_id'], trek_id=trek.id, status='Completed'
    ).first()
    if not booking:
        flash('You can only upload photos for treks you have completed.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    file = request.files.get('photo')
    if not file or file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('trekker.user_dashboard'))
    if not allowed_file(file.filename):
        flash('Only .png, .jpg, and .jpeg files are allowed (max 20MB).', 'danger')
        return redirect(url_for('trekker.user_dashboard'))

    filename = save_photo(file)
    photo = TrekPhoto(trek_id=trek.id, uploaded_by=session['user_id'], filename=filename, is_approved=False)
    db.session.add(photo)
    db.session.commit()
    flash('Photo uploaded successfully and is pending admin approval.', 'success')
    return redirect(url_for('trekker.user_dashboard'))


@trekker_bp.route('/trek/<int:id>/itinerary')
def view_itinerary(id):
    """Public itinerary page - viewable by anyone, shows only approved entries."""
    trek = db.session.get(Trek, id) or abort(404)
    items = Itinerary.query.filter_by(trek_id=id, is_approved=True).order_by(Itinerary.day_number).all()
    return render_template('user/itinerary.html', trek=trek, items=items)


@trekker_bp.route('/apply-staff', methods=['GET', 'POST'])
@login_required
@role_required('trekker')
def apply_staff():
    """Let a trekker apply to become staff."""
    # Check if already applied
    existing = StaffApplication.query.filter_by(user_id=session['user_id']).first()
    if existing:
        flash(f'You have already applied. Status: {existing.status}', 'info')
        return redirect(url_for('trekker.user_dashboard'))

    if request.method == 'POST':
        aadhar = _truncate(request.form.get('aadhar', '').strip(), 50)
        region = _truncate(request.form.get('region', '').strip(), 100)
        certification = _truncate(request.form.get('certification', '').strip(), 200)
        level = request.form.get('level', 'Beginner')

        if not aadhar or not region:
            flash('Aadhar/Passport and Region are required.', 'danger')
            return render_template('user/apply_staff.html')
        if level not in ('Beginner', 'Intermediate', 'Advanced'):
            level = 'Beginner'

        app = StaffApplication(
            user_id=session['user_id'],
            aadhar_or_passport=aadhar,
            region=region,
            certification=certification,
            experience_level=level
        )
        db.session.add(app)
        db.session.commit()
        flash('Staff application submitted! Management will review it.', 'success')
        return redirect(url_for('trekker.user_dashboard'))

    return render_template('user/apply_staff.html')
