import streamlit as st
import pandas as pd
import calendar
from datetime import datetime
from database import supabase, fetch_table, clear_db_cache
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

def render_collection_desk(members_df, member_dict, global_target_date):
    st.markdown("<h1 style='color:#34D399;'>💰 Meeting Day Collection Desk</h1>", unsafe_allow_html=True)
    
    # ---------------------------------------------------------
    # STATE MANAGEMENT
    # ---------------------------------------------------------
    if 'form_reset_key' not in st.session_state:
        st.session_state['form_reset_key'] = 0
    if 'prefill_emi' not in st.session_state:
        st.session_state['prefill_emi'] = {}

    emis_df = fetch_table("emi_ledger")
    savings_df = fetch_table("savings_log")
    receipts_df = fetch_table("payment_receipts")
    loans_df = fetch_table("loans")
    settlements_df = fetch_table("individual_settlement")
    
    if not receipts_df.empty:
        receipts_df['logged_at'] = pd.to_datetime(receipts_df['logged_at'])
    
    target_year = global_target_date.year
    target_month = global_target_date.month
    selected_month_name = calendar.month_name[target_month]
    target_log_date = global_target_date.strftime("%Y-%m-%d")
    target_date_obj = datetime(target_year, target_month, 15).date()
    id_to_name = dict(zip(members_df['id'], members_df['name']))
    
    st.info(f"🗓️ Currently viewing and logging data for: **{selected_month_name} {target_year}**")
    
    # ==========================================
    # 🏦 SPLIT TREASURY SUMMARY
    # ==========================================
    st.divider()
    st.markdown(f"### 🏦 Treasury Summary ({selected_month_name} {target_year})")
    
    if not receipts_df.empty:
        monthly_receipts = receipts_df[(receipts_df['logged_at'].dt.month == target_month) & 
                                       (receipts_df['logged_at'].dt.year == target_year)]
                                       
        sav_receipts = monthly_receipts[monthly_receipts['payment_type'] == 'Savings']
        emi_receipts = monthly_receipts[monthly_receipts['payment_type'] != 'Savings']
        
        sav_cash = sav_receipts['amount_cash'].sum()
        sav_online = sav_receipts['amount_online'].sum()
        
        emi_cash = emi_receipts['amount_cash'].sum()
        emi_online = emi_receipts['amount_online'].sum()
        
        st.markdown("#### 🟢 Savings Collection")
        s1, s2, s3 = st.columns(3)
        s1.metric("💵 Total Cash in Hand", f"₹{sav_cash:,.0f}")
        s2.metric("📱 Total Bank Balance", f"₹{sav_online:,.0f}")
        s3.metric("🎯 Monthly Grand Total", f"₹{sav_cash + sav_online:,.0f}")
        
        st.markdown("#### 🔵 Loan EMI Collection")
        e1, e2, e3 = st.columns(3)
        e1.metric("💵 Total Cash in Hand", f"₹{emi_cash:,.0f}")
        e2.metric("📱 Total Bank Balance", f"₹{emi_online:,.0f}")
        e3.metric("🎯 Monthly Grand Total", f"₹{emi_cash + emi_online:,.0f}")
    else:
        st.info("No payments have been logged yet.")

    # ==========================================
    # 📊 INDIVIDUAL SETTLEMENT STATEMENT & ALLOCATOR
    # ==========================================
    st.divider()
    st.markdown("### 📊 Individual Settlement Statement & Allocator")
    
    settlement_members = st.multiselect(
        "Target Member(s) [Select multiple to combine aliases]",
        options=list(member_dict.keys()),
        help="Select member(s) to view their comprehensive settlement and route payments to the EMI table."
    )
    
    if settlement_members:
        settle_ids = [member_dict[n] for n in settlement_members]
        
        direct_payables_data = []
        subloan_payables_data = []
        receivables_data = []
        
        total_direct_liability = 0.0
        total_sub_loans_payable = 0.0
        total_sub_loans_receivable = 0.0
        
        # 1. Direct Loans Calculations (FIXED to evaluate row-by-row safely)
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
                        
                        exp = float(row['total_expected']) if pd.notna(row.get('total_expected')) else 0.0
                        p_c = float(row['paid_cash']) if pd.notna(row.get('paid_cash')) else 0.0
                        p_o = float(row['paid_online']) if pd.notna(row.get('paid_online')) else 0.0
                        
                        expected = exp - (p_c + p_o)
                        
                        if expected > 0:
                            total_direct_liability += expected
                            direct_payables_data.append({
                                "master_id": row_member_id, # Hidden
                                "Source": f"Direct Loan #{row.get('loan_id', '?')} (EMI #{row.get('emi_number', '?')})",
                                "Belongs To": exact_ticket_name,
                                "Total To Pay": expected,
                                "Cash Paid (₹)": 0.0,
                                "Bank Paid (₹)": 0.0
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
                    # Check if the Master Loan's EMI is already fully paid
                    master_emi_paid = False
                    if not emis_df.empty:
                        m_emi = emis_df[(emis_df['loan_id'] == master_loan['id']) & (emis_df['emi_number'] == calc['emi_number'])]
                        if not m_emi.empty and m_emi.iloc[0].get('status') == 'Paid':
                            master_emi_paid = True
                            
                    # Only show and calculate if the master EMI is NOT paid
                    if not master_emi_paid:
                        total_due = float(calc['total_due'])
                        total_sub_loans_payable += total_due
                        
                        subloan_payables_data.append({
                            "master_id": master_owner_id, # Hidden mapping to the Master Holder
                            "Source": f"Sub-Loan from {master_owner_name} (EMI #{calc['emi_number']})",
                            "Belongs To": exact_borrower_name,
                            "Total To Pay": total_due,
                            "Cash Paid (₹)": 0.0,
                            "Bank Paid (₹)": 0.0
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
                    # Check if the Master Loan's EMI is already fully paid
                    master_emi_paid = False
                    if not emis_df.empty:
                        m_emi = emis_df[(emis_df['loan_id'] == master_loan['id']) & (emis_df['emi_number'] == calc['emi_number'])]
                        if not m_emi.empty and m_emi.iloc[0].get('status') == 'Paid':
                            master_emi_paid = True
                            
                    # Only show and calculate if the master EMI is NOT paid
                    if not master_emi_paid:
                        amount_to_collect = float(calc['total_due'])
                        total_sub_loans_receivable += amount_to_collect
                        
                        receivables_data.append({
                            "Sub-Lent To": sub_borrower_name,
                            "Originating Loan": f"Direct Loan #{lent['master_loan_id']} (EMI #{calc['emi_number']})",
                            "Amount to Collect": amount_to_collect
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
        
        # --- DIRECT LOANS TABLE ---
        if direct_payables_data:
            st.write("**🔴 Direct Loans Owed**")
            edited_direct = st.data_editor(
                pd.DataFrame(direct_payables_data),
                column_config={
                    "master_id": None, # Hides the ID column securely
                    "Total To Pay": st.column_config.NumberColumn(format="₹%.0f", disabled=True),
                    "Source": st.column_config.TextColumn(disabled=True),
                    "Belongs To": st.column_config.TextColumn(disabled=True),
                    "Cash Paid (₹)": st.column_config.NumberColumn(min_value=0.0, step=100.0),
                    "Bank Paid (₹)": st.column_config.NumberColumn(min_value=0.0, step=100.0)
                },
                hide_index=True, use_container_width=True, key=f"alloc_dir_{st.session_state['form_reset_key']}"
            )
            # Live Total Row Display
            t_due = edited_direct['Total To Pay'].sum()
            t_cash = edited_direct['Cash Paid (₹)'].sum()
            t_bank = edited_direct['Bank Paid (₹)'].sum()
            st.markdown(f"""
            <div style='background-color:#1E293B; padding:10px; border-radius:5px; margin-top:-15px; margin-bottom:20px; display:flex; justify-content:flex-end; gap:30px; font-weight:bold;'>
                <span style='color:#F8FAFC;'>TOTAL DUE: <span style='color:#FCD34D;'>₹{t_due:,.0f}</span></span>
                <span style='color:#F8FAFC;'>TOTAL CASH: <span style='color:#34D399;'>₹{t_cash:,.0f}</span></span>
                <span style='color:#F8FAFC;'>TOTAL BANK: <span style='color:#60A5FA;'>₹{t_bank:,.0f}</span></span>
            </div>
            """, unsafe_allow_html=True)

        # --- SUB LOANS TABLE ---
        if subloan_payables_data:
            st.write("**🟠 Sub-Loans Owed to Others**")
            edited_sub = st.data_editor(
                pd.DataFrame(subloan_payables_data),
                column_config={
                    "master_id": None, 
                    "Total To Pay": st.column_config.NumberColumn(format="₹%.0f", disabled=True),
                    "Source": st.column_config.TextColumn(disabled=True),
                    "Belongs To": st.column_config.TextColumn(disabled=True),
                    "Cash Paid (₹)": st.column_config.NumberColumn(min_value=0.0, step=100.0),
                    "Bank Paid (₹)": st.column_config.NumberColumn(min_value=0.0, step=100.0)
                },
                hide_index=True, use_container_width=True, key=f"alloc_sub_{st.session_state['form_reset_key']}"
            )
            # Live Total Row Display
            t_sub_due = edited_sub['Total To Pay'].sum()
            t_sub_cash = edited_sub['Cash Paid (₹)'].sum()
            t_sub_bank = edited_sub['Bank Paid (₹)'].sum()
            st.markdown(f"""
            <div style='background-color:#1E293B; padding:10px; border-radius:5px; margin-top:-15px; margin-bottom:20px; display:flex; justify-content:flex-end; gap:30px; font-weight:bold;'>
                <span style='color:#F8FAFC;'>TOTAL DUE: <span style='color:#FCD34D;'>₹{t_sub_due:,.0f}</span></span>
                <span style='color:#F8FAFC;'>TOTAL CASH: <span style='color:#34D399;'>₹{t_sub_cash:,.0f}</span></span>
                <span style='color:#F8FAFC;'>TOTAL BANK: <span style='color:#60A5FA;'>₹{t_sub_bank:,.0f}</span></span>
            </div>
            """, unsafe_allow_html=True)
            
        if receivables_data:
            st.write("**🟢 Sub-Loans to Collect** (Read-Only)")
            st.dataframe(
                pd.DataFrame(receivables_data),
                column_config={"Amount to Collect": st.column_config.NumberColumn(format="₹%.0f")},
                hide_index=True, use_container_width=True
            )

        # Single button to process all interactive tables at once
        if not edited_direct.empty or not edited_sub.empty:
            if st.button("⬇️ Populate Entered Funds to EMI Table", type="primary"):
                staged_any = False
                
                def process_allocated_funds(df):
                    nonlocal staged_any
                    for _, row in df.iterrows():
                        c_amt = float(row.get('Cash Paid (₹)', 0.0) or 0.0)
                        b_amt = float(row.get('Bank Paid (₹)', 0.0) or 0.0)
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

    # ==========================================
    # MAIN DESK: QUICK FILTERS
    # ==========================================
    st.divider()
    st.markdown("### 🔎 Quick Filters")
    show_pending_only = st.checkbox("Hide fully paid members", value=False)
    
    if st.button("🧹 Clear All Staged Allocations"):
        st.session_state['prefill_emi'] = {}
        st.session_state['form_reset_key'] += 1
        st.rerun()
    
    meeting_data_sav = []
    meeting_data_emi = []
    
    for _, member in members_df.iterrows():
        m_id = member['id']
        m_name = member['name']
        
        # 1. SAVINGS CALCULATIONS
        savings_expected = 500.0
        savings_already_paid = 0.0
        if not savings_df.empty:
             savings_df['created_at'] = pd.to_datetime(savings_df['created_at'])
             paid_this_month = savings_df[(savings_df['member_id'] == m_id) & 
                                          (savings_df['created_at'].dt.month == target_month) & 
                                          (savings_df['created_at'].dt.year == target_year)]
             if not paid_this_month.empty:
                 savings_already_paid = paid_this_month['amount'].sum()
                 
        sav_remaining = max(0, savings_expected - savings_already_paid)
        
        if not (show_pending_only and sav_remaining <= 0):
            meeting_data_sav.append({
                "Member_ID": m_id, "Name": m_name, "Full Cash ✅": False, "Full Bank ✅": False,
                "Remaining Due": sav_remaining, "Already Paid": savings_already_paid, "Expected": savings_expected,
                "Custom Cash": 0.0, "Custom Bank": 0.0
            })

        # 2. EMI CALCULATIONS (WITH PRE-FILL INTEGRATION)
        emi_expected = 0.0
        emi_already_paid = 0.0
        
        if not emis_df.empty:
            emis_df['pay_date'] = pd.to_datetime(emis_df['pay_date'])
            relevant_emis = emis_df[(emis_df['member_id'] == m_id) & 
                                    (((emis_df['pay_date'].dt.year == target_year) & (emis_df['pay_date'].dt.month == target_month)) | 
                                     (((emis_df['pay_date'].dt.year < target_year) | ((emis_df['pay_date'].dt.year == target_year) & (emis_df['pay_date'].dt.month < target_month))) & (emis_df['status'] != 'Paid')))]
            for _, row in relevant_emis.iterrows():
                emi_expected += float(row['total_expected'])
                emi_already_paid += float(row.get('paid_cash', 0) or 0) + float(row.get('paid_online', 0) or 0)
                
        emi_remaining = max(0, emi_expected - emi_already_paid)
        
        if not (show_pending_only and emi_remaining <= 0):
            # Pull any staged funds assigned to this Master Loan holder from the Allocator above
            staged_funds = st.session_state['prefill_emi'].get(m_id, {'cash': 0.0, 'bank': 0.0})
            
            meeting_data_emi.append({
                "Member_ID": m_id, 
                "Name": m_name, 
                "Cash Paid": staged_funds['cash'], 
                "Bank Paid": staged_funds['bank'],
                "Remaining Due": emi_remaining, 
                "Already Paid": emi_already_paid, 
                "Expected": emi_expected
            })
            
    df_sav = pd.DataFrame(meeting_data_sav)
    df_emi = pd.DataFrame(meeting_data_emi)

    # ==========================================
    # AG-GRID: STYLING & BULLETPROOF CHECKBOXES
    # ==========================================
    row_style_jscode = JsCode("""
    function(params) {
        if (params.data['Remaining Due'] <= 0) {
            return {'backgroundColor': '#D1E7DD', 'color': '#0F5132', 'fontWeight': 'bold'};
        } else if (params.node.rowIndex % 2 === 0) {
            return {'backgroundColor': '#FCE4D6', 'color': '#000000'};
        } else {
            return {'backgroundColor': '#FFFFFF', 'color': '#000000'};
        }
    }
    """)

    bulletproof_checkbox_renderer = JsCode("""
    class CheckboxRenderer {
        init(params) {
            this.params = params;
            this.eGui = document.createElement('div');
            this.eGui.style.display = 'flex';
            this.eGui.style.justifyContent = 'center';
            this.eGui.style.alignItems = 'center';
            this.eGui.style.height = '100%';
            this.eGui.style.width = '100%';
            this.eGui.style.cursor = 'pointer';
            
            this.eCheckbox = document.createElement('input');
            this.eCheckbox.type = 'checkbox';
            this.eCheckbox.style.transform = 'scale(1.5)';
            this.eCheckbox.style.accentColor = '#10B981'; 
            this.eCheckbox.style.pointerEvents = 'none'; 
            
            let isChecked = params.value === true || params.value === 'true';
            this.eCheckbox.checked = isChecked;
            
            this.eGui.addEventListener('click', () => {
                let currentVal = this.params.value === true || this.params.value === 'true';
                let newVal = !currentVal;
                this.params.node.setDataValue(this.params.colDef.field, newVal);
            });
            
            this.eGui.appendChild(this.eCheckbox);
        }
        
        getGui() { return this.eGui; }
        
        refresh(params) {
            this.params = params;
            let isChecked = params.value === true || params.value === 'true';
            this.eCheckbox.checked = isChecked;
            return true;
        }
    }
    """)

    validation_failed = False

    # ==========================================
    # UI: TABLE 1 - EMIs (AG-GRID)
    # ==========================================
    st.markdown("### 🔵 1. Loan EMI Collection")
    edited_emi = pd.DataFrame()
    if not df_emi.empty:
        gb_emi = GridOptionsBuilder.from_dataframe(df_emi)
        gb_emi.configure_default_column(editable=False)
        gb_emi.configure_column("Member_ID", hide=True)
        gb_emi.configure_column("Name", pinned="left")
        gb_emi.configure_column("Cash Paid", editable=True, type=["numericColumn"])
        gb_emi.configure_column("Bank Paid", editable=True, type=["numericColumn"])
        
        gb_emi.configure_grid_options(getRowStyle=row_style_jscode, singleClickEdit=True)
        
        grid_response_emi = AgGrid(
            df_emi, gridOptions=gb_emi.build(), update_mode=GridUpdateMode.MODEL_CHANGED,
            data_return_mode=DataReturnMode.AS_INPUT, allow_unsafe_jscode=True, theme="streamlit",
            key=f"emi_grid_{st.session_state['form_reset_key']}"
        )
        edited_emi = pd.DataFrame(grid_response_emi['data'])
    else:
        st.success("All visible EMI dues are clear!")

    # ==========================================
    # UI: TABLE 2 - SAVINGS (AG-GRID)
    # ==========================================
    st.markdown("### 🟢 2. Monthly Savings Collection (₹500)")
    
    edited_sav = pd.DataFrame()
    if not df_sav.empty:
        gb_sav = GridOptionsBuilder.from_dataframe(df_sav)
        gb_sav.configure_default_column(editable=False)
        gb_sav.configure_column("Member_ID", hide=True)
        gb_sav.configure_column("Name", pinned="left")
        
        gb_sav.configure_column("Full Cash ✅", editable=False, cellRenderer=bulletproof_checkbox_renderer)
        gb_sav.configure_column("Full Bank ✅", editable=False, cellRenderer=bulletproof_checkbox_renderer)
        gb_sav.configure_column("Custom Cash", editable=True, type=["numericColumn"])
        gb_sav.configure_column("Custom Bank", editable=True, type=["numericColumn"])
        
        gb_sav.configure_grid_options(getRowStyle=row_style_jscode, singleClickEdit=True)
        
        grid_response_sav = AgGrid(
            df_sav, gridOptions=gb_sav.build(), update_mode=GridUpdateMode.MODEL_CHANGED,
            data_return_mode=DataReturnMode.AS_INPUT, allow_unsafe_jscode=True, theme="streamlit",
            key=f"sav_grid_{st.session_state['form_reset_key']}"
        )
        edited_sav = pd.DataFrame(grid_response_sav['data'])
        
        sav_errors = []
        for _, row in edited_sav.iterrows():
            member_name = row.get('Name')
            is_full_cash = str(row.get('Full Cash ✅')).lower() == 'true'
            is_full_bank = str(row.get('Full Bank ✅')).lower() == 'true'
            cust_cash = float(row.get('Custom Cash', 0.0) or 0)
            cust_bank = float(row.get('Custom Bank', 0.0) or 0)
            
            if is_full_cash or is_full_bank or cust_cash > 0 or cust_bank > 0:
                if is_full_cash and is_full_bank:
                    sav_errors.append(f"❌ **{member_name}**: Both 'Full Cash' and 'Full Bank' are checked.")
                    validation_failed = True
                elif (is_full_cash or is_full_bank) and (cust_cash > 0 or cust_bank > 0):
                    sav_errors.append(f"❌ **{member_name}**: Do not mix checkboxes with custom amounts.")
                    validation_failed = True
                elif (cust_cash + cust_bank) > 500.0:
                    sav_errors.append(f"❌ **{member_name}**: Custom total entered is ₹{cust_cash + cust_bank}. Max is ₹500.")
                    validation_failed = True

        if sav_errors:
            for err in sav_errors: st.error(err)
    else:
        st.success("All visible Savings dues are clear!")

    # ==========================================
    # EXTRACT STAGED ROWS
    # ==========================================
    to_commit_sav_list = []
    if not edited_sav.empty and not validation_failed:
        for _, row in edited_sav.iterrows():
            is_full_cash = str(row.get('Full Cash ✅')).lower() == 'true'
            is_full_bank = str(row.get('Full Bank ✅')).lower() == 'true'
            cust_cash = float(row.get('Custom Cash', 0.0) or 0)
            cust_bank = float(row.get('Custom Bank', 0.0) or 0)
            if is_full_cash or is_full_bank or cust_cash > 0 or cust_bank > 0:
                to_commit_sav_list.append((row, is_full_cash, is_full_bank, cust_cash, cust_bank))

    to_commit_emi_list = []
    if not edited_emi.empty and not validation_failed:
        for _, row in edited_emi.iterrows():
            c_paid = float(row.get('Cash Paid', 0.0) or 0)
            b_paid = float(row.get('Bank Paid', 0.0) or 0)
            if c_paid > 0 or b_paid > 0:
                to_commit_emi_list.append((row, c_paid, b_paid))

    # ==========================================
    # DRAFT TOTALS 
    # ==========================================
    st.markdown("### ⚖️ Uncommitted Session Draft")
    
    draft_sav_cash, draft_sav_online = 0, 0
    for r, is_c, is_b, c_amt, b_amt in to_commit_sav_list:
        draft_sav_cash += 500.0 if is_c else c_amt
        draft_sav_online += 500.0 if is_b else b_amt
            
    draft_emi_cash = sum([c for _, c, _ in to_commit_emi_list])
    draft_emi_online = sum([b for _, _, b in to_commit_emi_list])
    
    total_cash_box = draft_sav_cash + draft_emi_cash
    total_bank = draft_sav_online + draft_emi_online
    grand_total = total_cash_box + total_bank
    
    c1, c2, c3 = st.columns(3)
    c1.metric("💵 Draft Cash Box", f"₹{total_cash_box:,.0f}")
    c2.metric("📱 Draft Bank Transfers", f"₹{total_bank:,.0f}")
    c3.metric("🎯 Draft Total", f"₹{grand_total:,.0f}")
    
    st.markdown("### 💾 Finalize & Save Transactions")
    if validation_failed:
        st.warning("⚠️ Please fix the errors in the tables above before saving.")
        
    if st.button(f"🔒 Lock Entered Payments for {target_log_date}", type="primary", disabled=validation_failed):
        commits_made = False
        
        if not to_commit_sav_list and not to_commit_emi_list:
            st.error("No payments entered. Enter amounts in the grids above to commit.")
        else:
            if to_commit_sav_list:
                for row, is_c, is_b, c_amt, b_amt in to_commit_sav_list:
                    m_id = int(row['Member_ID'])
                    cash = 500.0 if is_c else c_amt
                    online = 500.0 if is_b else b_amt
                    if (cash + online) > 0:
                        supabase.table("savings_log").insert({
                            "member_id": m_id, "amount": cash + online,
                            "payment_mode": "Split" if cash > 0 and online > 0 else ("Cash" if cash > 0 else "Online"),
                            "created_at": target_log_date
                        }).execute()
                        
                        supabase.table("payment_receipts").insert({
                            "member_id": m_id, "payment_type": "Savings", 
                            "amount_cash": cash, "amount_online": online, "logged_at": target_log_date
                        }).execute()
                        commits_made = True

            if to_commit_emi_list:
                for row, cash, online in to_commit_emi_list:
                    m_id = int(row['Member_ID'])
                    if (cash + online) > 0:
                         pending = emis_df[(emis_df['member_id'] == m_id) & (emis_df['status'].isin(['Pending', 'Partial'])) & 
                                          (emis_df['pay_date'].dt.month <= target_month) & (emis_df['pay_date'].dt.year <= target_year)]
                         pending = pending.sort_values(by='pay_date')
                         for idx, emi_row in pending.iterrows():
                             if cash + online <= 0: break
                             
                             emi_id = int(emi_row['id'])
                             expected = float(emi_row['total_expected'])
                             current_paid_cash = float(emi_row.get('paid_cash', 0) or 0)
                             current_paid_online = float(emi_row.get('paid_online', 0) or 0)
                             remaining_for_this_emi = expected - (current_paid_cash + current_paid_online)
                             
                             if remaining_for_this_emi <= 0: continue
                                 
                             payment_to_apply = min(remaining_for_this_emi, cash + online)
                             apply_cash = min(payment_to_apply, cash)
                             cash -= apply_cash
                             apply_online = payment_to_apply - apply_cash
                             online -= apply_online
                             
                             new_total_cash = current_paid_cash + apply_cash
                             new_total_online = current_paid_online + apply_online
                             new_status = 'Paid' if (new_total_cash + new_total_online) >= expected else 'Partial'
                             
                             supabase.table("emi_ledger").update({
                                 "status": new_status, "paid_cash": new_total_cash, "paid_online": new_total_online
                             }).eq("id", emi_id).execute()
                             
                             supabase.table("payment_receipts").insert({
                                 "member_id": m_id, "emi_id": emi_id, "payment_type": f"EMI #{emi_row['emi_number']} (Loan {emi_row['loan_id']})", 
                                 "amount_cash": apply_cash, "amount_online": apply_online, "logged_at": target_log_date
                             }).execute()
                             commits_made = True

            if commits_made:
                st.session_state['form_reset_key'] += 1
                st.session_state['prefill_emi'] = {} # Clear staged funds upon successful save
                clear_db_cache()
                st.toast("✅ Meeting Day Ledgers & Receipts Updated!", icon="🎉")
                st.rerun()

    # ==========================================
    # TRANSACTION AUDIT VIEWER & REVERSALS
    # ==========================================
    st.divider()
    st.markdown(f"### 🗃️ Member Payment Audit ({selected_month_name} {target_year})")
    
    audit_member_names = st.multiselect("Select Member(s) to Audit or Edit", options=list(member_dict.keys()), default=[])
    
    if audit_member_names:
        audit_member_ids = [member_dict[n] for n in audit_member_names]
        
        if not receipts_df.empty:
            my_receipts = receipts_df[(receipts_df['member_id'].isin(audit_member_ids)) & 
                                      (receipts_df['logged_at'].dt.month == target_month) & 
                                      (receipts_df['logged_at'].dt.year == target_year)]
            
            if not my_receipts.empty:
                my_receipts = my_receipts.sort_values(by='logged_at', ascending=True)
                id_to_name = {v: k for k, v in member_dict.items()}
                
                display_audit = my_receipts[['id', 'logged_at', 'member_id', 'payment_type', 'amount_cash', 'amount_online']].copy()
                display_audit['Member Name'] = display_audit['member_id'].map(id_to_name)
                display_audit['logged_at'] = display_audit['logged_at'].dt.strftime('%Y-%m-%d')
                display_audit['Total'] = display_audit['amount_cash'] + display_audit['amount_online']
                
                show_audit = display_audit[['logged_at', 'Member Name', 'payment_type', 'amount_cash', 'amount_online', 'Total']].copy()
                show_audit.columns = ['Recorded Date', 'Member Name', 'Payment Towards', 'Cash Paid', 'Online Paid', 'Total Receipt']
                
                total_cash = show_audit['Cash Paid'].sum()
                total_online = show_audit['Online Paid'].sum()
                show_audit.loc['TOTAL'] = ["", "", "MONTHLY COMBINED SUM:", total_cash, total_online, total_cash + total_online]
                
                format_dict = {'Cash Paid': '₹{:,.0f}', 'Online Paid': '₹{:,.0f}', 'Total Receipt': '₹{:,.0f}'}
                def highlight_totals(s):
                    if s.name == 'TOTAL': return ['background-color: #fef9e7; color: #0B0F0E; font-weight: bold'] * len(s)
                    return [''] * len(s)
                st.dataframe(show_audit.style.format(format_dict).apply(highlight_totals, axis=1), hide_index=True, use_container_width=True)
                
                st.markdown("#### ⚙️ Modify or Reverse Logged Transactions")
                with st.expander("Reverse a transaction made by mistake", expanded=False):
                    receipt_options = []
                    receipt_mapping = {}
                    for _, r in display_audit.iterrows():
                        label = f"[{r['logged_at']}] {r['Member Name']} - {r['payment_type']} (₹{r['Total']:,.0f})"
                        receipt_options.append(label)
                        receipt_mapping[label] = r['id']
                        
                    selected_reversal = st.selectbox("Select specific transaction to Reverse/Delete", ["-- Select --"] + receipt_options)
                    
                    if selected_reversal != "-- Select --":
                        target_receipt_id = receipt_mapping[selected_reversal]
                        target_receipt = my_receipts[my_receipts['id'] == target_receipt_id].iloc[0]
                        
                        st.warning(f"⚠️ You are about to permanently delete this receipt and reverse the ₹{target_receipt['amount_cash']+target_receipt['amount_online']:,.0f} payment from the member's ledger. They will owe this amount again.")
                        
                        if st.button("🗑️ Reverse & Delete Transaction"):
                            r_cash = float(target_receipt['amount_cash'])
                            r_online = float(target_receipt['amount_online'])
                            
                            if not pd.isna(target_receipt.get('emi_id')):
                                emi_id = int(target_receipt['emi_id'])
                                emi_row = emis_df[emis_df['id'] == emi_id].iloc[0]
                                
                                new_cash = max(0, float(emi_row.get('paid_cash', 0) or 0)) - r_cash
                                new_online = max(0, float(emi_row.get('paid_online', 0) or 0)) - r_online
                                expected = float(emi_row['total_expected'])
                                
                                new_status = 'Pending' if (new_cash + new_online) == 0 else ('Paid' if (new_cash + new_online) >= expected else 'Partial')
                                
                                supabase.table("emi_ledger").update({
                                    "status": new_status, "paid_cash": new_cash, "paid_online": new_online
                                }).eq("id", emi_id).execute()
                                
                            elif target_receipt['payment_type'] == "Savings":
                                target_sav_date = pd.to_datetime(target_receipt['logged_at'])
                                sav_to_delete = savings_df[(savings_df['member_id'] == target_receipt['member_id']) & 
                                                           (pd.to_datetime(savings_df['created_at']).dt.month == target_sav_date.month) &
                                                           (pd.to_datetime(savings_df['created_at']).dt.year == target_sav_date.year) &
                                                           (savings_df['amount'] == (r_cash + r_online))]
                                                           
                                if not sav_to_delete.empty:
                                    sav_id = int(sav_to_delete.iloc[-1]['id']) 
                                    supabase.table("savings_log").delete().eq("id", sav_id).execute()
                            
                            supabase.table("payment_receipts").delete().eq("id", int(target_receipt_id)).execute()
                            
                            clear_db_cache()
                            st.toast("✅ Transaction successfully reversed!", icon="🗑️")
                            st.rerun()
            else:
                st.info(f"No payments logged for the selected members in {selected_month_name} {target_year}.")
        else:
            st.info("No transaction history available yet.")