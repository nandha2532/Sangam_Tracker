import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode

# ==========================================
# HELPER: SUB-LOAN CALCULATOR
# ==========================================
def calculate_sub_loan_month(amount_taken, duration_months, start_date_str, target_date):
    try:
        start_date = pd.to_datetime(start_date_str).date()
    except Exception:
        return None
        
    month_index = (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month)
    
    if month_index < 1 or month_index > duration_months:
        return None
        
    monthly_principal = amount_taken / duration_months
    monthly_rate = 0.02 # 2% Common Interest
    
    current_outstanding = amount_taken - (monthly_principal * (month_index - 1))
    interest = current_outstanding * monthly_rate
    
    return {
        "emi_number": month_index,
        "principal_due": monthly_principal,
        "interest_due": interest,
        "total_due": monthly_principal + interest
    }

# ==========================================
# AG-GRID RENDERER
# ==========================================
def render_allocator_grid(df_data, key_name):
    df = pd.DataFrame(df_data)
    if df.empty:
        return pd.DataFrame()
        
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=False)
    gb.configure_column("master_id", hide=True)
    
    gb.configure_column("Source", pinned="left", width=220)
    gb.configure_column("Belongs To", width=140)
    
    if "Sub-Loan Details" in df.columns:
        gb.configure_column("Sub-Loan Details", width=200)
    
    # Currency Formatter
    currency_formatter = JsCode("function(params) { if (params.value == null || params.value === 0) return '₹0'; return '₹' + Number(params.value).toLocaleString('en-IN'); }")
    
    for col in ["Expected", "Total Expected", "Sub-Loan Share", "Net Expected", "Already Paid", "Remaining Due"]:
        if col in df.columns:
            gb.configure_column(col, type=["numericColumn"], valueFormatter=currency_formatter, width=130)

    # Editable Columns
    gb.configure_column("Cash Paid", editable=True, type=["numericColumn"], valueFormatter=currency_formatter, width=120)
    gb.configure_column("Bank Paid", editable=True, type=["numericColumn"], valueFormatter=currency_formatter, width=120)
    
    # LIVE Calculated Columns 
    gb.configure_column("Total Paying Now", type=["numericColumn"], width=150,
                        valueGetter=JsCode("function(params) { return (Number(params.data['Cash Paid']) || 0) + (Number(params.data['Bank Paid']) || 0); }"),
                        valueFormatter=currency_formatter)
                        
    gb.configure_column("Balance After", type=["numericColumn"], width=140,
                        valueGetter=JsCode("function(params) { return Number(params.data['Remaining Due']) - ((Number(params.data['Cash Paid']) || 0) + (Number(params.data['Bank Paid']) || 0)); }"),
                        valueFormatter=currency_formatter)

    # Dynamic Green Row Styling
    row_style_alloc = JsCode("""
    function(params) {
        let rem = Number(params.data['Remaining Due']) - ((Number(params.data['Cash Paid']) || 0) + (Number(params.data['Bank Paid']) || 0));
        if (rem <= 0) {
            return {'backgroundColor': '#D1E7DD', 'color': '#0F5132', 'fontWeight': 'bold'};
        }
        return null;
    }
    """)
    
    gb.configure_grid_options(getRowStyle=row_style_alloc, singleClickEdit=True)
    
    grid_resp = AgGrid(df, gridOptions=gb.build(), update_mode=GridUpdateMode.MODEL_CHANGED, data_return_mode=DataReturnMode.AS_INPUT, allow_unsafe_jscode=True, theme="streamlit", key=key_name)
    
    return pd.DataFrame(grid_resp['data'])

