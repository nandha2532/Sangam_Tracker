import streamlit as st
import pandas as pd
from datetime import datetime
import calendar
from database import supabase, fetch_table, clear_db_cache

def calculate_sub_loan_month(amount_taken, duration_months, start_date_str, target_date):
    try:
        start_date = pd.to_datetime(start_date_str).date()
    except Exception:
        return None
        
    month_index = (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month)
    
    if month_index < 1 or month_index > duration_months:
        return None
        
    monthly_principal = amount_taken / duration_months
    monthly_rate = 0.02
    
    current_outstanding = amount_taken - (monthly_principal * (month_index - 1))
    interest = current_outstanding * monthly_rate
    
    return {
        "emi_number": month_index,
        "principal_due": monthly_principal,
        "interest_due": interest,
        "total_due": monthly_principal + interest
    }

def render_settlement(members_df, member_dict, global_target_date):
    st.markdown("<h1 style='color:#34D399;'>🤝 Settlement & Shadow Ledger</h1>", unsafe_allow_html=True)
    st.write("Track pass-through liabilities and calculate exact 'Bring to Meeting' cash totals.")
    
    loans_df = fetch_table("loans")
    settlements_df = fetch_table("individual_settlement")
    emis_df = fetch_table("emi_ledger")
    
    if loans_df.empty or members_df.empty:
        st.warning("Please ensure active members and loans exist before using the settlement ledger.")
        return

    id_to_name = dict(zip(members_df['id'], members_df['name']))
    
    # ==========================================
    # 1. THE SUB-LOAN ASSIGNER & MANAGER
    # ==========================================
    st.markdown("<div class='section-header'>📝 Log & Manage Sub-Loans (Unofficial Splits)</div>", unsafe_allow_html=True)
    
    col_l1, col_l2 = st.columns(2)
    
    with col_l1:
        with st.expander("➕ Assign funds from a Master Loan", expanded=False):
            with st.form("add_sub_loan_form"):
                active_loans = loans_df[loans_df['active_status'] == True]
                loan_options = []
                loan_mapping = {}
                for _, row in active_loans.iterrows():
                    owner_name = id_to_name.get(row['target_member_id'], 'Unknown')
                    label = f"Loan #{row['id']} - {owner_name} (₹{row['total_amount']:,.0f})"
                    loan_options.append(label)
                    loan_mapping[label] = int(row['id'])
                    
                s_master = st.selectbox("Select Master Loan", loan_options)
                s_borrower = st.selectbox("Select Sub-Borrower", list(member_dict.keys()))
                s_amount = st.number_input("Amount Taken (₹)", min_value=100, step=500)
                
                if st.form_submit_button("💾 Lock Sub-Loan"):
                    master_loan_id = loan_mapping[s_master]
                    borrower_id = member_dict[s_borrower]
                    
                    supabase.table("individual_settlement").insert({
                        "master_loan_id": master_loan_id,
                        "sub_borrower_id": borrower_id,
                        "amount_taken": float(s_amount)
                    }).execute()
                    
                    clear_db_cache()
                    st.toast(f"✅ Sub-loan of ₹{s_amount} assigned to {s_borrower}!", icon="🤝")
                    st.rerun()

    with col_l2:
        with st.expander("⚙️ Manage Existing Splits", expanded=False):
            if not settlements_df.empty:
                split_options = []
                split_mapping = {}
                for _, row in settlements_df.iterrows():
                    sub_name = id_to_name.get(row['sub_borrower_id'], 'Unknown')
                    master_loan = loans_df[loans_df['id'] == row['master_loan_id']]
                    if not master_loan.empty:
                        master_name = id_to_name.get(master_loan.iloc[0]['target_member_id'], 'Unknown')
                        label = f"Split #{row['id']} - {sub_name} took ₹{row['amount_taken']:,.0f} from {master_name}'s Loan"
                    else:
                        label = f"Split #{row['id']} - {sub_name} took ₹{row['amount_taken']:,.0f}"
                        
                    split_options.append(label)
                    split_mapping[label] = int(row['id'])

                s_edit = st.selectbox("Select Split to Modify", ["-- Select --"] + split_options)

                if s_edit != "-- Select --":
                    target_id = split_mapping[s_edit]
                    target_row = settlements_df[settlements_df['id'] == target_id].iloc[0]

                    with st.form("edit_split_form"):
                        st.write("**Edit Split Amount**")
                        new_amount = st.number_input("Amount Taken (₹)", min_value=100, step=500, value=int(target_row['amount_taken']))
                        
                        c_a, c_b = st.columns(2)
                        if c_a.form_submit_button("💾 Update Amount"):
                            supabase.table("individual_settlement").update({"amount_taken": float(new_amount)}).eq("id", target_id).execute()
                            clear_db_cache()
                            st.toast(f"✅ Split updated successfully!", icon="💾")
                            st.rerun()
                            
                        if c_b.form_submit_button("🗑️ Delete Split"):
                            supabase.table("individual_settlement").delete().eq("id", target_id).execute()
                            clear_db_cache()
                            st.toast("✅ Split removed permanently!", icon="🗑️")
                            st.rerun()
            else:
                st.info("No unofficial splits have been created yet.")

    # ==========================================
    # 2. BRING TO MEETING MATRIX
    # ==========================================
    st.markdown("<br><div class='section-header'>📊 Individual Settlement Statement</div>", unsafe_allow_html=True)
    
    # --- GLOBAL CALENDAR SYNC ---
    selected_year = global_target_date.year
    selected_month = global_target_date.month
    selected_month_name = calendar.month_name[selected_month]
    target_date = datetime(selected_year, selected_month, 15).date()
    
    # st.info(f"🗓️ Generating Shadow Ledger for: **{selected_month_name} {selected_year}** (Synced with Sidebar)")
    
    selected_member_names = st.multiselect(
        "Target Member(s) [Select multiple to combine aliases]", 
        options=list(member_dict.keys())
    )
    
    if not selected_member_names:
        st.info("Please select at least one member to view their settlement statement.")
        return

    selected_member_ids = [member_dict[name] for name in selected_member_names]
    st.divider()
    
    # ------------------------------------------
    # TABLE A: LIABILITIES
    # ------------------------------------------
    st.subheader(f"🔴 Accounts Payable: What must be BROUGHT to the meeting")
    payables_data = []
    
    if not emis_df.empty:
        emis_df['pay_date'] = pd.to_datetime(emis_df['pay_date'])
        direct_emis = emis_df[(emis_df['member_id'].isin(selected_member_ids)) & 
                              (emis_df['pay_date'].dt.year == selected_year) & 
                              (emis_df['pay_date'].dt.month == selected_month)]
                              
        for _, row in direct_emis.iterrows():
            exact_ticket_name = id_to_name.get(row['member_id'], 'Unknown')
            payables_data.append({
                "Source": f"Direct Loan #{row['loan_id']}",
                "Belongs To": exact_ticket_name,
                "EMI No.": int(row['emi_number']),
                "Principal": float(row['principal_due']),
                "Interest": float(row['interest_due']),
                "Total To Pay": float(row['total_expected'])
            })
            
    if not settlements_df.empty:
        my_sub_loans = settlements_df[settlements_df['sub_borrower_id'].isin(selected_member_ids)]
        for _, sub in my_sub_loans.iterrows():
            exact_borrower_name = id_to_name.get(sub['sub_borrower_id'], 'Unknown')
            master_loan = loans_df[loans_df['id'] == sub['master_loan_id']].iloc[0]
            master_owner_name = id_to_name.get(master_loan['target_member_id'], 'Unknown')
            
            calc = calculate_sub_loan_month(
                amount_taken=float(sub['amount_taken']),
                duration_months=int(master_loan['duration_months']),
                start_date_str=master_loan['created_at'],
                target_date=target_date
            )
            
            if calc:
                payables_data.append({
                    "Source": f"Sub-Loan from {master_owner_name}",
                    "Belongs To": exact_borrower_name,
                    "EMI No.": calc['emi_number'],
                    "Principal": calc['principal_due'],
                    "Interest": calc['interest_due'],
                    "Total To Pay": calc['total_due']
                })
                
    if payables_data:
        df_payables = pd.DataFrame(payables_data)
        total_bring_cash = df_payables['Total To Pay'].sum()
        
        df_payables.loc['FINAL TOTAL'] = ["", "BRING TO MEETING", "", df_payables['Principal'].sum(), df_payables['Interest'].sum(), total_bring_cash]
        
        format_dict = {'Principal': '₹{:,.0f}', 'Interest': '₹{:,.0f}', 'Total To Pay': '₹{:,.0f}'}
        
        def highlight_total(s):
            if s.name == 'FINAL TOTAL': return ['background-color: #fef9e7; font-weight: bold; color: #b7950b'] * len(s)
            return [''] * len(s)
            
        st.dataframe(df_payables.style.format(format_dict).apply(highlight_total, axis=1), hide_index=True, use_container_width=True)
    else:
        st.success(f"✅ Selected members have no liabilities due for {selected_month_name} {selected_year}.")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # ------------------------------------------
    # TABLE B: RECEIVABLES
    # ------------------------------------------
    st.subheader(f"🟢 Accounts Receivable: What must be COLLECTED before the meeting")
    receivables_data = []
    
    if not settlements_df.empty:
        my_master_loans = loans_df[loans_df['target_member_id'].isin(selected_member_ids)]['id'].tolist()
        lent_out = settlements_df[settlements_df['master_loan_id'].isin(my_master_loans)]
        
        for _, lent in lent_out.iterrows():
            sub_borrower_name = id_to_name.get(lent['sub_borrower_id'], 'Unknown')
            master_loan = loans_df[loans_df['id'] == lent['master_loan_id']].iloc[0]
            exact_originating_name = id_to_name.get(master_loan['target_member_id'], 'Unknown')
            
            calc = calculate_sub_loan_month(
                amount_taken=float(lent['amount_taken']),
                duration_months=int(master_loan['duration_months']),
                start_date_str=master_loan['created_at'],
                target_date=target_date
            )
            
            if calc:
                receivables_data.append({
                    "Sub-Lent To": sub_borrower_name,
                    "Originating Loan": f"Direct Loan #{lent['master_loan_id']} ({exact_originating_name})",
                    "EMI No.": calc['emi_number'],
                    "Principal": calc['principal_due'],
                    "Interest": calc['interest_due'],
                    "Amount to Collect": calc['total_due']
                })
                
    if receivables_data:
        df_receivables = pd.DataFrame(receivables_data)
        format_dict_rec = {'Principal': '₹{:,.0f}', 'Interest': '₹{:,.0f}', 'Amount to Collect': '₹{:,.0f}'}
        st.dataframe(df_receivables.style.format(format_dict_rec), hide_index=True, use_container_width=True)
    else:
        st.info("No sub-loans to collect this month.")