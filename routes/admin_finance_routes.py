import csv
import io
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, Response
from datetime import datetime, date
from sqlalchemy import func
from models import (db, User, Trek, Booking, Expense, StaffPayout)
from .utils import login_required, role_required

admin_finance_bp = Blueprint('admin_finance', __name__, url_prefix='/admin')


# =========================================================
# Feature #1: Financial Profit/Loss Dashboard
# =========================================================
@admin_finance_bp.route('/financials')
@login_required
@role_required('admin')
def financials():
    """Per-trek financial breakdown: Revenue - Expenses - Staff Payouts = Net P&L."""
    treks = Trek.query.order_by(Trek.id.desc()).all()
    financials_data = []

    grand_revenue = 0.0
    grand_expenses = 0.0
    grand_payouts = 0.0

    for trek in treks:
        revenue = db.session.query(func.sum(Booking.total_price)).filter(
            Booking.trek_id == trek.id,
            Booking.status.in_(['Booked', 'Completed'])
        ).scalar() or 0.0

        expenses = db.session.query(func.sum(Expense.amount)).filter(
            Expense.trek_id == trek.id,
            Expense.status.in_(['Approved', 'Paid'])
        ).scalar() or 0.0

        payouts = db.session.query(func.sum(StaffPayout.calculated_amount)).filter(
            StaffPayout.trek_id == trek.id
        ).scalar() or 0.0

        net = revenue - expenses - payouts
        booking_count = Booking.query.filter(
            Booking.trek_id == trek.id,
            Booking.status.in_(['Booked', 'Completed'])
        ).count()

        grand_revenue += revenue
        grand_expenses += expenses
        grand_payouts += payouts

        financials_data.append({
            'trek': trek,
            'revenue': revenue,
            'expenses': expenses,
            'payouts': payouts,
            'net': net,
            'booking_count': booking_count,
        })

    return render_template('admin/financials.html',
        financials_data=financials_data,
        grand_revenue=grand_revenue,
        grand_expenses=grand_expenses,
        grand_payouts=grand_payouts,
        grand_net=grand_revenue - grand_expenses - grand_payouts)


# =========================================================
# Feature #9: Export Financials CSV
# =========================================================
@admin_finance_bp.route('/financials/export')
@login_required
@role_required('admin')
def export_financials():
    """Download financial data as CSV."""
    treks = Trek.query.order_by(Trek.id).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Trek ID', 'Trek Name', 'Location', 'Status', 'Bookings', 'Revenue (₹)',
                      'Expenses (₹)', 'Staff Payouts (₹)', 'Net P&L (₹)'])

    for trek in treks:
        revenue = db.session.query(func.sum(Booking.total_price)).filter(
            Booking.trek_id == trek.id,
            Booking.status.in_(['Booked', 'Completed'])
        ).scalar() or 0.0
        expenses = db.session.query(func.sum(Expense.amount)).filter(
            Expense.trek_id == trek.id,
            Expense.status.in_(['Approved', 'Paid'])
        ).scalar() or 0.0
        payouts = db.session.query(func.sum(StaffPayout.calculated_amount)).filter(
            StaffPayout.trek_id == trek.id
        ).scalar() or 0.0
        booking_count = Booking.query.filter(
            Booking.trek_id == trek.id,
            Booking.status.in_(['Booked', 'Completed'])
        ).count()
        net = revenue - expenses - payouts
        writer.writerow([trek.id, trek.name, trek.location, trek.status, booking_count,
                          f'{revenue:.2f}', f'{expenses:.2f}', f'{payouts:.2f}', f'{net:.2f}'])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=financials_{date.today().isoformat()}.csv'}
    )


# =========================================================
# Feature #10: Monthly Staff Payout Report
# =========================================================
@admin_finance_bp.route('/payouts')
@login_required
@role_required('admin')
def payouts():
    """Monthly staff payout summary."""
    month = request.args.get('month', type=int, default=date.today().month)
    year = request.args.get('year', type=int, default=date.today().year)

    staff_users = User.query.filter_by(role='staff', status='active').all()
    payout_data = []

    for staff in staff_users:
        completed_treks = Trek.query.filter(
            Trek.assigned_staff_id == staff.id,
            Trek.status == 'Completed',
            db.extract('month', Trek.end_date) == month,
            db.extract('year', Trek.end_date) == year,
        ).all()

        total_payout = 0.0
        total_expenses_reimbursed = 0.0
        trek_details = []

        for trek in completed_treks:
            revenue = db.session.query(func.sum(Booking.total_price)).filter(
                Booking.trek_id == trek.id,
                Booking.status.in_(['Booked', 'Completed'])
            ).scalar() or 0.0

            if trek.staff_flat_salary:
                payout = trek.staff_flat_salary
            else:
                payout = revenue * (trek.staff_commission_pct / 100.0)

            expenses = db.session.query(func.sum(Expense.amount)).filter(
                Expense.trek_id == trek.id,
                Expense.staff_id == staff.id,
                Expense.status.in_(['Approved', 'Paid'])
            ).scalar() or 0.0

            total_payout += payout
            total_expenses_reimbursed += expenses
            trek_details.append({
                'trek': trek,
                'revenue': revenue,
                'payout': payout,
                'expenses': expenses,
            })

        if completed_treks or total_payout > 0:
            payout_data.append({
                'staff': staff,
                'profile': staff.staff_profile,
                'completed_count': len(completed_treks),
                'treks': trek_details,
                'total_payout': total_payout,
                'total_expenses': total_expenses_reimbursed,
                'net_payable': total_payout + total_expenses_reimbursed,
            })

    return render_template('admin/payouts.html',
        payout_data=payout_data, month=month, year=year)


# =========================================================
# Expense approval routes
# =========================================================
@admin_finance_bp.route('/expense/<int:id>/approve', methods=['POST'])
@login_required
@role_required('admin')
def approve_expense(id):
    expense = db.session.get(Expense, id) or abort(404)
    expense.status = 'Approved'
    db.session.commit()
    flash('Expense approved.', 'success')
    return redirect(request.referrer or url_for('admin_finance.financials'))


@admin_finance_bp.route('/expense/<int:id>/reject', methods=['POST'])
@login_required
@role_required('admin')
def reject_expense(id):
    expense = db.session.get(Expense, id) or abort(404)
    expense.status = 'Rejected'
    db.session.commit()
    flash('Expense rejected.', 'info')
    return redirect(request.referrer or url_for('admin_finance.financials'))


@admin_finance_bp.route('/expense/<int:id>/mark-paid', methods=['POST'])
@login_required
@role_required('admin')
def mark_expense_paid(id):
    expense = db.session.get(Expense, id) or abort(404)
    expense.status = 'Paid'
    db.session.commit()
    flash('Expense marked as paid.', 'success')
    return redirect(request.referrer or url_for('admin_finance.financials'))
