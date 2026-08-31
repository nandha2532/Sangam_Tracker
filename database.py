import streamlit as st
from supabase import create_client
import pandas as pd

# --- Supabase Setup & Connection ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Memory Management ---
def clear_db_cache():
    """Wipes the Streamlit memory so fresh data can be fetched immediately after a database write."""
    st.cache_data.clear()

# --- Helper Functions ---
@st.cache_data(ttl=300)
def fetch_table(table_name):
    try:
        response = supabase.table(table_name).select("*").execute()
        return pd.DataFrame(response.data) if response.data else pd.DataFrame()
    except Exception as e:
        st.error(f"Error fetching {table_name}: {e}")
        return pd.DataFrame()

def get_members():
    members = fetch_table("members")
    if not members.empty and 'priority_order' in members.columns:
        members = members.sort_values('priority_order')
    return members