# ==========================================
# UI COMPONENT: SETTLEMENT ALLOCATOR
# ==========================================
def render_individual_settlement(member_dict, target_year, target_month, target_date_obj, id_to_name, emis_df, loans_df, settlements_df, hide_paid_settlements):
    st.divider()
    st.markdown("### 📊 Individual Settlement Statement & Allocator")
    
    settlement_members = st.multiselect(
        "Target Member(s) [Select multiple to combine aliases]",
        options=list(member_dict.keys()),
        help="Select member(s) to view their comprehensive settlement and route payments to the EMI table."
    )
    
    if settlement_members:
        hide_paid_settlements_local = st.checkbox("Hide fully paid loans (Check to view only pending)", value=hide_paid_settlements, key="hide_paid_settle")
        
        settle_ids = [member_dict[n] for n in settlement_members]
        
        direct_payables_data = []
        subloan_payables_data = []
        receivables_data = []
        
        total_direct_liability = 0.0
        total_sub_loans_payable = 0.0
        total_sub_loans_receivable = 0.0
        
        # 1. Direct Loans Calculations (Now with Sub-Loan Breakdowns!)
        if not emis_df.empty:
            emis_df['pay_date'] = pd.to_datetime(emis_df['pay_date'])
            
            for _, row in emis_df.iterrows():
                try:
                    row_member_id = int(float(row['member_id']))
                except (ValueError, TypeError):
                    continue
                    
                if row_member_id in settle_ids:
                    pay_date = row['pay_date']
                    status = str(row.get('status', 'Pending'))
                    
                    is_current = (pay_date.year == target_year and pay_date.month == target_month)
                    is_overdue = ((pay_date.year < target_year) or (pay_date.year == target_year and pay_date.month < target_month)) and (status != 'Paid')
                    
                    if is_current or is_overdue:
                        exact_ticket_name = id_to_name.get(row_member_id, 'Unknown')
                        loan_id = row.get('loan_id')
                        emi_num = row.get('emi_number')
                        
                        exp = float(row['total_expected']) if pd.notna(row.get('total_expected')) else 0.0
                        p_c = float(row['paid_cash']) if pd.notna(row.get('paid_cash')) else 0.0
                        p_o = float(row['paid_online']) if pd.notna(row.get('paid_online')) else 0.0
                        
                        already_paid = p_c + p_o
                        remaining = exp - already_paid
                        
                        if hide_paid_settlements_local and remaining <= 0:
                            continue
                            
                        # Search for sub-loans carrying the weight of this EMI
                        sub_share_total = 0.0
                        sub_details = []
                        if not settlements_df.empty and loan_id and not loans_df.empty:
                            my_splits = settlements_df[settlements_df['master_loan_id'] == loan_id]
                            master_loan_row = loans_df[loans_df['id'] == loan_id]
                            if not master_loan_row.empty:
                                m_row = master_loan_row.iloc[0]
                                for _, split in my_splits.iterrows():
                                    sub_name = id_to_name.get(split['sub_borrower_id'], 'Unknown')
                                    calc = calculate_sub_loan_month(float(split['amount_taken']), int(m_row['duration_months']), m_row['created_at'], target_date_obj)
                                    if calc and calc['emi_number'] == emi_num:
                                        sub_share_total += float(calc['total_due'])
                                        sub_details.append(f"{sub_name} (₹{calc['total_due']:,.0f})")
                                        
                        sub_detail_str = " + ".join(sub_details) if sub_details else "-"
                        
                        total_direct_liability += remaining
                        direct_payables_data.append({
                            "master_id": row_member_id,
                            "Source": f"Direct Loan #{loan_id} (EMI #{emi_num})",
                            "Belongs To": exact_ticket_name,
                            "Total Expected": exp,
                            "Sub-Loan Share": sub_share_total,
                            "Sub-Loan Details": sub_detail_str,
                            "Net Expected": exp - sub_share_total,
                            "Already Paid": already_paid,
                            "Remaining Due": remaining,
                            "Cash Paid": 0.0,
                            "Bank Paid": 0.0
                        })
                
        # 2. Sub-Loans Taken Calculations
        if not settlements_df.empty and not loans_df.empty:
            my_sub_loans = settlements_df[settlements_df['sub_borrower_id'].isin(settle_ids)]
            for _, sub in my_sub_loans.iterrows():
                exact_borrower_name = id_to_name.get(sub['sub_borrower_id'], 'Unknown')
                master_loan = loans_df[loans_df['id'] == sub['master_loan_id']].iloc[0]
                master_owner_id = int(master_loan['target_member_id'])
                master_owner_name = id_to_name.get(master_owner_id, 'Unknown')
                
                calc = calculate_sub_loan_month(
                    amount_taken=float(sub['amount_taken']),
                    duration_months=int(master_loan['duration_months']),
                    start_date_str=master_loan['created_at'],
                    target_date=target_date_obj
                )
                
                if calc:
                    master_emi_paid = False
                    if not emis_df.empty:
                        m_emi = emis_df[(emis_df['loan_id'] == master_loan['id']) & (emis_df['emi_number'] == calc['emi_number'])]
                        if not m_emi.empty and m_emi.iloc[0].get('status') == 'Paid':
                            master_emi_paid = True
                            
                    if hide_paid_settlements_local and master_emi_paid:
                        continue
                        
                    total_due = float(calc['total_due'])
                    already_paid = total_due if master_emi_paid else 0.0
                    remaining = 0.0 if master_emi_paid else total_due
                    
                    total_sub_loans_payable += remaining
                    
                    subloan_payables_data.append({
                        "master_id": master_owner_id, 
                        "Source": f"Sub-Loan from {master_owner_name} (EMI #{calc['emi_number']})",
                        "Belongs To": exact_borrower_name,
                        "Expected": total_due,
                        "Already Paid": already_paid,
                        "Remaining Due": remaining,
                        "Cash Paid": 0.0,
                        "Bank Paid": 0.0
                    })
                    
        # 3. Sub-Loans Given (Receivables)
        if not settlements_df.empty and not loans_df.empty:
            my_master_loans = loans_df[loans_df['target_member_id'].isin(settle_ids)]['id'].tolist()
            lent_out = settlements_df[settlements_df['master_loan_id'].isin(my_master_loans)]
            
            for _, lent in lent_out.iterrows():
                sub_borrower_name = id_to_name.get(lent['sub_borrower_id'], 'Unknown')
                master_loan = loans_df[loans_df['id'] == lent['master_loan_id']].iloc[0]
                exact_originating_name = id_to_name.get(master_loan['target_member_id'], 'Unknown')
                
                calc = calculate_sub_loan_month(
                    amount_taken=float(lent['amount_taken']),
                    duration_months=int(master_loan['duration_months']),
                    start_date_str=master_loan['created_at'],
                    target_date=target_date_obj
                )
                
                if calc:
                    master_emi_paid = False
                    if not emis_df.empty:
                        m_emi = emis_df[(emis_df['loan_id'] == master_loan['id']) & (emis_df['emi_number'] == calc['emi_number'])]
                        if not m_emi.empty and m_emi.iloc[0].get('status') == 'Paid':
                            master_emi_paid = True
                            
                    if hide_paid_settlements_local and master_emi_paid:
                        continue
                        
                    amount_to_collect = float(calc['total_due'])
                    already_collected = amount_to_collect if master_emi_paid else 0.0
                    remaining = 0.0 if master_emi_paid else amount_to_collect
                    
                    total_sub_loans_receivable += remaining
                    
                    receivables_data.append({
                        "Sub-Lent To": sub_borrower_name,
                        "Originating Loan": f"Direct Loan #{lent['master_loan_id']} (EMI #{calc['emi_number']})",
                        "Expected": amount_to_collect,
                        "Already Collected": already_collected,
                        "Remaining to Collect": remaining
                    })

        # Render Financial Overview
        net_total_payable = (total_direct_liability - total_sub_loans_receivable) + total_sub_loans_payable
        
        st.markdown("#### 💼 Financial Overview")
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("1️⃣ Direct Loan Liability", f"₹{total_direct_liability:,.0f}")
        kpi2.metric("2️⃣ Total Net (Bring to Meeting)", f"₹{net_total_payable:,.0f}")
        kpi3.metric("3️⃣ Sub-Loans Payable", f"₹{total_sub_loans_payable:,.0f}")
        kpi4.metric("4️⃣ Sub-Loans Receivable", f"₹{total_sub_loans_receivable:,.0f}")

        # Render Interactive Allocation Tables
        st.markdown("#### 🎯 Allocate Funds & Stage to EMI Table")
        st.caption("Enter Cash or Bank amounts directly in the tables below. Click 'Populate' to automatically send the funds to the correct Master Loan holder in the EMI table.")
        
        edited_direct = pd.DataFrame()
        edited_sub = pd.DataFrame()
        
        # --- DIRECT LOANS TABLE (AG-GRID) ---
        if direct_payables_data:
            st.write("**🔴 Direct Loans Owed**")
            edited_direct = render_allocator_grid(direct_payables_data, f"alloc_dir_{st.session_state['form_reset_key']}")
            
            if not edited_direct.empty:
                t_expected = pd.to_numeric(edited_direct['Total Expected'], errors='coerce').fillna(0).sum()
                t_already = pd.to_numeric(edited_direct['Already Paid'], errors='coerce').fillna(0).sum()
                t_remaining = pd.to_numeric(edited_direct['Remaining Due'], errors='coerce').fillna(0).sum()
                t_cash = pd.to_numeric(edited_direct['Cash Paid'], errors='coerce').fillna(0).sum()
                t_bank = pd.to_numeric(edited_direct['Bank Paid'], errors='coerce').fillna(0).sum()
                t_paying = t_cash + t_bank
                t_bal = t_remaining - t_paying
                
                st.markdown(f"""
                <div style='background-color:#1E293B; padding:10px; border-radius:5px; margin-top:-5px; margin-bottom:20px; display:flex; justify-content:flex-end; gap:20px; font-weight:bold; font-size:13px;'>
                    <span style='color:#94A3B8;'>TOTAL EXPECTED: ₹{t_expected:,.0f}</span>
                    <span style='color:#94A3B8;'>ALREADY PAID: ₹{t_already:,.0f}</span>
                    <span style='color:#F8FAFC;'>REMAINING DUE: <span style='color:#FCD34D;'>₹{t_remaining:,.0f}</span></span>
                    <span style='color:#F8FAFC;'>TOTAL PAYING NOW: <span style='color:#34D399;'>₹{t_paying:,.0f}</span></span>
                    <span style='color:#F8FAFC;'>BALANCE AFTER: <span style='color:#60A5FA;'>₹{t_bal:,.0f}</span></span>
                </div>
                """, unsafe_allow_html=True)

        # --- SUB LOANS TABLE (AG-GRID) ---
        if subloan_payables_data:
            st.write("**🟠 Sub-Loans Owed to Others**")
            edited_sub = render_allocator_grid(subloan_payables_data, f"alloc_sub_{st.session_state['form_reset_key']}")
            
            if not edited_sub.empty:
                t_sub_expected = pd.to_numeric(edited_sub['Expected'], errors='coerce').fillna(0).sum()
                t_sub_already = pd.to_numeric(edited_sub['Already Paid'], errors='coerce').fillna(0).sum()
                t_sub_remaining = pd.to_numeric(edited_sub['Remaining Due'], errors='coerce').fillna(0).sum()
                t_sub_cash = pd.to_numeric(edited_sub['Cash Paid'], errors='coerce').fillna(0).sum()
                t_sub_bank = pd.to_numeric(edited_sub['Bank Paid'], errors='coerce').fillna(0).sum()
                t_sub_paying = t_sub_cash + t_sub_bank
                t_sub_bal = t_sub_remaining - t_sub_paying
                
                st.markdown(f"""
                <div style='background-color:#1E293B; padding:10px; border-radius:5px; margin-top:-5px; margin-bottom:20px; display:flex; justify-content:flex-end; gap:20px; font-weight:bold; font-size:13px;'>
                    <span style='color:#94A3B8;'>EXPECTED: ₹{t_sub_expected:,.0f}</span>
                    <span style='color:#94A3B8;'>PAID: ₹{t_sub_already:,.0f}</span>
                    <span style='color:#F8FAFC;'>REMAINING DUE: <span style='color:#FCD34D;'>₹{t_sub_remaining:,.0f}</span></span>
                    <span style='color:#F8FAFC;'>TOTAL PAYING NOW: <span style='color:#34D399;'>₹{t_sub_paying:,.0f}</span></span>
                    <span style='color:#F8FAFC;'>BALANCE AFTER: <span style='color:#60A5FA;'>₹{t_sub_bal:,.0f}</span></span>
                </div>
                """, unsafe_allow_html=True)
            
        if receivables_data:
            st.write("**🟢 Sub-Loans to Collect** (Read-Only)")
            st.dataframe(
                pd.DataFrame(receivables_data),
                column_config={
                    "Expected": st.column_config.NumberColumn(format="₹%.0f"),
                    "Already Collected": st.column_config.NumberColumn(format="₹%.0f"),
                    "Remaining to Collect": st.column_config.NumberColumn(format="₹%.0f")
                },
                hide_index=True, use_container_width=True
            )

        # Single button to process all interactive tables at once
        if not edited_direct.empty or not edited_sub.empty:
            if st.button("⬇️ Populate Entered Funds to EMI Table", type="primary"):
                staged_any = False
                
                def process_allocated_funds(df):
                    nonlocal staged_any
                    for _, row in df.iterrows():
                        c_amt = float(row.get('Cash Paid', 0.0) or 0.0)
                        b_amt = float(row.get('Bank Paid', 0.0) or 0.0)
                        if c_amt > 0 or b_amt > 0:
                            m_id = int(row['master_id'])
                            if m_id not in st.session_state['prefill_emi']:
                                st.session_state['prefill_emi'][m_id] = {'cash': 0.0, 'bank': 0.0}
                            st.session_state['prefill_emi'][m_id]['cash'] += c_amt
                            st.session_state['prefill_emi'][m_id]['bank'] += b_amt
                            staged_any = True

                if not edited_direct.empty: process_allocated_funds(edited_direct)
                if not edited_sub.empty: process_allocated_funds(edited_sub)
                
                if staged_any:
                    st.session_state['form_reset_key'] += 1 # Force grid redraw
                    st.toast("✅ Funds successfully staged to the EMI table!", icon="⬇️")
                    st.rerun()
                else:
                    st.warning("Please enter at least one amount greater than 0 in the tables above.")