import streamlit as st
import pandas as pd
from datetime import datetime
from database import supabase, fetch_table, clear_db_cache
from calculations import generate_emi_schedule

def render_admin(members_df):
    st.markdown("<h1 style='color:#34D399;'>⚙️ Admin & Configurations</h1>", unsafe_allow_html=True)
    
    # ADDED 4TH TAB FOR SUB-LOANS
    tab1, tab2, tab3, tab4 = st.tabs(["👥 Manage Members", "📜 Ledger View", "🧹 Danger Zone", "🤝 Sub-Loans (Splits)"])
    
    # Internal mappings needed for the dropdowns
    if not members_df.empty:
        id_to_name = dict(zip(members_df['id'], members_df['name']))
        member_dict = dict(zip(members_df['name'], members_df['id']))
    else:
        id_to_name = {}
        member_dict = {}
    
    with tab1:
        st.subheader("Sangam Members & Priority Queue")
        if not members_df.empty:
            members_display = members_df[['name', 'priority_order', 'total_savings']].rename(columns={'name': 'Name', 'priority_order': 'Priority Queue'})
            st.dataframe(members_display.style.format({'total_savings': '₹{:,.0f}'}, na_rep="₹0"), hide_index=True)
            
        with st.form("add_member"):
            m_name = st.text_input("New Member Name")
            m_queue = st.number_input("Priority Order Index", min_value=1, step=1)
            if st.form_submit_button("➕ Add Member") and m_name.strip():
                supabase.table("members").insert({"name": m_name.strip(), "priority_order": int(m_queue)}).execute()
                clear_db_cache()
                st.rerun()

    with tab2:
        st.subheader("Raw Data Ledgers")
        ledgers = fetch_table("emi_ledger")
        
        if not ledgers.empty:
            merged_ledger = pd.merge(ledgers, members_df[['id', 'name']], left_on='member_id', right_on='id', how='left')
            merged_ledger = merged_ledger.drop(columns=['id_y']).rename(columns={'id_x': 'id', 'name': 'Member Name'})
            
            cols = list(merged_ledger.columns)
            cols.insert(3, cols.pop(cols.index('Member Name')))
            merged_ledger = merged_ledger[cols]
            
            unique_members = sorted(merged_ledger['Member Name'].dropna().unique().tolist())
            selected_filter = st.selectbox("Filter by Member:", ["All"] + unique_members)
            
            if selected_filter != "All":
                display_ledger = merged_ledger[merged_ledger['Member Name'] == selected_filter]
            else:
                display_ledger = merged_ledger
                
            format_raw = {'principal_due': '₹{:,.0f}', 'interest_due': '₹{:,.0f}', 'total_expected': '₹{:,.0f}'}
            st.dataframe(display_ledger.style.format(format_raw), use_container_width=True, hide_index=True)
        else:
            st.info("No active ledgers.")

    with tab3:
        st.warning("⚠️ Operations here directly modify the core financial records.")
        loans_df = fetch_table("loans")
        
        if not loans_df.empty and not members_df.empty:
            loan_options = []
            loan_mapping = {}
            for _, row in loans_df.iterrows():
                owner_name = id_to_name.get(row['target_member_id'], 'Unknown')
                label = f"Loan #{row['id']} - {owner_name} (₹{row['total_amount']:,.0f})"
                loan_options.append(label)
                loan_mapping[label] = int(row['id'])
                
            s_loan = st.selectbox("Select Loan to Manage", ["-- Select --"] + loan_options)
            
            if s_loan != "-- Select --":
                target_loan_id = loan_mapping[s_loan]
                target_loan = loans_df[loans_df['id'] == target_loan_id].iloc[0]
                
                st.write("**Edit Loan Parameters**")
                st.info("💡 Updating these values will permanently replace the existing EMI schedule for this loan.")
                
                with st.form("edit_loan_form"):
                    c1, c2 = st.columns(2)
                    new_amount = c1.number_input("Total Amount (₹)", min_value=1000, step=500, value=int(target_loan['total_amount']))
                    new_part = c2.number_input("Part-Payment (₹)", min_value=0, max_value=int(new_amount), step=100, value=int(target_loan['part_payment_initial']))
                    
                    new_dur = c1.number_input("Duration (Months)", min_value=1, step=1, value=int(target_loan['duration_months']))
                    
                    try:
                        current_date = pd.to_datetime(target_loan['created_at']).date()
                    except Exception:
                        current_date = datetime.today().date()
                        
                    new_date = c2.date_input("Start Date", value=current_date)
                    
                    submit_c1, submit_c2 = st.columns(2)
                    
                    if submit_c1.form_submit_button("💾 Update & Regenerate EMIs"):
                        # 1. Update Loan Parameters
                        supabase.table("loans").update({
                            "total_amount": float(new_amount),
                            "part_payment_initial": float(new_part),
                            "duration_months": int(new_dur),
                            "created_at": new_date.strftime("%Y-%m-%d")
                        }).eq("id", target_loan_id).execute()
                        
                        # 2. Clear out the old flawed EMIs
                        supabase.table("emi_ledger").delete().eq("loan_id", target_loan_id).execute()
                        
                        # 3. Generate & Insert the corrected EMI matrix
                        schedule_df = generate_emi_schedule(target_loan_id, float(new_amount), float(new_part), int(new_dur), new_date)
                        schedule_df['member_id'] = int(target_loan['target_member_id'])
                        supabase.table("emi_ledger").insert(schedule_df.to_dict('records')).execute()
                        
                        clear_db_cache()
                        st.toast("✅ Loan updated and EMIs regenerated successfully!", icon="💾")
                        st.rerun()
                        
                    if submit_c2.form_submit_button("🗑️ Delete Loan Entirely"):
                        # Supabase Cascade Delete handles attached EMIs and Sub-loans automatically
                        supabase.table("loans").delete().eq("id", target_loan_id).execute()
                        clear_db_cache()
                        st.toast("✅ Loan removed permanently!", icon="🗑️")
                        st.rerun()
        else:
            st.info("No active loans available to manage.")

    with tab4:
        st.markdown("### 📝 Log & Manage Sub-Loans (Unofficial Splits)")
        st.write("Assign portions of a Master Loan to other members, or edit existing splits.")
        
        loans_df = fetch_table("loans")
        settlements_df = fetch_table("individual_settlement")
        
        if loans_df.empty or members_df.empty:
            st.warning("Please ensure active members and master loans exist before assigning sub-loans.")
        else:
            col_l1, col_l2 = st.columns(2)
            
            with col_l1:
                with st.expander("➕ Assign funds from a Master Loan", expanded=True):
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
                with st.expander("⚙️ Manage Existing Splits", expanded=True):
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