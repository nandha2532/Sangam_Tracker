import streamlit as st
import pandas as pd
import calendar
from datetime import datetime
from database import supabase, fetch_table, clear_db_cache

def render_collection_desk(members_df, member_dict, global_target_date):
    st.markdown("<h1 style='color:#34D399;'>💰 Meeting Day Collection Desk</h1>", unsafe_allow_html=True)
    
    emis_df = fetch_table("emi_ledger")
    savings_df = fetch_table("savings_log")
    receipts_df = fetch_table("payment_receipts")
    
    if not receipts_df.empty:
        receipts_df['logged_at'] = pd.to_datetime(receipts_df['logged_at'])
    
    # --- USE THE GLOBAL DATE ---
    target_year = global_target_date.year
    target_month = global_target_date.month
    selected_month_name = calendar.month_name[target_month]
    target_log_date = global_target_date.strftime("%Y-%m-%d")
    
    st.info(f"🗓️ Currently viewing and logging data for: **{selected_month_name} {target_year}** (Set via Sidebar)")
    
    # ==========================================
    # 🏦 TREASURY SUMMARY (GRAND TOTALS)
    # ==========================================
    st.divider()
    st.markdown(f"### 🏦 Treasury Summary ({selected_month_name} {target_year})")
    
    if not receipts_df.empty:
        monthly_receipts = receipts_df[(receipts_df['logged_at'].dt.month == target_month) & 
                                       (receipts_df['logged_at'].dt.year == target_year)]
                                       
        global_cash = monthly_receipts['amount_cash'].sum()
        global_online = monthly_receipts['amount_online'].sum()
        global_total = global_cash + global_online
        
        v1, v2, v3 = st.columns(3)
        v1.metric("💵 Total Cash in Hand", f"₹{global_cash:,.0f}")
        v2.metric("📱 Total Bank Balance", f"₹{global_online:,.0f}")
        v3.metric("🎯 Monthly Grand Total", f"₹{global_total:,.0f}")
    else:
        st.info("No payments have been logged yet.")

    # --- QUICK FILTERS ---
    st.markdown("### 🔎 Quick Filters")
    show_pending_only = st.checkbox("Hide fully paid members", value=False)
    
    meeting_data_sav = []
    meeting_data_emi = []
    
    for _, member in members_df.iterrows():
        m_id = member['id']
        m_name = member['name']
        
        # =======================================
        # 1. SAVINGS CALCULATIONS
        # =======================================
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
                "Member_ID": m_id,
                "Name": m_name,
                "Expected": savings_expected,
                "Already Paid": savings_already_paid,
                "Remaining Due": sav_remaining,
                "Full Cash (₹500)": False,
                "Full Online (₹500)": False,
                "Custom Cash": 0.0,
                "Custom Online": 0.0
            })

        # =======================================
        # 2. EMI CALCULATIONS
        # =======================================
        emi_expected = 0.0
        emi_already_paid = 0.0
        
        if not emis_df.empty:
            emis_df['pay_date'] = pd.to_datetime(emis_df['pay_date'])
            relevant_emis = emis_df[(emis_df['member_id'] == m_id) & 
                                    (((emis_df['pay_date'].dt.year == target_year) & (emis_df['pay_date'].dt.month == target_month)) | 
                                     (((emis_df['pay_date'].dt.year < target_year) | ((emis_df['pay_date'].dt.year == target_year) & (emis_df['pay_date'].dt.month < target_month))) & (emis_df['status'] != 'Paid')))]
            
            for _, row in relevant_emis.iterrows():
                emi_expected += float(row['total_expected'])
                emi_already_paid += float(row.get('paid_cash', 0)) + float(row.get('paid_online', 0))
                
        emi_remaining = max(0, emi_expected - emi_already_paid)
        
        if not (show_pending_only and emi_remaining <= 0):
            meeting_data_emi.append({
                "Member_ID": m_id,
                "Name": m_name,
                "Expected": emi_expected,
                "Already Paid": emi_already_paid,
                "Remaining Due": emi_remaining,
                "New Cash": 0.0,
                "New Online": 0.0
            })
            
    df_sav = pd.DataFrame(meeting_data_sav)
    df_emi = pd.DataFrame(meeting_data_emi)
    
    def highlight_paid(row):
        if row['Remaining Due'] <= 0:
            return ['background-color: #18201D; color: #22C55E; font-weight: bold'] * len(row)
        return [''] * len(row)

    # Global Validation Flag
    validation_failed = False

    # ==========================================
    # UI: TABLE 1 - SAVINGS
    # ==========================================
    st.markdown("### 🟢 1. Monthly Savings Collection (₹500)")
    
    edited_sav = pd.DataFrame()
    if not df_sav.empty:
        styled_sav = df_sav.style.apply(highlight_paid, axis=1)
        edited_sav = st.data_editor(
            styled_sav,
            disabled=["Member_ID", "Name", "Expected", "Already Paid", "Remaining Due"],
            column_config={
                "Member_ID": None, 
                "Expected": st.column_config.NumberColumn(format="₹%d"),
                "Already Paid": st.column_config.NumberColumn(format="₹%d"),
                "Remaining Due": st.column_config.NumberColumn(format="₹%d"),
                "Full Cash (₹500)": st.column_config.CheckboxColumn("Full Cash ✅"),
                "Full Online (₹500)": st.column_config.CheckboxColumn("Full Bank ✅"),
                "Custom Cash": st.column_config.NumberColumn("Custom Cash (₹)", format="₹%d", min_value=0),
                "Custom Online": st.column_config.NumberColumn("Custom Bank (₹)", format="₹%d", min_value=0)
            },
            use_container_width=True, hide_index=True, key="sav_editor"
        )
        
        # --- INSTANT VALIDATION ---
        sav_errors = []
        for _, row in edited_sav.iterrows():
            is_full_cash = row.get('Full Cash (₹500)', False)
            is_full_online = row.get('Full Online (₹500)', False)
            cust_cash = float(row.get('Custom Cash', 0.0))
            cust_online = float(row.get('Custom Online', 0.0))
            
            if is_full_cash or is_full_online or cust_cash > 0 or cust_online > 0:
                if is_full_cash and is_full_online:
                    sav_errors.append(f"❌ **{row['Name']}**: Both 'Full Cash' and 'Full Bank' are checked. For split payments, leave checkboxes empty and use the Custom columns.")
                    validation_failed = True
                elif (is_full_cash or is_full_online) and (cust_cash > 0 or cust_online > 0):
                    sav_errors.append(f"❌ **{row['Name']}**: Do not mix checkboxes with custom amounts. Use EITHER the checkboxes OR the Custom columns.")
                    validation_failed = True
                elif (cust_cash + cust_online) > 500.0:
                    sav_errors.append(f"❌ **{row['Name']}**: Custom savings total entered is ₹{cust_cash + cust_online}. The maximum allowed is ₹500.")
                    validation_failed = True

        if sav_errors:
            for err in sav_errors:
                st.error(err)
    else:
        st.success("All visible Savings dues are clear!")

    # ==========================================
    # UI: TABLE 2 - EMIs
    # ==========================================
    st.markdown("### 🔵 2. Loan EMI Collection")
    edited_emi = pd.DataFrame()
    if not df_emi.empty:
        styled_emi = df_emi.style.apply(highlight_paid, axis=1)
        edited_emi = st.data_editor(
            styled_emi,
            disabled=["Member_ID", "Name", "Expected", "Already Paid", "Remaining Due"],
            column_config={
                "Member_ID": None, 
                "Expected": st.column_config.NumberColumn(format="₹%d"),
                "Already Paid": st.column_config.NumberColumn(format="₹%d"),
                "Remaining Due": st.column_config.NumberColumn(format="₹%d"),
                "New Cash": st.column_config.NumberColumn("Cash Paid (₹)", format="₹%d", min_value=0),
                "New Online": st.column_config.NumberColumn("Bank Paid (₹)", format="₹%d", min_value=0)
            },
            use_container_width=True, hide_index=True, key="emi_editor"
        )
    else:
        st.success("All visible EMI dues are clear!")

    # ==========================================
    # EXTRACT STAGED ROWS (Zero-Click Staging)
    # ==========================================
    to_commit_sav_list = []
    if not edited_sav.empty and not validation_failed:
        for _, row in edited_sav.iterrows():
            is_full_cash = row.get('Full Cash (₹500)', False)
            is_full_online = row.get('Full Online (₹500)', False)
            cust_cash = float(row.get('Custom Cash', 0.0))
            cust_online = float(row.get('Custom Online', 0.0))
            
            if is_full_cash or is_full_online or cust_cash > 0 or cust_online > 0:
                to_commit_sav_list.append(row)
                
    to_commit_sav = pd.DataFrame(to_commit_sav_list)

    to_commit_emi_list = []
    if not edited_emi.empty and not validation_failed:
        for _, row in edited_emi.iterrows():
            if float(row.get('New Cash', 0.0)) > 0 or float(row.get('New Online', 0.0)) > 0:
                to_commit_emi_list.append(row)
                
    to_commit_emi = pd.DataFrame(to_commit_emi_list)

    # ==========================================
    # DRAFT TOTALS 
    # ==========================================
    st.markdown("### ⚖️ Uncommitted Session Draft")
    
    draft_sav_cash = 0
    draft_sav_online = 0
    if not to_commit_sav.empty:
        for _, r in to_commit_sav.iterrows():
            draft_sav_cash += 500.0 if r['Full Cash (₹500)'] else float(r['Custom Cash'])
            draft_sav_online += 500.0 if r['Full Online (₹500)'] else float(r['Custom Online'])
            
    draft_emi_cash = to_commit_emi['New Cash'].sum() if not to_commit_emi.empty else 0
    draft_emi_online = to_commit_emi['New Online'].sum() if not to_commit_emi.empty else 0
    
    total_cash_box = draft_sav_cash + draft_emi_cash
    total_bank = draft_sav_online + draft_emi_online
    grand_total = total_cash_box + total_bank
    
    c1, c2, c3 = st.columns(3)
    c1.metric("💵 Draft Cash Box", f"₹{total_cash_box:,.0f}")
    c2.metric("📱 Draft Bank Transfers", f"₹{total_bank:,.0f}")
    c3.metric("🎯 Draft Total", f"₹{grand_total:,.0f}")
    
    st.markdown("### 💾 Finalize & Save Transactions")
    
    if validation_failed:
        st.warning("⚠️ Please fix the errors in the tables above before saving. The save button is temporarily disabled.")
        
    if st.button(f"🔒 Lock Entered Payments for {target_log_date}", type="primary", disabled=validation_failed):
        
        commits_made = False
        
        if to_commit_sav.empty and to_commit_emi.empty:
            st.error("No payments entered. Enter amounts in the grids above to commit.")
        else:
            # 1. PROCESS SAVINGS COMMITS
            if not to_commit_sav.empty:
                for _, row in to_commit_sav.iterrows():
                    m_id = int(row['Member_ID'])
                    
                    cash = 500.0 if row['Full Cash (₹500)'] else float(row['Custom Cash'])
                    online = 500.0 if row['Full Online (₹500)'] else float(row['Custom Online'])
                    
                    if (cash + online) > 0:
                        supabase.table("savings_log").insert({
                            "member_id": m_id,
                            "amount": cash + online,
                            "payment_mode": "Split" if cash > 0 and online > 0 else ("Cash" if cash > 0 else "Online"),
                            "created_at": target_log_date
                        }).execute()
                        
                        supabase.table("payment_receipts").insert({
                            "member_id": m_id, "payment_type": "Savings", "amount_cash": cash, "amount_online": online, "logged_at": target_log_date
                        }).execute()
                        commits_made = True

            # 2. PROCESS EMI COMMITS
            if not to_commit_emi.empty:
                for _, row in to_commit_emi.iterrows():
                    m_id = int(row['Member_ID'])
                    cash = float(row['New Cash'])
                    online = float(row['New Online'])
                    
                    if (cash + online) > 0:
                         pending = emis_df[(emis_df['member_id'] == m_id) & 
                                          (emis_df['status'].isin(['Pending', 'Partial'])) & 
                                          (emis_df['pay_date'].dt.month <= target_month) &
                                          (emis_df['pay_date'].dt.year <= target_year)]
                         
                         pending = pending.sort_values(by='pay_date')
                         
                         for idx, emi_row in pending.iterrows():
                             if cash + online <= 0:
                                 break
                                 
                             emi_id = int(emi_row['id'])
                             expected = float(emi_row['total_expected'])
                             current_paid_cash = float(emi_row.get('paid_cash', 0))
                             current_paid_online = float(emi_row.get('paid_online', 0))
                             
                             remaining_for_this_emi = expected - (current_paid_cash + current_paid_online)
                             
                             if remaining_for_this_emi <= 0:
                                 continue
                                 
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
                                
                                new_cash = max(0, float(emi_row.get('paid_cash', 0)) - r_cash)
                                new_online = max(0, float(emi_row.get('paid_online', 0)) - r_online)
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