from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session
from datetime import date
from models import (db, User, Trek, Booking, TrekPhoto, Expense, StaffAvailability)
from .utils import login_required, role_required, LIMITS, _truncate, allowed_file, save_photo

staff_bp = Blueprint('staff', __name__, url_prefix='/staff')


@staff_bp.route('/dashboard')
@login_required
@role_required('staff')
def staff_dashboard():
    staff_user = db.session.get(User, session['user_id'])
    if staff_user.status != 'active':
        session.clear()
        flash('Your account is not approved or has been deactivated.', 'danger')
        return redirect(url_for('auth.login'))

    assigned_treks = Trek.query.filter_by(assigned_staff_id=staff_user.id).all()

    # Check for any availability blocks
    blocks = StaffAvailability.query.filter_by(staff_id=staff_user.id).filter(
        StaffAvailability.unavailable_to >= date.today()
    ).order_by(StaffAvailability.unavailable_from).all()

    return render_template('staff/dashboard.html', treks=assigned_treks, availability_blocks=blocks)


@staff_bp.route('/trek/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('staff')
def staff_edit_trek(id):
    trek = db.session.get(Trek, id) or abort(404)

    if trek.assigned_staff_id != session['user_id']:
        flash('You are not assigned to this trek.', 'danger')
        return redirect(url_for('staff.staff_dashboard'))

    if request.method == 'POST':
        new_slots = request.form.get('slots', type=int)
        if new_slots is not None:
            if new_slots < 1 or new_slots > LIMITS['slots_max']:
                flash(f'Slots must be between 1 and {LIMITS["slots_max"]}.', 'danger')
                return redirect(url_for('staff.staff_edit_trek', id=id))
            booked_slots = trek.total_slots - trek.available_slots
            if new_slots < booked_slots:
                flash(f'Cannot reduce below booked capacity ({booked_slots}).', 'danger')
                return redirect(url_for('staff.staff_edit_trek', id=id))
            trek.total_slots = new_slots
            trek.available_slots = new_slots - booked_slots

        new_status = request.form.get('status')
        if new_status in ('Pending', 'Approved', 'Open', 'In Progress', 'Closed', 'Completed'):
            trek.status = new_status

        trek.description = _truncate(request.form.get('description', '').strip(), LIMITS['description_max'])

        price = request.form.get('price', 0.0, type=float)
        if price < 0 or price > LIMITS['price_max']:
            flash(f'Price must be between 0 and {LIMITS["price_max"]}.', 'danger')
            return redirect(url_for('staff.staff_edit_trek', id=id))
        trek.price = price

        db.session.commit()
        flash('Trek updated successfully.', 'success')
        return redirect(url_for('staff.staff_dashboard'))

    return render_template('staff/edit_trek.html', trek=trek)


@staff_bp.route('/trek/participants/<int:id>')
@login_required
@role_required('staff')
def view_participants(id):
    trek = db.session.get(Trek, id) or abort(404)
    if trek.assigned_staff_id != session['user_id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('staff.staff_dashboard'))

    active_bookings = Booking.query.filter_by(trek_id=trek.id, status='Booked').all()
    return render_template('staff/participants.html', trek=trek, bookings=active_bookings)


@staff_bp.route('/trek/participants/<int:trek_id>/attendance/<int:booking_id>', methods=['POST'])
@login_required
@role_required('staff')
def mark_attendance(trek_id, booking_id):
    trek = db.session.get(Trek, trek_id) or abort(404)
    if trek.assigned_staff_id != session['user_id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('staff.staff_dashboard'))

    booking = db.session.get(Booking, booking_id) or abort(404)
    if booking.trek_id != trek.id:
        abort(400)

    status = request.form.get('attendance_status')
    if status in ['Present', 'No-Show']:
        booking.attendance_status = status
        db.session.commit()
        flash('Attendance updated.', 'success')
    return redirect(url_for('staff.view_participants', id=trek_id))


@staff_bp.route('/trek/<int:id>/expenses', methods=['GET', 'POST'])
@login_required
@role_required('staff')
def staff_expenses(id):
    trek = db.session.get(Trek, id) or abort(404)
    if trek.assigned_staff_id != session['user_id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('staff.staff_dashboard'))

    if request.method == 'POST':
        amount = request.form.get('amount', type=float)
        description = request.form.get('description', '').strip()
        if not amount or amount <= 0:
            flash('Invalid amount.', 'danger')
        elif not description:
            flash('Description required.', 'danger')
        else:
            expense = Expense(trek_id=trek.id, staff_id=session['user_id'], amount=amount, description=description)
            db.session.add(expense)
            db.session.commit()
            flash('Expense logged successfully.', 'success')
        return redirect(url_for('staff.staff_expenses', id=id))

    expenses = Expense.query.filter_by(trek_id=trek.id).order_by(Expense.created_at.desc()).all()
    return render_template('staff/expenses.html', trek=trek, expenses=expenses)


@staff_bp.route('/trek/<int:id>/upload-photo', methods=['POST'])
@login_required
@role_required('staff')
def staff_upload_photo(id):
    trek = db.session.get(Trek, id) or abort(404)
    if trek.assigned_staff_id != session['user_id']:
        flash('You are not assigned to this trek.', 'danger')
        return redirect(url_for('staff.staff_dashboard'))

    file = request.files.get('photo')
    if not file or file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('staff.staff_edit_trek', id=id))
    if not allowed_file(file.filename):
        flash('Only .png, .jpg, and .jpeg files are allowed.', 'danger')
        return redirect(url_for('staff.staff_edit_trek', id=id))

    filename = save_photo(file)
    photo = TrekPhoto(trek_id=trek.id, uploaded_by=session['user_id'], filename=filename, is_approved=False)
    db.session.add(photo)
    db.session.commit()
    flash('Photo uploaded successfully and is pending admin approval.', 'success')
    return redirect(url_for('staff.staff_edit_trek', id=id))
