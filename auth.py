import streamlit as st
from database import supabase
from streamlit_cookies_controller import CookieController

# 1. Initialize the browser cookie manager
cookie_controller = CookieController()

def init_auth_state():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "profile" not in st.session_state:
        st.session_state["profile"] = None

    # 2. Check for a saved login cookie if the memory was wiped
    if not st.session_state["authenticated"]:
        access_token = cookie_controller.get('sangam_auth_token')
        
        if access_token:
            try:
                # Securely verify the saved token directly with Supabase
                user_resp = supabase.auth.get_user(access_token)
                if user_resp and user_resp.user:
                    st.session_state["authenticated"] = True
                    st.session_state["user"] = user_resp.user
                    
                    # Re-fetch the user's role profile
                    profile_res = supabase.table("profiles").select("*").eq("id", user_resp.user.id).execute()
                    if profile_res.data:
                        st.session_state["profile"] = profile_res.data[0]
            except Exception:
                # If the 1-day token expired or is invalid, destroy the cookie
                cookie_controller.remove('sangam_auth_token')

def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user and res.session:
            st.session_state["authenticated"] = True
            st.session_state["user"] = res.user
            
            profile_res = supabase.table("profiles").select("*").eq("id", res.user.id).execute()
            if profile_res.data:
                st.session_state["profile"] = profile_res.data[0]
            
            # 3. Save the secure token to the browser cookie for 1 Day (86400 seconds)
            cookie_controller.set('sangam_auth_token', res.session.access_token, max_age=86400)
            
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
    
    # 4. Destroy the cookie so it doesn't auto-login again
    cookie_controller.remove('sangam_auth_token')
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