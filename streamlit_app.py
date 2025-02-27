import streamlit as st
import hashlib
from pyairtable import Table
import requests
import stripe
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
import uuid

# Streamlit configuration
st.set_page_config(page_title="Voice Agent Portal", page_icon="🎙️", layout="wide")
st.markdown("""
    <style>
    .stApp {
        background-color: #F5F7FA;
        color: #1A2B4A;
        font-family: 'Inter', sans-serif;
    }
    .stTextInput > div > div > input, .stTextArea > div > div > textarea {
        background-color: #FFFFFF;
        color: #1A2B4A;
        border: 1px solid #D1D9E0;
        border-radius: 8px;
        padding: 12px;
        box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.05);
    }
    .stButton > button {
        background-color: #00C4B4;
        color: #FFFFFF;
        border-radius: 8px;
        padding: 10px 20px;
        font-weight: 500;
        transition: background-color 0.2s, transform 0.1s;
    }
    .stButton > button:hover {
        background-color: #00A89A;
        transform: translateY(-1px);
    }
    .stButton > button[type="secondary"] {
        background-color: #6B7280;
    }
    .stButton > button[type="secondary"]:hover {
        background-color: #4B5563;
    }
    .sidebar .sidebar-content {
        background-color: #1A2B4A;
        color: #FFFFFF;
        padding: 20px;
        border-radius: 8px;
    }
    h1, h2, h3 {
        color: #1A2B4A;
    }
    .stats-card {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        text-align: center;
        margin: 10px 0;
    }
    .stats-title {
        font-size: 14px;
        color: #6B7280;
        margin-bottom: 8px;
    }
    .stats-value {
        font-size: 20px;
        font-weight: 600;
        color: #1A2B4A;
    }
    .content-card {
        background-color: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 15px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }
    </style>
""", unsafe_allow_html=True)

# Secrets
try:
    AIRTABLE_TOKEN = st.secrets["airtable"]["token"]
    AIRTABLE_BASE_ID = st.secrets["airtable"]["base_id"]
    AIRTABLE_USERS_TABLE = st.secrets["airtable"]["users_table"]
    AIRTABLE_AGENTS_TABLE = st.secrets["airtable"]["agents_table"]
    AIRTABLE_LOGS_TABLE = st.secrets["airtable"]["logs_table"]
    stripe.api_key = st.secrets["stripe"]["secret_key"]
except KeyError as e:
    st.error(f"Missing secret: {str(e)}. Please check your secrets configuration.")
    st.stop()

# Airtable clients
users_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_USERS_TABLE)
agents_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_AGENTS_TABLE)
logs_table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_LOGS_TABLE)

# Hash password
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Verify user
def verify_user(email, password):
    records = users_table.all(formula=f"{{Email}}='{email}'")
    if records and records[0]['fields'].get('Password') == hash_password(password):
        return True, records[0]['id']
    return False, None

# Create user
def create_user(email, password):
    if users_table.all(formula=f"{{Email}}='{email}'"):
        return False, "Email already exists"
    users_table.create({
        "Email": email,
        "Password": hash_password(password),
        "Subscription": "Free",
        "Tokens": 50,
        "LastReset": datetime.now(timezone.utc).isoformat()
    })
    return True, "Account created"

# Reset password (simulate email link with token)
def initiate_password_reset(email):
    records = users_table.all(formula=f"{{Email}}='{email}'")
    if not records:
        return False, "Email not found"
    user_id = records[0]['id']
    reset_token = str(uuid.uuid4())
    users_table.update(user_id, {"ResetToken": reset_token, "ResetTokenExpiry": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()})
    # In a real app, send email with reset link containing reset_token
    st.session_state['reset_token'] = reset_token  # Simulate for demo
    return True, f"Reset token generated: {reset_token} (Check your email in a real app)"

def reset_password(email, reset_token, new_password):
    records = users_table.all(formula=f"{{Email}}='{email}'")
    if not records:
        return False, "Email not found"
    user = records[0]
    stored_token = user['fields'].get('ResetToken')
    expiry = user['fields'].get('ResetTokenExpiry')
    if not stored_token or not expiry:
        return False, "No reset request found"
    expiry_date = datetime.fromisoformat(expiry)
    if stored_token == reset_token and datetime.now(timezone.utc) < expiry_date:
        users_table.update(user['id'], {"Password": hash_password(new_password), "ResetToken": "", "ResetTokenExpiry": ""})
        return True, "Password reset successfully"
    return False, "Invalid or expired token"

