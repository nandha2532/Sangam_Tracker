import streamlit as st
import pandas as pd
from database import supabase, fetch_table, get_members, clear_db_cache
from dashboard import render_dashboard
from admin_configs import render_admin
from settlement_dashboard import render_settlement

st.set_page_config(page_title="Sangam Tracker", page_icon="🤝", layout="wide", initial_sidebar_state="expanded")

# --- PREMIUM SAAS CSS ---
st.markdown("""
    <style>
        .main { background-color: #F8FAFC; font-family: 'Inter', 'Segoe UI', Helvetica, sans-serif; }
        .card { background-color: #FFFFFF; padding: 24px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); border: 1px solid #E2E8F0; margin-bottom: 20px; }
        .card-green { border-top: 4px solid #10B981; }
        .card-red { border-top: 4px solid #EF4444; }
        .card-purple { border-top: 4px solid #6366F1; }
        .card-title { font-size: 0.75rem; color: #64748B; text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em; }
        .card-value { font-size: 2.25rem; font-weight: 800; color: #0F172A; margin-top: 8px; }
        .section-header { font-size: 1.15rem; color: #0F172A; font-weight: 700; margin-bottom: 20px; display: flex; align-items: center; }
        .section-header::before { content: ""; display: inline-block; width: 4px; height: 20px; background-color: #4F46E5; border-radius: 4px; margin-right: 12px; }
    </style>
""", unsafe_allow_html=True)

members_df = get_members()
member_names = members_df['name'].tolist() if not members_df.empty else []
member_dict = dict(zip(members_df['name'], members_df['id'])) if not members_df.empty else {}

# --- SIDEBAR NAVIGATION ---
st.sidebar.markdown("<h2 style='color:#0F172A;'>Control Panel</h2>", unsafe_allow_html=True)
nav_selection = st.sidebar.radio("Navigation", ["📱 Actionable Dashboard", "⚙️ Admin & Configs", "🤝 Individual Settlements"])
st.sidebar.divider()

# Sidebar: Quick Log Monthly 500
with st.sidebar.expander("⚡ Log Monthly ₹500 Savings"):
    with st.form("quick_savings_form", clear_on_submit=True):
        if member_names:
            s_member = st.selectbox("Select Member", member_names)
            s_date = st.date_input("Date")
            if st.form_submit_button("🚀 Log Savings"):
                supabase.table("savings_log").insert({
                    "member_id": int(member_dict[s_member]), 
                    "amount": 500, 
                    "date": s_date.strftime("%Y-%m-%d"), 
                    "status": 'Paid'
                }).execute()
                clear_db_cache()
                st.toast(f"✅ ₹500 logged for {s_member}!", icon="💰")
                st.rerun()
        else:
            st.info("Add members in Admin panel first.")

# --- ROUTER CORE ---
if nav_selection == "📱 Actionable Dashboard":
    render_dashboard(members_df, member_dict)
elif nav_selection == "⚙️ Admin & Configs":
    render_admin(members_df)
elif nav_selection == "🤝 Individual Settlements":
    render_settlement(members_df, member_dict)