import streamlit as st
import pandas as pd
import calendar
from datetime import datetime
from database import supabase, fetch_table

def render_dashboard(members_df, member_dict, global_target_date):
    st.markdown("<h1 style='color:#34D399;'>📱 Sangam Daily Operations</h1>", unsafe_allow_html=True)
    
    # Initialize Manual Adjustment State 
    if "manual_balance_adj" not in st.session_state:
        st.session_state["manual_balance_adj"] = 216.0
        
    # Fetch Data
    loans_df = fetch_table("loans")
    emis_df = fetch_table("emi_ledger")
    savings_df = fetch_table("savings_log")
    receipts_df = fetch_table("payment_receipts")
    
    target_year = global_target_date.year
    target_month = global_target_date.month
    selected_month_name = calendar.month_name[target_month]
    
    # ==========================================
    # PRE-CALCULATE GLOBAL & MONTHLY DATA
    # ==========================================
    
    # 1. Treasury / Available Balance
    total_receipts_all_time = receipts_df['amount_cash'].sum() + receipts_df['amount_online'].sum() if not receipts_df.empty else 0.0
    final_balance_as_of_now = st.session_state["manual_balance_adj"] + total_receipts_all_time

    # 2. Monthly Collections
    monthly_collected_savings = 0.0
    monthly_collected_emi = 0.0
    
    if not receipts_df.empty:
        receipts_df['logged_at'] = pd.to_datetime(receipts_df['logged_at'])
        this_month_receipts = receipts_df[(receipts_df['logged_at'].dt.month == target_month) & 
                                          (receipts_df['logged_at'].dt.year == target_year)]
        
        savings_receipts = this_month_receipts[this_month_receipts['payment_type'] == 'Savings']
        emi_receipts = this_month_receipts[this_month_receipts['payment_type'] != 'Savings']
        
        monthly_collected_savings = savings_receipts['amount_cash'].sum() + savings_receipts['amount_online'].sum()
        monthly_collected_emi = emi_receipts['amount_cash'].sum() + emi_receipts['amount_online'].sum()

    # 3. Monthly Expected
    total_active_members = len(members_df)
    expected_savings_this_month = total_active_members * 500.0
    expected_emis_this_month = 0.0
    matrix_data = []
    
    if not emis_df.empty:
        emis_df['pay_date'] = pd.to_datetime(emis_df['pay_date'])
        this_month_emis = emis_df[(emis_df['pay_date'].dt.month == target_month) & 
                                  (emis_df['pay_date'].dt.year == target_year)]
        
        for _, row in this_month_emis.iterrows():
            m_id = row['member_id']
            m_name = member_dict.get(m_id) if m_id in member_dict.values() else "Unknown"
            for name, id_val in member_dict.items():
                if id_val == m_id:
                    m_name = name
                    break
                    
            expected = float(row['total_expected'])
            paid = float(row.get('paid_cash', 0)) + float(row.get('paid_online', 0))
            balance = expected - paid
            expected_emis_this_month += expected
            
            matrix_data.append({
                "EMI NO.": row['emi_number'],
                "NAME": m_name,
                "EXPECTED EMI": expected,
                "PAID EMI": paid,
                "BALANCE DUE": balance,
                "STATUS": row['status']
            })

    pending_emis_this_month = expected_emis_this_month - monthly_collected_emi
    pending_savings_this_month = expected_savings_this_month - monthly_collected_savings

    # ==========================================
    # UI SECTION 1: MONTHLY CASH FLOW & TREASURY
    # ==========================================
    st.markdown(f"### 🏦 Monthly Cash Flow & Treasury ({selected_month_name} {target_year})")
    st.markdown("<p style='color: #94A3A0; font-size: 0.9rem;'>Track live collections and available lending capacity.</p>", unsafe_allow_html=True)
    
    # ROW 1: Treasury Balance
    tc1, tc2, tc3 = st.columns([1, 1, 1])
    with tc1:
        new_adj = st.number_input("Manual Adjustment / Opening Balance (₹)", value=float(st.session_state["manual_balance_adj"]), step=1.0)
        if new_adj != st.session_state["manual_balance_adj"]:
            st.session_state["manual_balance_adj"] = new_adj
            st.rerun()

    tc2.metric("Total Available to Lend", f"₹{final_balance_as_of_now:,.0f}")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ROW 2: Loan EMI Flow
    st.markdown("#### 🔵 Loan EMI Flow")
    ec1, ec2, ec3 = st.columns(3)
    ec1.metric("🎯 Expected EMI", f"₹{expected_emis_this_month:,.0f}")
    ec2.metric("✅ Collected EMI", f"₹{monthly_collected_emi:,.0f}")
    ec3.metric("⏳ Pending EMI", f"₹{pending_emis_this_month:,.0f}")

    # ROW 3: Savings Flow
    st.markdown("#### 🟢 Savings Flow")
    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("🎯 Expected Savings", f"₹{expected_savings_this_month:,.0f}")
    sc2.metric("✅ Collected Savings", f"₹{monthly_collected_savings:,.0f}")
    sc3.metric("⏳ Pending Savings", f"₹{pending_savings_this_month:,.0f}")

    st.divider()

    # ==========================================
    # UI SECTION 2: QUICK ACTIONS HUB
    # ==========================================
    st.markdown("### ⚡ Quick Actions Hub")
    with st.expander("Issue New Manual Loan", expanded=False):
        with st.form("new_loan_form"):
            st.markdown("#### 📝 Loan Details")
            l_c1, l_c2 = st.columns(2)
            
            with l_c1:
                selected_member = st.selectbox("Target Member", options=["-- Select --"] + list(member_dict.keys()))
                loan_amt = st.number_input("Total Loan Amount (₹)", min_value=0.0, step=1000.0)
                part_pay = st.number_input("Initial Part Payment / Upfront (₹)", min_value=0.0, step=100.0)
                
            with l_c2:
                duration_m = st.number_input("Duration (Months)", min_value=1, step=1, value=5)
                first_emi_date = st.date_input("First EMI Date", global_target_date)
                
            submit_loan = st.form_submit_button("💸 Confirm & Issue New Loan", type="primary", use_container_width=True)
            
            if submit_loan:
                if selected_member == "-- Select --":
                    st.error("Please select a member first.")
                elif loan_amt <= 0:
                    st.error("Loan amount must be greater than 0.")
                else:
                    m_id = member_dict[selected_member]
                    true_principal = loan_amt - part_pay
                    emi_expected = true_principal / duration_m
                    
                    # 1. Insert Loan into database
                    loan_data = {
                        "target_member_id": m_id,
                        "total_amount": loan_amt,
                        "part_payment_initial": part_pay,
                        "duration_months": duration_m,
                        "active_status": True
                    }
                    res = supabase.table("loans").insert(loan_data).execute()
                    
                    if res.data:
                        new_loan_id = res.data[0]['id']
                        
                        # 2. Generate the EMI Schedule Automatically
                        emis = []
                        for i in range(1, int(duration_m) + 1):
                            next_date = (pd.to_datetime(first_emi_date) + pd.DateOffset(months=i-1)).strftime('%Y-%m-%d')
                            emis.append({
                                "loan_id": new_loan_id,
                                "member_id": m_id,
                                "emi_number": i,
                                "total_expected": emi_expected,
                                "pay_date": next_date,
                                "status": "Pending",
                                "paid_cash": 0.0,
                                "paid_online": 0.0
                            })
                        supabase.table("emi_ledger").insert(emis).execute()
                        
                        # 3. Auto-Deduct from Treasury Balance
                        # We log this as a negative cash receipt so it perfectly reduces your "Available to Lend" balance
                        supabase.table("payment_receipts").insert({
                            "member_id": m_id,
                            "payment_type": f"Loan Disbursement (Loan #{new_loan_id})",
                            "amount_cash": -true_principal, 
                            "amount_online": 0,
                            "logged_at": global_target_date.strftime('%Y-%m-%d')
                        }).execute()
                        
                        st.success(f"✅ Loan #{new_loan_id} successfully issued to {selected_member}!")
                        
                        # Clear cache and refresh to update all dashboard numbers instantly
                        from database import clear_db_cache
                        clear_db_cache()
                        st.rerun()

    st.divider()

    # ==========================================
    # UI SECTION 3: MONTHLY EMI MATRIX
    # ==========================================
    st.markdown(f"### 🗓️ Monthly EMI Matrix ({selected_month_name} {target_year})")
    
    if matrix_data:
        df_matrix = pd.DataFrame(matrix_data)
        
        def style_matrix(row):
            if row['STATUS'] == 'Paid':
                return ['background-color: #18201D; color: #22C55E; font-weight: bold'] * len(row)
            elif row['STATUS'] == 'Partial':
                return ['background-color: #121817; color: #F59E0B'] * len(row)
            return [''] * len(row)
            
        styled_df = df_matrix.style.apply(style_matrix, axis=1).format({
            "EXPECTED EMI": "₹{:,.0f}",
            "PAID EMI": "₹{:,.0f}",
            "BALANCE DUE": "₹{:,.0f}"
        })
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.info(f"No EMIs scheduled for {selected_month_name} {target_year}.")

    st.divider()

   # ==========================================
    # UI SECTION 4: GLOBAL PORTFOLIO OVERVIEW
    # ==========================================
    st.markdown("### 🌍 Global Portfolio & All-Time Stats")
    
    total_disbursed = loans_df['total_amount'].sum() if not loans_df.empty else 0.0
    outstanding_emis = 0.0
    total_outstanding_principal = 0.0
    
    if not emis_df.empty and not loans_df.empty:
        # Calculate Outstanding EMIs
        pending_emis = emis_df[emis_df['status'] != 'Paid']
        for _, row in pending_emis.iterrows():
            expected = float(row['total_expected'])
            paid = float(row.get('paid_cash', 0)) + float(row.get('paid_online', 0))
            outstanding_emis += (expected - paid)
            
        # Calculate Total Outstanding Principal (Accounting for Part Payments)
        for _, loan in loans_df.iterrows():
            l_id = loan['id']
            
            # 1. Get raw amounts
            total_amt = float(loan['total_amount'])
            part_payment = float(loan.get('part_payment_initial', 0.0))
            
            # 2. Find the TRUE principal that was distributed into EMIs
            true_principal = total_amt - part_payment
            
            # 3. Calculate how much principal is in each EMI
            duration = int(loan['duration_months']) if int(loan['duration_months']) > 0 else 1
            principal_per_month = true_principal / duration
            
            # 4. Multiply by the number of unpaid EMIs
            unpaid_emis_for_loan = emis_df[(emis_df['loan_id'] == l_id) & (emis_df['status'] != 'Paid')]
            unpaid_count = len(unpaid_emis_for_loan)
            
            total_outstanding_principal += (principal_per_month * unpaid_count)
                
    gc1, gc2, gc3 = st.columns(3)
    gc1.metric("Total Outstanding Principal", f"₹{total_outstanding_principal:,.0f}")
    gc2.metric("Outstanding EMIs (All Time)", f"₹{outstanding_emis:,.0f}")
    gc3.metric("Total Disbursed", f"₹{total_disbursed:,.0f}")
                