import streamlit as st
import pandas as pd
from database import supabase, fetch_table, clear_db_cache

def render_admin(members_df):
    st.markdown("<h1 style='color:#2c3e50;'>Admin & Configurations</h1>", unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["👥 Manage Members", "📜 Ledger View", "🧹 Danger Zone"])
    
    with tab1:
        st.subheader("Sangam Members & Priority Queue")
        if not members_df.empty:
            members_display = members_df[['name', 'priority_order', 'total_savings']].rename(columns={'name': 'Name', 'priority_order': 'Priority Queue'})
            # FIXED: Format total savings
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
                
            # FIXED: Removed decimals from raw database view
            format_raw = {'principal_due': '₹{:,.0f}', 'interest_due': '₹{:,.0f}', 'total_expected': '₹{:,.0f}'}
            st.dataframe(display_ledger.style.format(format_raw), use_container_width=True, hide_index=True)
        else:
            st.info("No active ledgers.")

    with tab3:
        st.warning("⚠️ Operations here cannot be undone.")
        if not ledgers.empty:
            with st.form("wipe_loan"):
                l_id = st.number_input("Enter Loan ID to Erase", min_value=1, step=1)
                if st.form_submit_button("🗑️ Erase Loan & Associated EMIs"):
                    supabase.table("loans").delete().eq("id", int(l_id)).execute()
                    clear_db_cache()
                    st.rerun()