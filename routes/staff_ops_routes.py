from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session
from datetime import date
from models import (db, User, Trek, Booking, Itinerary,
                    DebriefReport, StaffAvailability)
from .utils import login_required, role_required

staff_ops_bp = Blueprint('staff_ops', __name__, url_prefix='/staff')


# =========================================================
# Post-Trek Debrief Report
# =========================================================
@staff_ops_bp.route('/trek/<int:id>/debrief', methods=['GET', 'POST'])
@login_required
@role_required('staff')
def debrief(id):
    """Staff submits post-trek feedback."""
    trek = db.session.get(Trek, id) or abort(404)
    if trek.assigned_staff_id != session['user_id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('staff.staff_dashboard'))

    if request.method == 'POST':
        trail = request.form.get('trail_conditions', '').strip()
        weather = request.form.get('weather_report', '').strip()
        feedback = request.form.get('general_feedback', '').strip()

        if not trail and not weather and not feedback:
            flash('Please fill in at least one field.', 'danger')
            return redirect(url_for('staff_ops.debrief', id=id))

        report = DebriefReport(
            trek_id=trek.id,
            staff_id=session['user_id'],
            trail_conditions=trail or None,
            weather_report=weather or None,
            general_feedback=feedback or None
        )
        db.session.add(report)
        db.session.commit()
        flash('Debrief report submitted. Thank you!', 'success')
        return redirect(url_for('staff_ops.debrief', id=id))

    reports = DebriefReport.query.filter_by(trek_id=trek.id).order_by(DebriefReport.created_at.desc()).all()
    return render_template('staff/debrief.html', trek=trek, reports=reports)


# =========================================================
# Feature #17: Daily Itinerary Checklist
# =========================================================
@staff_ops_bp.route('/trek/<int:id>/checklist', methods=['GET', 'POST'])
@login_required
@role_required('staff')
def checklist(id):
    """Staff marks itinerary days as completed."""
    trek = db.session.get(Trek, id) or abort(404)
    if trek.assigned_staff_id != session['user_id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('staff.staff_dashboard'))

    if request.method == 'POST':
        itinerary_id = request.form.get('itinerary_id', type=int)
        action = request.form.get('action', 'complete')
        item = db.session.get(Itinerary, itinerary_id)
        if item and item.trek_id == trek.id:
            item.is_completed = (action == 'complete')
            db.session.commit()
            status = 'completed' if item.is_completed else 'reset'
            flash(f'Day {item.day_number} marked as {status}.', 'success')
        return redirect(url_for('staff_ops.checklist', id=id))

    items = Itinerary.query.filter_by(trek_id=trek.id, is_approved=True).order_by(Itinerary.day_number).all()
    completed_count = sum(1 for i in items if i.is_completed)
    return render_template('staff/checklist.html', trek=trek, items=items,
                           completed_count=completed_count, total_count=len(items))


# =========================================================
# Feature #18: Equipment & Gear Checklist
# =========================================================
@staff_ops_bp.route('/trek/<int:id>/gear-check', methods=['GET', 'POST'])
@login_required
@role_required('staff')
def gear_check(id):
    """Staff verifies mandatory group gear before departure."""
    trek = db.session.get(Trek, id) or abort(404)
    if trek.assigned_staff_id != session['user_id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('staff.staff_dashboard'))

    default_gear = [
        'First Aid Kit', 'Emergency Shelter/Tarp', 'Rope (50m)', 'Navigation (Map + Compass)',
        'Headlamps (group)', 'Water Purification Tablets', 'Emergency Rations',
        'Communication Device (Walkie-Talkie/Satellite Phone)', 'Fire Starting Kit',
        'Multi-tool/Knife', 'Group Tents', 'Sleeping Bags', 'Cooking Stove + Fuel',
        'Rain Gear / Ponchos', 'Waste Disposal Bags'
    ]

    if trek.gear_checklist:
        gear_items = [item.strip() for item in trek.gear_checklist.split('\n') if item.strip()]
    else:
        gear_items = default_gear

    if request.method == 'POST':
        checked_items = request.form.getlist('checked_gear')
        updated = []
        for item in gear_items:
            clean = item.lstrip('✓ ').strip()
            if clean in checked_items:
                updated.append(f'✓ {clean}')
            else:
                updated.append(clean)
        trek.gear_checklist = '\n'.join(updated)
        db.session.commit()
        flash('Gear checklist updated.', 'success')
        return redirect(url_for('staff_ops.gear_check', id=id))

    parsed_gear = []
    for item in gear_items:
        if item.startswith('✓ '):
            parsed_gear.append({'name': item[2:].strip(), 'checked': True})
        else:
            parsed_gear.append({'name': item.strip(), 'checked': False})

    checked_count = sum(1 for g in parsed_gear if g['checked'])
    return render_template('staff/gear_check.html', trek=trek, gear_items=parsed_gear,
                           checked_count=checked_count, total_count=len(parsed_gear))


# =========================================================
# Feature #19: Staff Availability Calendar
# =========================================================
@staff_ops_bp.route('/availability', methods=['GET', 'POST'])
@login_required
@role_required('staff')
def availability():
    """Staff blocks out dates when they're unavailable."""
    if request.method == 'POST':
        from datetime import datetime
        from_str = request.form.get('from_date', '').strip()
        to_str = request.form.get('to_date', '').strip()
        reason = request.form.get('reason', '').strip()

        if not from_str or not to_str:
            flash('Both dates are required.', 'danger')
            return redirect(url_for('staff_ops.availability'))

        try:
            from_date = datetime.strptime(from_str, '%Y-%m-%d').date()
            to_date = datetime.strptime(to_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('staff_ops.availability'))

        if to_date < from_date:
            flash('End date cannot be before start date.', 'danger')
            return redirect(url_for('staff_ops.availability'))

        block = StaffAvailability(
            staff_id=session['user_id'],
            unavailable_from=from_date,
            unavailable_to=to_date,
            reason=reason or None
        )
        db.session.add(block)
        db.session.commit()
        flash('Unavailability period added.', 'success')
        return redirect(url_for('staff_ops.availability'))

    blocks = StaffAvailability.query.filter_by(staff_id=session['user_id']).order_by(
        StaffAvailability.unavailable_from.desc()
    ).all()
    return render_template('staff/availability.html', blocks=blocks)


@staff_ops_bp.route('/availability/<int:id>/delete', methods=['POST'])
@login_required
@role_required('staff')
def delete_availability(id):
    block = db.session.get(StaffAvailability, id) or abort(404)
    if block.staff_id != session['user_id']:
        abort(403)
    db.session.delete(block)
    db.session.commit()
    flash('Availability block removed.', 'success')
    return redirect(url_for('staff_ops.availability'))


# =========================================================
# Feature #20: Local Connects Directory
# =========================================================
@staff_ops_bp.route('/trek/<int:id>/local-connects')
@login_required
@role_required('staff')
def local_connects(id):
    """View local emergency contacts, hospitals, transport near the trek."""
    trek = db.session.get(Trek, id) or abort(404)
    if trek.assigned_staff_id != session['user_id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('staff.staff_dashboard'))

    connects = []
    if trek.local_connects:
        for line in trek.local_connects.split('\n'):
            line = line.strip()
            if line:
                connects.append(line)

    return render_template('staff/local_connects.html', trek=trek, connects=connects)
