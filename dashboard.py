import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import calendar
from database import supabase, fetch_table, clear_db_cache
from calculations import generate_emi_schedule

def render_dashboard(members_df, member_dict):
    st.markdown("<h1 style='color:#2c3e50;'>Sangam Daily Operations</h1>", unsafe_allow_html=True)
    
    savings = fetch_table("savings_log")
    loans = fetch_table("loans")
    emis_all = fetch_table("emi_ledger")
    
    total_savings = float(savings['amount'].sum()) if not savings.empty else 0
    total_loans_given = float(loans['total_amount'].sum()) if not loans.empty else 0
    pending_emis = emis_all[emis_all['status'] == 'Pending'] if not emis_all.empty else pd.DataFrame()
    pending_total = float(pending_emis['total_expected'].sum()) if not pending_emis.empty else 0
    
    # 1. TOP METRICS (Fixed: Removed decimals)
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card card-green'><div class='card-title'>Total Pool Collected</div><div class='card-value'>₹{total_savings:,.0f}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card card-purple'><div class='card-title'>Total Disbursed</div><div class='card-value'>₹{total_loans_given:,.0f}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card card-red'><div class='card-title'>Outstanding EMIs</div><div class='card-value'>₹{pending_total:,.0f}</div></div>", unsafe_allow_html=True)

    # 2. ACTION HUB
    st.markdown("<div class='section-header'>⚡ Quick Actions Hub</div>", unsafe_allow_html=True)
    
    with st.expander("💸 Issue New Manual Loan", expanded=False):
        if member_dict:
            with st.form("issue_loan_form"):
                col_a, col_b = st.columns(2)
                l_member = col_a.selectbox("Recipient", list(member_dict.keys()))
                
                # FIXED: Force integer bounds
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

    # 3. MONTHLY EMI MATRIX & PAYMENT HUB
    st.markdown("<br><div class='section-header'>📅 Monthly EMI Matrix</div>", unsafe_allow_html=True)
    
    if not emis_all.empty:
        emis_all['pay_date'] = pd.to_datetime(emis_all['pay_date'])
        today = datetime.today().date()
        
        col_y, col_m = st.columns(2)
        available_years = sorted(emis_all['pay_date'].dt.year.dropna().unique().tolist())
        current_year = today.year if today.year in available_years else (available_years[-1] if available_years else today.year)
        selected_year = col_y.selectbox("Filter by Year", available_years, index=available_years.index(current_year) if current_year in available_years else 0)
        
        months_in_year = sorted(emis_all[emis_all['pay_date'].dt.year == selected_year]['pay_date'].dt.month.dropna().unique().tolist())
        current_month = today.month if today.month in months_in_year else (months_in_year[0] if months_in_year else today.month)
        
        month_labels = [calendar.month_name[int(m)] for m in months_in_year]
        selected_month_name = col_m.selectbox("Filter by Month", month_labels, index=months_in_year.index(current_month) if current_month in months_in_year else 0)
        selected_month = list(calendar.month_name).index(selected_month_name)
        
        matrix_df = emis_all[(emis_all['pay_date'].dt.year == selected_year) & (emis_all['pay_date'].dt.month == selected_month)]
        
        if not matrix_df.empty:
            matrix_df = pd.merge(matrix_df, members_df[['id', 'name']], left_on='member_id', right_on='id', how='left')
            
            display_matrix = matrix_df[['emi_number', 'name', 'principal_due', 'interest_due', 'total_expected', 'status', 'id_x']]
            display_matrix.columns = ['CURRENT EMI', 'NAME', 'PRINCIPAL', 'INTEREST', 'TOTAL', 'Status', 'emi_id']
            display_matrix = display_matrix.sort_values(by='CURRENT EMI', ascending=False)
            
            # --- NEW FEATURE: DYNAMIC MONTHLY TOTALS ---
            collected_total = display_matrix[display_matrix['Status'] == 'Paid']['TOTAL'].sum()
            expected_total = display_matrix['TOTAL'].sum()
            
            st.markdown("<br>", unsafe_allow_html=True)
            m1, m2, _ = st.columns([1, 1, 2])
            m1.metric("✅ Total Collected", f"₹{collected_total:,.0f}")
            m2.metric("🎯 Total Expected", f"₹{expected_total:,.0f}")
            st.markdown("<br>", unsafe_allow_html=True)
            # -------------------------------------------
            
            def style_excel(row):
                if row['Status'] == 'Paid':
                    return ['background-color: #d1f2eb; color: #145a32'] * len(row)
                return [''] * len(row)
                
            format_matrix = {'PRINCIPAL': '₹{:,.0f}', 'INTEREST': '₹{:,.0f}', 'TOTAL': '₹{:,.0f}'}
            st.dataframe(display_matrix[['CURRENT EMI', 'NAME', 'PRINCIPAL', 'INTEREST', 'TOTAL', 'Status']].style.format(format_matrix).apply(style_excel, axis=1), hide_index=True, use_container_width=True)
            
            st.markdown("<br><div class='section-header'>✔️ Process Pending EMIs</div>", unsafe_allow_html=True)
            pending_this_month = display_matrix[display_matrix['Status'] == 'Pending']
            
            if not pending_this_month.empty:
                for _, row in pending_this_month.iterrows():
                    with st.form(f"pay_emi_{row['emi_id']}"):
                        st.write(f"**{row['NAME']}** | EMI {row['CURRENT EMI']} | Due: ₹{row['TOTAL']:,.0f}")
                        if st.form_submit_button("Mark as Paid"):
                            supabase.table("emi_ledger").update({"status": 'Paid'}).eq("id", int(row['emi_id'])).execute()
                            clear_db_cache()
                            st.rerun()
            else:
                st.success(f"All EMIs for {selected_month_name} {selected_year} have been cleared! 🎉")
        else:
            st.info(f"No EMIs scheduled for {selected_month_name} {selected_year}.")
    else:
        st.info("No EMIs have been generated yet.")