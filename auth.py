import streamlit as st
from database import supabase

def init_auth_state():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "profile" not in st.session_state:
        st.session_state["profile"] = None

def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            st.session_state["authenticated"] = True
            st.session_state["user"] = res.user
            
            # Fetch profile details (Role, full name)
            profile_res = supabase.table("profiles").select("*").eq("id", res.user.id).execute()
            if profile_res.data:
                st.session_state["profile"] = profile_res.data[0]
            return True, "Login successful"
        return False, "Authentication failed."
    except Exception as e:
        return False, str(e)

def logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    st.session_state["authenticated"] = False
    st.session_state["user"] = None
    st.session_state["profile"] = None
    st.rerun()

def render_login_page():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align: center; color: #34D399; font-size: 2.5rem;'>SANGAM FINANCE</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #94A3A0; margin-bottom: 2rem;'>Secure Financial Operations Desk</p>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            email = st.text_input("Email Address", placeholder="name@company.com")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            submit = st.form_submit_button("Sign In", type="primary", use_container_width=True)
            
            if submit:
                if not email or not password:
                    st.error("Please provide both email and password.")
                else:
                    success, message = login(email, password)
                    if success:
                        st.rerun()
                    else:
                        st.error("Access Denied: Incorrect email or password.")