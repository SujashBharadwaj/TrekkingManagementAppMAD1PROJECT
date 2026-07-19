from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from datetime import datetime, date
from sqlalchemy import func
from models import (db, User, StaffProfile, Trek, Booking, TrekPhoto, Expense,
                    SafetyGuide, StaffPayout)
from .utils import login_required, role_required, LIMITS, _safe_int, _truncate, allowed_file, save_photo

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/dashboard')
@login_required
@role_required('admin')
def admin_dashboard():
    total_treks = Trek.query.count()
    total_users = User.query.filter_by(role='trekker').count()
    total_staff = User.query.filter_by(role='staff').count()
    total_bookings = Booking.query.count()
    pending_staff = User.query.filter_by(role='staff', status='pending').count()

    # Feature #14: Check for any treks in Emergency status
    emergency_treks = Trek.query.filter_by(status='Emergency').all()

    # Quick revenue stat
    total_revenue = db.session.query(func.sum(Booking.total_price)).filter(
        Booking.status.in_(['Booked', 'Completed'])
    ).scalar() or 0.0

    pending_expenses = Expense.query.filter_by(status='Pending').count()

    return render_template('admin/dashboard.html',
        total_treks=total_treks, total_users=total_users,
        total_staff=total_staff, total_bookings=total_bookings,
        pending_staff=pending_staff, emergency_treks=emergency_treks,
        total_revenue=total_revenue, pending_expenses=pending_expenses)


@admin_bp.route('/treks')
@login_required
@role_required('admin')
def admin_treks():
    search = request.args.get('q', '').strip()
    query = Trek.query

    if search:
        search_id = _safe_int(search)
        if search_id is not None:
            query = query.filter(
                (Trek.name.ilike(f'%{search}%')) |
                (Trek.location.ilike(f'%{search}%')) |
                (Trek.id == search_id))
        else:
            query = query.filter(
                (Trek.name.ilike(f'%{search}%')) |
                (Trek.location.ilike(f'%{search}%')))

    treks = query.order_by(Trek.id.desc()).all()
    approved_staff = User.query.filter_by(role='staff', status='active').all()

    difficulty_counts = {'Easy': 0, 'Moderate': 0, 'Hard': 0}
    all_treks = Trek.query.all()
    for t in all_treks:
        if t.difficulty in difficulty_counts:
            difficulty_counts[t.difficulty] += 1

    safety_guides = SafetyGuide.query.all()

    return render_template('admin/treks.html',
        treks=treks, approved_staff=approved_staff,
        search=search, difficulty_counts=difficulty_counts,
        safety_guides=safety_guides)


@admin_bp.route('/trek/add', methods=['POST'])
@login_required
@role_required('admin')
def add_trek():
    name = _truncate(request.form.get('name', '').strip(), LIMITS['trek_name_max'])
    location = _truncate(request.form.get('location', '').strip(), LIMITS['location_max'])
    difficulty = request.form.get('difficulty', 'Easy')
    duration = request.form.get('duration', type=int)
    total_slots = request.form.get('slots', type=int)
    assigned_staff_id = request.form.get('staff_id', type=int)
    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')
    price = request.form.get('price', 0.0, type=float)
    description = _truncate(request.form.get('description', '').strip(), LIMITS['description_max'])

    if not name or not location or duration is None or total_slots is None or not start_date_str or not end_date_str:
        flash('All core fields are required.', 'danger')
        return redirect(url_for('admin.admin_treks'))
    if difficulty not in ('Easy', 'Moderate', 'Hard'):
        flash('Invalid difficulty level.', 'danger')
        return redirect(url_for('admin.admin_treks'))
    if duration < 1 or duration > LIMITS['duration_max']:
        flash(f'Duration must be between 1 and {LIMITS["duration_max"]} days.', 'danger')
        return redirect(url_for('admin.admin_treks'))
    if total_slots < 1 or total_slots > LIMITS['slots_max']:
        flash(f'Slots must be between 1 and {LIMITS["slots_max"]}.', 'danger')
        return redirect(url_for('admin.admin_treks'))
    if price < 0 or price > LIMITS['price_max']:
        flash(f'Price must be between 0 and {LIMITS["price_max"]}.', 'danger')
        return redirect(url_for('admin.admin_treks'))

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format.', 'danger')
        return redirect(url_for('admin.admin_treks'))

    if start_date < date.today():
        flash('Start date cannot be in the past.', 'danger')
        return redirect(url_for('admin.admin_treks'))

    if end_date < start_date:
        flash('End date cannot be before start date.', 'danger')
        return redirect(url_for('admin.admin_treks'))

    assigned_staff_id = assigned_staff_id if assigned_staff_id and assigned_staff_id != 0 else None

    new_trek = Trek(
        name=name, location=location, difficulty=difficulty,
        duration=duration, total_slots=total_slots, available_slots=total_slots,
        assigned_staff_id=assigned_staff_id, status='Pending',
        start_date=start_date, end_date=end_date,
        description=description, price=price
    )
    db.session.add(new_trek)
    db.session.commit()
    flash(f'Trek "{name}" created successfully.', 'success')
    return redirect(url_for('admin.admin_treks'))


