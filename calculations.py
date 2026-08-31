import pandas as pd
import numpy as np
from datetime import datetime

def generate_emi_schedule(loan_id, total_amount, part_payment, duration, start_date):
    """
    Generates the amortization schedule.
    Rule: First month interest is on the full total_amount. Principal is reduced by part_payment.
    """
    schedule = []
    reduced_principal = total_amount - part_payment
    monthly_principal = reduced_principal / duration
    monthly_rate = 0.02  # 24% p.a. -> 2% per month
    
    current_outstanding = total_amount # Used only for the first month's interest
    
    for month in range(1, duration + 1):
        # Calculate interest
        if month == 1:
            interest = current_outstanding * monthly_rate
            current_outstanding = reduced_principal # Drop the outstanding for month 2 onwards
        else:
            interest = current_outstanding * monthly_rate
            
        total_due = monthly_principal + interest
        
        # Calculate due date
        try:
            m = start_date.month + month
            y = start_date.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            due_date = start_date.replace(year=y, month=m)
        except ValueError:
            # Handle edge cases like Feb 29
            due_date = datetime(y, m, 28).date()
            
        schedule.append({
            "loan_id": loan_id,
            "emi_number": month,
            "principal_due": monthly_principal,
            "interest_due": interest,
            "total_expected": total_due,
            "pay_date": due_date.strftime("%Y-%m-%d"),
            "status": 'Pending'
        })
        
        # Reduce outstanding for the next loop's interest calculation
        current_outstanding -= monthly_principal
        
    return pd.DataFrame(schedule)

def calculate_sub_loan_liability(amount_taken, duration_months, start_date):
    """
    Generates the exact EMI schedule for a sub-borrower.
    They pay 0 part-payment, so the principal is cleanly divided by the duration.
    """
    schedule = []
    monthly_principal = amount_taken / duration_months
    monthly_rate = 0.02  # 24% p.a.
    current_outstanding = amount_taken 

    for month in range(1, duration_months + 1):
        interest = current_outstanding * monthly_rate
        total_due = monthly_principal + interest
        
        # Match the exact due date of the master loan
        m = start_date.month + month
        y = start_date.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        due_date = start_date.replace(year=y, month=m)
            
        schedule.append({
            "emi_number": month,
            "principal_due": monthly_principal,
            "interest_due": interest,
            "total_expected": total_due,
            "pay_date": due_date.strftime("%Y-%m-%d")
        })
        
        current_outstanding -= monthly_principal
        
    return pd.DataFrame(schedule)