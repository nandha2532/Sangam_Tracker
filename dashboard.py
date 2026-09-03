import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import calendar
from database import supabase, fetch_table, clear_db_cache
from calculations import generate_emi_schedule

def render_dashboard(members_df, member_dict, global_target_date):
    st.markdown("<h1 style='color:#34D399;'>📱 Sangam Daily Operations</h1>", unsafe_allow_html=True)    
    savings = fetch_table("savings_log")
    loans = fetch_table("loans")
    emis_all = fetch_table("emi_ledger")
    
    total_savings = float(savings['amount'].sum()) if not savings.empty else 0
    total_loans_given = float(loans['total_amount'].sum()) if not loans.empty else 0
    pending_emis = emis_all[emis_all['status'].isin(['Pending', 'Partial'])] if not emis_all.empty else pd.DataFrame()
    
    # Calculate true pending total by subtracting what's already paid
    pending_total = 0
    if not pending_emis.empty:
        total_exp = float(pending_emis['total_expected'].sum())
        total_pd = float(pending_emis['paid_cash'].sum() + pending_emis['paid_online'].sum())
        pending_total = total_exp - total_pd
    
    # 1. TOP METRICS 
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card card-green'><div class='card-title'>Total Pool Collected</div><div class='card-value'>₹{total_savings:,.0f}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card card-purple'><div class='card-title'>Total Disbursed</div><div class='card-value'>₹{total_loans_given:,.0f}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card card-red'><div class='card-title'>Outstanding EMIs (All Time)</div><div class='card-value'>₹{pending_total:,.0f}</div></div>", unsafe_allow_html=True)

    # 2. ACTION HUB
    st.markdown("<div class='section-header'>⚡ Quick Actions Hub</div>", unsafe_allow_html=True)
    
    with st.expander("💸 Issue New Manual Loan", expanded=False):
        if member_dict:
            with st.form("issue_loan_form"):
                col_a, col_b = st.columns(2)
                l_member = col_a.selectbox("Recipient", list(member_dict.keys()))
                
                l_amount = col_b.number_input("Total Loan Amount (₹)", min_value=1000, step=500)
                l_part = col_a.number_input("Initial Part-Payment (₹)", min_value=0, max_value=int(l_amount), step=100)
                l_dur = col_b.number_input("Duration (Months)", min_value=1, value=5, step=1)
                l_date = st.date_input("Start Date")
                
                if st.form_submit_button("✅ Issue Loan & Generate EMIs"):
                    loan_response = supabase.table("loans").insert({
                        "target_member_id": int(member_dict[l_member]),
                        "total_amount": float(l_amount),
                        "part_payment_initial": float(l_part),
                        "duration_months": int(l_dur),
                        "created_at": l_date.strftime("%Y-%m-%d")
                    }).execute()
                    
                    if loan_response.data:
                        new_loan_id = loan_response.data[0]['id']
                        schedule_df = generate_emi_schedule(new_loan_id, float(l_amount), float(l_part), int(l_dur), l_date)
                        schedule_df['member_id'] = int(member_dict[l_member])
                        
                        supabase.table("emi_ledger").insert(schedule_df.to_dict('records')).execute()
                        clear_db_cache()
                        st.toast("✅ Loan processed and EMI matrix generated!", icon="🎉")
                        st.rerun()

    # 3. MONTHLY EMI MATRIX (Executive Viewer)
    st.markdown("<br><div class='section-header'>📅 Monthly EMI Matrix</div>", unsafe_allow_html=True)
    
    if not emis_all.empty:
        emis_all['pay_date'] = pd.to_datetime(emis_all['pay_date'])
        
        # --- GLOBAL CALENDAR SYNC ---
        selected_year = global_target_date.year
        selected_month = global_target_date.month
        selected_month_name = calendar.month_name[selected_month]
        
        # st.info(f"🗓️ Viewing EMIs scheduled for: **{selected_month_name} {selected_year}** (Synced with Sidebar)")
        
        matrix_df = emis_all[(emis_all['pay_date'].dt.year == selected_year) & (emis_all['pay_date'].dt.month == selected_month)].copy()
        
        if not matrix_df.empty:
            matrix_df = pd.merge(matrix_df, members_df[['id', 'name']], left_on='member_id', right_on='id', how='left')
            
            # Compute actual paid vs balance
            matrix_df['paid_cash'] = matrix_df['paid_cash'].fillna(0).astype(float)
            matrix_df['paid_online'] = matrix_df['paid_online'].fillna(0).astype(float)
            matrix_df['TOTAL PAID'] = matrix_df['paid_cash'] + matrix_df['paid_online']
            matrix_df['BALANCE'] = matrix_df['total_expected'].astype(float) - matrix_df['TOTAL PAID']
            
            display_matrix = matrix_df[['emi_number', 'name', 'total_expected', 'TOTAL PAID', 'BALANCE', 'status']]
            display_matrix.columns = ['EMI NO.', 'NAME', 'EXPECTED', 'PAID', 'BALANCE DUE', 'STATUS']
            display_matrix = display_matrix.sort_values(by='EMI NO.', ascending=False)
            
            collected_total = display_matrix['PAID'].sum()
            expected_total = display_matrix['EXPECTED'].sum()
            remaining_total = display_matrix['BALANCE DUE'].sum()
            
            st.markdown("<br>", unsafe_allow_html=True)
            m1, m2, m3 = st.columns([1, 1, 1])
            m1.metric("🎯 Total Expected", f"₹{expected_total:,.0f}")
            m2.metric("✅ Total Collected", f"₹{collected_total:,.0f}")
            m3.metric("⏳ Total Remaining", f"₹{remaining_total:,.0f}")
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Dynamic styling for Paid (Green) and Partial (Yellow)
            def style_excel(row):
                if row['STATUS'] == 'Paid':
                    return ['background-color: #18201D; color: #22C55E; font-weight: bold'] * len(row)
                elif row['STATUS'] == 'Partial':
                    return ['background-color: #121817; color: #F59E0B'] * len(row) # Pending Color
                return [''] * len(row)
                
            format_matrix = {'EXPECTED': '₹{:,.0f}', 'PAID': '₹{:,.0f}', 'BALANCE DUE': '₹{:,.0f}'}
            st.dataframe(display_matrix.style.format(format_matrix).apply(style_excel, axis=1), hide_index=True, use_container_width=True)
            
            st.caption("ℹ️ Note: Payments must be logged through the **Collection Desk** to ensure accurate cash/online audit tracking.")
        else:
            st.info(f"No EMIs scheduled for {selected_month_name} {selected_year}.")
    else:
        st.info("No EMIs have been generated yet.")