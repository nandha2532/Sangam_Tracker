import streamlit as st
import pandas as pd
from datetime import datetime

# --- IMPORT MODULES ---
from auth import init_auth_state, render_login_page, logout
from database import supabase, fetch_table, get_members, clear_db_cache
from dashboard import render_dashboard
from admin_configs import render_admin
from settlement_dashboard import render_settlement
from collection_desk import render_collection_desk

st.set_page_config(page_title="Sangam Tracker", page_icon="🤝", layout="wide", initial_sidebar_state="expanded")

# --- SANGAM FINANCE DARK THEME CSS ---
st.markdown("""
<style>
    .stApp { background-color: #0B0F0E; color: #F5F7F6; }
    [data-testid="stSidebar"] { background-color: #121817; border-right: 1px solid #26332F; }
    div.stButton > button[kind="primary"] { background-color: #34D399 !important; color: #0B0F0E !important; font-weight: 700 !important; border: none !important; transition: background-color 0.2s ease; }
    div.stButton > button[kind="primary"]:hover { background-color: #6EE7B7 !important; }
    .metric-card { background-color: #18201D; border: 1px solid #26332F; border-radius: 8px; padding: 1.2rem; }
    div[data-testid="stDataEditor"] { background-color: #121817; border: 1px solid #26332F; border-radius: 8px; }
    .section-header { color: #F5F7F6; border-left: 3px solid #34D399; padding-left: 10px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. SECURITY GATEKEEPER
# ==========================================
init_auth_state()

if not st.session_state["authenticated"]:
    render_login_page()
    st.stop() # Stops the rest of the code from running until logged in!

# ==========================================
# 2. EXTRACT USER PROFILE
# ==========================================
user_profile = st.session_state.get("profile", {})
user_role = user_profile.get("role", "admin") # Defaulting to admin temporarily if profile fetch fails
user_name = user_profile.get("full_name", "Team Member")

# ==========================================
# 3. LOAD APPLICATION DATA
# ==========================================
members_df = get_members()
member_names = members_df['name'].tolist() if not members_df.empty else []
member_dict = dict(zip(members_df['name'], members_df['id'])) if not members_df.empty else {}

# ==========================================
# 4. SIDEBAR & NAVIGATION (Role-Based Access)
# ==========================================
# (Make sure to default to 'viewer' if no role is found)
user_role = user_profile.get("role", "viewer") 

st.sidebar.markdown(f"**👤 {user_name}**<br><span style='color:#94A3A0; font-size:0.8rem;'>ROLE: {user_role.upper()}</span>", unsafe_allow_html=True)
if st.sidebar.button("🚪 Sign Out", use_container_width=True):
    logout()
st.sidebar.divider()

st.sidebar.markdown("<h2 style='text-align: center; color: #34D399;'>Control Panel</h2>", unsafe_allow_html=True)

st.sidebar.markdown("### 📅 Global Time Context")
global_target_date = st.sidebar.date_input("Select Working Date", datetime.today())
st.sidebar.divider()

st.sidebar.markdown("### Navigation")

# --- STRICT ROLE-BASED ACCESS CONTROL ---
# 1. Viewers (New Accounts) ONLY get the read-only dashboard
available_pages = ["📱 Actionable Dashboard"]

# 2. Collectors, Managers, and Admins get the Collection Desk
if user_role in ["collector", "manager", "admin"]:
    available_pages.append("💰 Collection Desk")

# 3. Managers and Admins get Settlements
if user_role in ["manager", "admin"]:
    available_pages.append("🤝 Individual Settlements")

# 4. Only Admins get Configurations
if user_role == "admin":
    available_pages.append("⚙️ Admin & Configs")

nav_selection = st.sidebar.radio("", available_pages)

# ==========================================
# 5. PAGE ROUTING
# ==========================================
if nav_selection == "📱 Actionable Dashboard":
    render_dashboard(members_df, member_dict, global_target_date) 

elif nav_selection == "💰 Collection Desk":
    render_collection_desk(members_df, member_dict, global_target_date)

elif nav_selection == "⚙️ Admin & Configs":
    render_admin(members_df)

elif nav_selection == "🤝 Individual Settlements":
    render_settlement(members_df, member_dict, global_target_date)