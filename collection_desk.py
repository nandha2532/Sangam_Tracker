import streamlit as st
import pandas as pd
import calendar
from datetime import datetime
from database import supabase, fetch_table, clear_db_cache
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode

# IMPORT THE NEW COMPONENT
from settlement_dashboard import render_individual_settlement

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
    # MASTER DESK: QUICK FILTERS
    # ==========================================
    st.divider()
    st.markdown("### 🔎 Quick Filters")
    # This single checkbox now controls Settlements, EMIs, and Savings visibility globally.
    show_pending_only = st.checkbox("Hide fully paid members & loans", value=False)
    
    if st.button("🧹 Clear All Staged Allocations"):
        st.session_state['prefill_emi'] = {}
        st.session_state['form_reset_key'] += 1
        st.rerun()

    # ==========================================
    # 📊 INDIVIDUAL SETTLEMENT STATEMENT & ALLOCATOR 
    # ==========================================
    # Pass the 'show_pending_only' value down so the component knows what to hide
    render_individual_settlement(member_dict, target_year, target_month, target_date_obj, id_to_name, emis_df, loans_df, settlements_df, show_pending_only)

    # ==========================================
    # DATA PREP FOR AG-GRIDS
    # ==========================================
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
    st.divider()
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