@admin_bp.route('/trek/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_trek(id):
    trek = db.session.get(Trek, id) or abort(404)
    approved_staff = User.query.filter_by(role='staff', status='active').all()
    safety_guides = SafetyGuide.query.all()

    if request.method == 'POST':
        trek.name = _truncate(request.form.get('name', '').strip(), LIMITS['trek_name_max'])
        trek.location = _truncate(request.form.get('location', '').strip(), LIMITS['location_max'])
        trek.difficulty = request.form.get('difficulty')
        trek.duration = request.form.get('duration', type=int)

        new_total_slots = request.form.get('slots', type=int)
        booked_slots = trek.total_slots - trek.available_slots

        if new_total_slots is None or new_total_slots < 1 or new_total_slots > LIMITS['slots_max']:
            flash(f'Slots must be between 1 and {LIMITS["slots_max"]}.', 'danger')
            return redirect(url_for('admin.edit_trek', id=id))
        if new_total_slots < booked_slots:
            flash(f'Cannot set slots to {new_total_slots}. {booked_slots} already booked.', 'danger')
            return redirect(url_for('admin.edit_trek', id=id))

        trek.total_slots = new_total_slots
        trek.available_slots = new_total_slots - booked_slots

        assigned_staff_id = request.form.get('staff_id', type=int)
        trek.assigned_staff_id = assigned_staff_id if assigned_staff_id and assigned_staff_id != 0 else None

        try:
            new_start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
            new_end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            flash('Invalid date format.', 'danger')
            return redirect(url_for('admin.edit_trek', id=id))

        if new_start_date < date.today() and new_start_date != trek.start_date:
            flash('Start date cannot be moved to the past.', 'danger')
            return redirect(url_for('admin.edit_trek', id=id))

        if new_end_date < new_start_date:
            flash('End date cannot be before start date.', 'danger')
            return redirect(url_for('admin.edit_trek', id=id))

        trek.start_date = new_start_date
        trek.end_date = new_end_date

        price = request.form.get('price', 0.0, type=float)
        if price < 0 or price > LIMITS['price_max']:
            flash(f'Price must be between 0 and {LIMITS["price_max"]}.', 'danger')
            return redirect(url_for('admin.edit_trek', id=id))
        trek.price = price
        trek.description = _truncate(request.form.get('description', '').strip(), LIMITS['description_max'])
        trek.status = request.form.get('status')

        # Feature #2: Staff payout config
        commission_pct = request.form.get('commission_pct', type=float)
        flat_salary = request.form.get('flat_salary', type=float)
        if commission_pct is not None:
            trek.staff_commission_pct = commission_pct
        if flat_salary is not None and flat_salary > 0:
            trek.staff_flat_salary = flat_salary
        elif flat_salary == 0:
            trek.staff_flat_salary = None

        # Feature #6: Safety guide assignment
        guide_id = request.form.get('safety_guide_id', type=int)
        trek.safety_guide_id = guide_id if guide_id and guide_id != 0 else None

        # Feature #18: Gear checklist
        gear = request.form.get('gear_checklist', '').strip()
        trek.gear_checklist = gear if gear else None

        # Feature #20: Local connects
        connects = request.form.get('local_connects', '').strip()
        trek.local_connects = connects if connects else None

        db.session.commit()
        flash('Trek updated successfully.', 'success')
        return redirect(url_for('admin.admin_treks'))

    return render_template('admin/edit_trek.html', trek=trek, approved_staff=approved_staff,
                           safety_guides=safety_guides)


@admin_bp.route('/trek/delete/<int:id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_trek(id):
    trek = db.session.get(Trek, id) or abort(404)
    db.session.delete(trek)
    db.session.commit()
    flash('Trek deleted successfully.', 'success')
    return redirect(url_for('admin.admin_treks'))


@admin_bp.route('/trek/<int:id>/upload-photo', methods=['POST'])
@login_required
@role_required('admin')
def admin_upload_photo(id):
    trek = db.session.get(Trek, id) or abort(404)
    file = request.files.get('photo')
    if not file or file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('admin.edit_trek', id=id))
    if not allowed_file(file.filename):
        flash('Only .png, .jpg, and .jpeg files are allowed.', 'danger')
        return redirect(url_for('admin.edit_trek', id=id))

    from flask import session as flask_session
    filename = save_photo(file)
    photo = TrekPhoto(trek_id=trek.id, uploaded_by=flask_session['user_id'], filename=filename, is_approved=True)
    db.session.add(photo)
    db.session.commit()
    flash('Photo uploaded successfully.', 'success')
    return redirect(url_for('admin.edit_trek', id=id))


@admin_bp.route('/staff')
@login_required
@role_required('admin')
def admin_staff():
    search = request.args.get('q', '').strip()
    query = User.query.filter_by(role='staff')

    if search:
        search_id = _safe_int(search)
        if search_id is not None:
            query = query.filter(
                (User.username.ilike(f'%{search}%')) |
                (User.id == search_id))
        else:
            query = query.join(StaffProfile, isouter=True).filter(
                (User.username.ilike(f'%{search}%')) |
                (StaffProfile.name.ilike(f'%{search}%')))

    staff_list = query.all()
    return render_template('admin/staff.html', staff_list=staff_list, search=search)


@admin_bp.route('/staff/approve/<int:id>', methods=['POST'])
@login_required
@role_required('admin')
def approve_staff(id):
    staff = db.session.get(User, id) or abort(404)
    if staff.role == 'staff':
        staff.status = 'active'
        db.session.commit()
        flash(f'Staff {staff.username} approved.', 'success')
    return redirect(url_for('admin.admin_staff'))


@admin_bp.route('/staff/blacklist/<int:id>', methods=['POST'])
@login_required
@role_required('admin')
def blacklist_user(id):
    user = db.session.get(User, id) or abort(404)
    user.status = 'blacklisted'
    db.session.commit()
    flash(f'{user.username} has been blacklisted.', 'warning')
    ref = request.form.get('next', url_for('admin.admin_staff'))
    return redirect(ref)


@admin_bp.route('/staff/activate/<int:id>', methods=['POST'])
@login_required
@role_required('admin')
def activate_user(id):
    user = db.session.get(User, id) or abort(404)
    user.status = 'active'
    db.session.commit()
    flash(f'{user.username} reactivated.', 'success')
    ref = request.form.get('next', url_for('admin.admin_staff'))
    return redirect(ref)


@admin_bp.route('/users')
@login_required
@role_required('admin')
def admin_users():
    search = request.args.get('q', '').strip()
    query = User.query.filter_by(role='trekker')

    if search:
        search_id = _safe_int(search)
        if search_id is not None:
            query = query.filter(
                (User.username.ilike(f'%{search}%')) |
                (User.email.ilike(f'%{search}%')) |
                (User.id == search_id))
        else:
            query = query.filter(
                (User.username.ilike(f'%{search}%')) |
                (User.email.ilike(f'%{search}%')))

    users = query.all()
    return render_template('admin/users.html', users=users, search=search)


@admin_bp.route('/bookings')
@login_required
@role_required('admin')
def view_all_bookings():
    bookings = Booking.query.order_by(Booking.booking_date.desc()).all()
    return render_template('admin/bookings.html', bookings=bookings)


@admin_bp.route('/photos/pending')
@login_required
@role_required('admin')
def pending_photos():
    photos = TrekPhoto.query.filter_by(is_approved=False).order_by(TrekPhoto.created_at.desc()).all()
    return render_template('admin/pending_photos.html', photos=photos)


@admin_bp.route('/photos/approve/<int:photo_id>', methods=['POST'])
@login_required
@role_required('admin')
def approve_photo(photo_id):
    photo = db.session.get(TrekPhoto, photo_id) or abort(404)
    photo.is_approved = True
    db.session.commit()
    flash('Photo approved successfully.', 'success')
    return redirect(url_for('admin.pending_photos'))


@admin_bp.route('/photos/reject/<int:photo_id>', methods=['POST'])
@login_required
@role_required('admin')
def reject_photo(photo_id):
    photo = db.session.get(TrekPhoto, photo_id) or abort(404)
    db.session.delete(photo)
    db.session.commit()
    flash('Photo rejected and deleted.', 'info')
    return redirect(url_for('admin.pending_photos'))