# Get subscription status
def get_subscription_status(user_id):
    record = users_table.get(user_id)
    sub_status = record['fields'].get('Subscription', 'Free')
    sub_end = record['fields'].get('SubscriptionEnd')
    if sub_status == "Premium" and sub_end:
        sub_end_date = datetime.fromisoformat(sub_end).replace(tzinfo=timezone.utc)
        if sub_end_date < datetime.now(timezone.utc):
            users_table.update(user_id, {"Subscription": "Free"})
            return "Free"
    return sub_status

# Get user data
def get_user_data(user_id):
    record = users_table.get(user_id)
    sub_status = record['fields'].get('Subscription', 'Free')
    tokens = record['fields'].get('Tokens', 0)
    last_reset = record['fields'].get('LastReset')
    company_name = record['fields'].get('CompanyName', '')
    
    if last_reset:
        last_reset_date = datetime.fromisoformat(last_reset).replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= last_reset_date + relativedelta(months=1):
            tokens = 50 if sub_status == "Free" else 200
            users_table.update(user_id, {
                "Tokens": tokens,
                "LastReset": datetime.now(timezone.utc).isoformat()
            })
    return sub_status, tokens, company_name

# Update subscription
def update_subscription(user_id, status, end_date=None):
    fields = {"Subscription": status}
    if end_date:
        fields["SubscriptionEnd"] = end_date.isoformat()
    users_table.update(user_id, fields)

# Update tokens
def update_tokens(user_id, token_change):
    current_tokens = get_user_data(user_id)[1]
    new_tokens = max(0, current_tokens + token_change)
    users_table.update(user_id, {"Tokens": new_tokens})
    return new_tokens

# Fetch agent stats
def get_agent_stats(user_id):
    return agents_table.all(formula=f"{{UserID}}='{user_id}'")

# Fetch call logs
def get_call_logs(user_id):
    return logs_table.all(formula=f"{{UserID}}='{user_id}'")

# Pages
def login_page():
    st.title("Login")
    with st.form(key='login_form'):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit_button = st.form_submit_button("Login")
        if submit_button:
            success, user_id = verify_user(email, password)
            if success:
                st.session_state['logged_in'] = True
                st.session_state['user_id'] = user_id
                st.session_state['user_email'] = email
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Invalid credentials")
    if st.button("Forgot Password?"):
        st.session_state['page'] = "Reset Password"
        st.rerun()

def create_account_page():
    st.title("Create Account")
    with st.form(key='create_form'):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        submit_button = st.form_submit_button("Sign Up")
        if submit_button:
            if password != confirm_password:
                st.error("Passwords don’t match")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters")
            else:
                success, message = create_user(email, password)
                if success:
                    st.success(message)
                else:
                    st.error(message)

def reset_password_page():
    st.title("Reset Password")
    email = st.text_input("Email")
    reset_token = st.text_input("Reset Token (from email)")
    new_password = st.text_input("New Password", type="password")
    if st.button("Reset Password"):
        success, message = reset_password(email, reset_token, new_password)
        if success:
            st.success(message)
            st.session_state['page'] = "Login"
            st.rerun()
        else:
            st.error(message)
    if st.button("Request Reset Token"):
        success, message = initiate_password_reset(email)
        if success:
            st.success(message)  # In production, this would be an email
        else:
            st.error(message)
    if st.button("Back to Login"):
        st.session_state['page'] = "Login"
        st.rerun()

def dashboard_page():
    st.title("Dashboard")
    user_id = st.session_state['user_id']
    sub_status, tokens, company_name = get_user_data(user_id)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f'<div class="stats-card"><div class="stats-title">Active Agents</div><div class="stats-value">{len(get_agent_stats(user_id))}</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stats-card"><div class="stats-title">Tokens Available</div><div class="stats-value">{tokens}</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="stats-card"><div class="stats-title">Plan</div><div class="stats-value">{sub_status}</div></div>', unsafe_allow_html=True)
    
    st.subheader("Recent Call Logs")
    logs = get_call_logs(user_id)[:5]  # Show last 5 logs
    for log in logs:
        fields = log['fields']
        st.markdown(f'<div class="content-card">Call at {fields.get("Timestamp", "N/A")} - Duration: {fields.get("Duration", "N/A")}s - Status: {fields.get("Status", "N/A")}</div>', unsafe_allow_html=True)

def stats_page():
    st.title("Agent Stats")
    user_id = st.session_state['user_id']
    agents = get_agent_stats(user_id)
    for agent in agents:
        fields = agent['fields']
        st.markdown(f'<div class="content-card">Agent: {fields.get("Name", "Unnamed")} - Calls: {fields.get("CallCount", 0)} - Success Rate: {fields.get("SuccessRate", "N/A")}%</div>', unsafe_allow_html=True)

def logs_page():
    st.title("Call Logs")
    user_id = st.session_state['user_id']
    logs = get_call_logs(user_id)
    for log in logs:
        fields = log['fields']
        st.markdown(f'<div class="content-card">Call at {fields.get("Timestamp", "N/A")} - Agent: {fields.get("AgentName", "N/A")} - Duration: {fields.get("Duration", "N/A")}s - Status: {fields.get("Status", "N/A")}</div>', unsafe_allow_html=True)

def billing_page():
    st.title("Billing")
    user_id = st.session_state['user_id']
    sub_status, tokens, _ = get_user_data(user_id)

    if sub_status == "Free":
        if st.button("Upgrade to Premium ($20/month)"):
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {'name': 'Premium Voice Plan'},
                        'unit_amount': 2000,
                        'recurring': {'interval': 'month'}
                    },
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=f"https://your-app.streamlit.app/?success=true&user_id={user_id}&email={st.session_state['user_email']}",
                cancel_url=f"https://your-app.streamlit.app/?cancel=true&email={st.session_state['user_email']}",
                client_reference_id=user_id
            )
            st.markdown(f'<a href="{session.url}" target="_blank">Go to Checkout</a>', unsafe_allow_html=True)
    else:
        st.success("You’re on the Premium plan!")

    st.subheader("Buy Tokens")
    token_amount = st.selectbox("Select tokens", [50, 100, 200])
    token_cost = token_amount // 10
    if st.button(f"Buy {token_amount} Tokens (${token_cost})"):
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': f"{token_amount} Tokens"},
                    'unit_amount': token_cost * 100,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"https://your-app.streamlit.app/?token_success=true&user_id={user_id}&tokens={token_amount}&email={st.session_state['user_email']}",
            cancel_url=f"https://your-app.streamlit.app/?cancel=true&email={st.session_state['user_email']}",
            client_reference_id=user_id
        )
        st.markdown(f'<a href="{session.url}" target="_blank">Go to Checkout</a>', unsafe_allow_html=True)

def settings_page():
    st.title("Settings")
    user_id = st.session_state['user_id']
    _, _, company_name = get_user_data(user_id)
    with st.form(key='settings_form'):
        new_company_name = st.text_input("Company Name", value=company_name)
        if st.form_submit_button("Save"):
            users_table.update(user_id, {"CompanyName": new_company_name})
            st.success("Settings updated!")

# Main
def main():
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
    if 'page' not in st.session_state:
        st.session_state['page'] = "Login"

    query_params = st.query_params
    if query_params.get("success") == "true" and query_params.get("user_id"):
        update_subscription(query_params["user_id"], "Premium", datetime.now(timezone.utc) + timedelta(days=30))
        update_tokens(query_params["user_id"], 200 - 50)
        st.success("Subscription upgraded!")
        st.query_params.clear()
    elif query_params.get("token_success") == "true" and query_params.get("user_id"):
        update_tokens(query_params["user_id"], int(query_params["tokens"]))
        st.success(f"Added {query_params['tokens']} tokens!")
        st.query_params.clear()

    if not st.session_state['logged_in']:
        tab1, tab2 = st.tabs(["Login", "Create Account"])
        with tab1:
            login_page()
        with tab2:
            create_account_page()
        if st.session_state.get('page') == "Reset Password":
            reset_password_page()
    else:
        with st.sidebar:
            st.markdown("<h2 style='color: #FFFFFF;'>Voice Agent Portal</h2>", unsafe_allow_html=True)
            user_id = st.session_state['user_id']
            sub_status, tokens, company_name = get_user_data(user_id)
            st.write(f"**Company**: {company_name or 'N/A'}")
            st.write(f"**Plan**: {sub_status}")
            st.write(f"**Tokens**: {tokens}")

            if st.button("🏠 Dashboard"):
                st.session_state['page'] = "Dashboard"
                st.rerun()
            if st.button("📊 Stats"):
                st.session_state['page'] = "Stats"
                st.rerun()
            if st.button("📜 Logs"):
                st.session_state['page'] = "Logs"
                st.rerun()
            if st.button("💳 Billing"):
                st.session_state['page'] = "Billing"
                st.rerun()
            if st.button("⚙️ Settings"):
                st.session_state['page'] = "Settings"
                st.rerun()
            if st.button("🚪 Logout"):
                st.session_state.pop('logged_in')
                st.session_state.pop('user_id')
                st.session_state.pop('user_email')
                st.rerun()

        page = st.session_state['page']
        if page == "Dashboard":
            dashboard_page()
        elif page == "Stats":
            stats_page()
        elif page == "Logs":
            logs_page()
        elif page == "Billing":
            billing_page()
        elif page == "Settings":
            settings_page()

if __name__ == "__main__":
    main()