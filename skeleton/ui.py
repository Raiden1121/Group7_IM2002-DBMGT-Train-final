"""
TransitFlow — Gradio Web Interface
====================================
Run with:  python skeleton/ui.py
Then open: http://localhost:7860

Students: You do NOT need to change this file.
"""

import sys
sys.path.insert(0, ".")

import html
import gradio as gr
import uvicorn
from authlib.integrations.base_client.errors import MismatchingStateError
from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from skeleton.agent import run_agent
from skeleton.llm_provider import llm
from skeleton.config import (
    GEMINI_CHAT_MODEL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    OLLAMA_CHAT_MODEL,
    SESSION_SECRET_KEY,
)
from databases.relational.queries import (
    complete_google_signup,
    login_or_create_google_user,
    login_user,
    query_user_profile,
    register_user,
    get_user_secret_question,
    verify_secret_answer,
    update_password,
)

SECRET_QUESTIONS = [
    "What is the name of your first pet?",
    "What is your mother's maiden name?",
    "What city were you born in?",
    "What was the name of your first school?",
    "What is your favourite book?",
    "What was the make of your first car?",
]


# ── Google OAuth setup ────────────────────────────────────────────────────────

GOOGLE_OAUTH_SCOPES = ["openid", "email", "profile"]

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": " ".join(GOOGLE_OAUTH_SCOPES)},
)


GOOGLE_BUTTON_CSS = """
.google-signin-button {
    align-items: center;
    background: #ffffff;
    border: 1px solid #747775;
    border-radius: 4px;
    box-sizing: border-box;
    color: #1f1f1f;
    display: inline-flex;
    font-family: Roboto, Arial, sans-serif;
    font-size: 14px;
    font-weight: 500;
    height: 40px;
    justify-content: center;
    line-height: 20px;
    padding: 0 12px;
    text-decoration: none;
    width: 100%;
}

.login-action-row {
    align-items: stretch;
}

.login-action-row > * {
    flex: 1 1 0;
    min-width: 0;
}

.login-action-row button,
.login-action-row .google-signin-button {
    height: 40px;
    min-height: 40px;
    max-height: 40px;
    padding: 0 12px;
    font-size: 14px;
    line-height: 20px;
    width: 100%;
}

.login-action-row > .block.padded.hide-container.auto-margin {
    flex: 1 1 0 !important;
    min-width: 0 !important;
    width: 100% !important;
}

.login-action-row .html-container {
    align-items: stretch;
    display: flex;
    flex: 1 1 0;
    height: 40px;
    margin: 0;
    min-height: 40px;
    overflow: visible;
    padding: 0;
    width: 100%;
}

.login-action-row .html-container .prose {
    align-items: stretch;
    display: flex;
    flex: 1 1 0;
    height: 100%;
    margin: 0;
    max-width: none;
    min-height: 40px;
    padding: 0;
    width: 100%;
}

.login-action-row .html-container .prose > * {
    width: 100%;
}

.login-action-row .google-signin-button {
    align-self: stretch;
    display: flex;
    justify-content: center;
    margin-left: -12px;
    margin-right: -12px;
    width: calc(100% + 24px);
}

.login-action-row .google-signin-button__text {
    overflow: visible;
    text-overflow: clip;
    white-space: nowrap;
}

.google-signin-button:hover {
    background: #f8fafd;
    box-shadow: inset 0 0 0 9999px rgba(66, 133, 244, 0.04);
    color: #1f1f1f;
    text-decoration: none;
}

.google-signin-button:focus {
    box-shadow: 0 0 0 2px rgba(66, 133, 244, 0.35);
    outline: none;
}

.google-signin-button__icon {
    flex: 0 0 auto;
    height: 18px;
    margin-right: 10px;
    width: 18px;
}

.google-signin-button__text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

#auth_header {
    min-width: 280px;
    position: relative;
    z-index: 20;
}

.user-info-badge {
    background: #f9fafb;
    color: #1f2937;
    font-size: 14px;
    font-weight: 500;
    line-height: 20px;
    min-height: 24px;
    padding-bottom: 8px;
    position: relative;
    text-align: right;
    z-index: 21;
}

.user-info-badge strong {
    font-weight: 700;
}
"""

GOOGLE_SIGNIN_BUTTON_HTML = """
<a class="google-signin-button" href="/auth/google/login" aria-label="Continue with Google">
    <svg class="google-signin-button__icon" viewBox="0 0 18 18" aria-hidden="true">
        <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62z"/>
        <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18z"/>
        <path fill="#FBBC05" d="M3.96 10.71A5.41 5.41 0 0 1 3.68 9c0-.59.1-1.16.28-1.71V4.96H.96A9 9 0 0 0 0 9c0 1.45.35 2.82.96 4.04l3-2.33z"/>
        <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.42 0 9 0A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.66 3.58 9 3.58z"/>
    </svg>
    <span class="google-signin-button__text">Continue with Google</span>
</a>
"""


def format_user_info(full_name: str) -> str:
    """Render logged-in user text with stable contrast across Gradio themes."""
    return f'<div class="user-info-badge">Welcome, <strong>{html.escape(full_name)}</strong></div>'


# ── Chat handler ───────────────────────────────────────────────────────────────

def chat(user_message: str, history_display: list, agent_history: list,
         show_debug: bool, current_user: str, request: gr.Request):
    if not user_message.strip():
        return history_display, agent_history, gr.update()

    session_user = None
    if request and request.request:
        session_user = request.request.session.get("user_email")
    effective_user = session_user or current_user

    if show_debug:
        answer, new_agent_history, debug_text = run_agent(
            user_message, agent_history, debug=True, current_user_email=effective_user
        )
    else:
        answer, new_agent_history = run_agent(
            user_message, agent_history, debug=False, current_user_email=effective_user
        )
        debug_text = ""

    history_display = history_display + [
        {"role": "user",      "content": user_message},
        {"role": "assistant", "content": answer},
    ]

    debug_update = gr.update(value=debug_text, visible=show_debug)
    return history_display, new_agent_history, debug_update


def clear_conversation():
    return [], [], gr.update(value="", visible=False)


# ── Provider / model selection ────────────────────────────────────────────────

_KNOWN_OLLAMA_MODELS = ["llama3.2:1b", "llama3.1:8b"]


def get_ollama_status():
    if llm.ollama_available():
        return "🟢 Ollama is running locally"
    return "🔴 Ollama not detected — install from ollama.com and run `ollama pull " + OLLAMA_CHAT_MODEL + "`"


def get_chat_model_choices() -> list:
    available = set(llm.get_available_ollama_models())
    choices = []
    for m in _KNOWN_OLLAMA_MODELS:
        label = m if m in available else f"{m}  (not pulled)"
        choices.append((label, m))
    choices.append((f"☁️ Gemini ({GEMINI_CHAT_MODEL})", "gemini"))
    return choices


def get_initial_chat_model_value() -> str:
    return "llama3.2:1b"


def on_chat_model_change(value: str):
    if value == "gemini":
        status = llm.set_chat_provider("gemini")
        return f"**Active:** ☁️ Gemini ({GEMINI_CHAT_MODEL})\n\n{status}", get_ollama_status()
    available = set(llm.get_available_ollama_models())
    if value not in available:
        return f"⚠️ `{value}` is not pulled. Run: `ollama pull {value}`", get_ollama_status()
    llm.set_chat_provider("ollama")
    status = llm.set_chat_model(value)
    return f"**Active:** {value}\n\n{status}", get_ollama_status()


# ── Auth handlers ──────────────────────────────────────────────────────────────

def load_current_user(request: gr.Request):
    """Restore Google OAuth session state when the Gradio page loads."""
    pending_google = None
    session_user = None
    if request and request.request:
        pending_google = request.request.session.get("pending_google_user")
        session_user = request.request.session.get("user_email")

    if pending_google:
        display_name = pending_google.get("display_name") or pending_google.get("email")
        return (
            None,
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(value="", visible=False),
            gr.update(visible=False),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(visible=True),
            gr.update(value=f"Complete Google registration for **{display_name}**", visible=True),
        )

    if session_user:
        user = query_user_profile(session_user)
        if user:
            return (
                user["email"],
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(value=format_user_info(user["full_name"]), visible=True),
                gr.update(visible=True),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(visible=False),
                gr.update(value="", visible=False),
            )

    return (
        None,
        gr.update(visible=True),
        gr.update(visible=True),
        gr.update(value="", visible=False),
        gr.update(visible=False),
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(value="", visible=False),
    )


def do_login(email: str, password: str, request: gr.Request):
    """Handle login form submission."""
    if not email.strip() or not password.strip():
        return (
            gr.update(value="Please enter your email and password.", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    user = login_user(email.strip(), password)
    if user is None:
        return (
            gr.update(value="Incorrect email or password.", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    display_name = f"{user['first_name']} {user['surname']}"
    if request and request.request:
        request.request.session["user_email"] = user["email"]
        request.request.session["user_id"] = user["user_id"]
    return (
        gr.update(value="", visible=False),
        user["email"],
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value=format_user_info(display_name), visible=True),
        gr.update(visible=True),
        gr.update(visible=False),
    )


def do_logout(request: gr.Request):
    """Clear both Gradio state and server-side OAuth session."""
    if request and request.request:
        request.request.session.clear()
    return (
        None,
        gr.update(visible=True),
        gr.update(visible=True),
        gr.update(value="", visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
    )


def do_register(email, first_name, surname, year_of_birth, password, secret_question, secret_answer,
                request: gr.Request):
    """Handle registration form submission."""
    if not all([
        str(email).strip(), str(first_name).strip(), str(surname).strip(),
        str(password).strip(), secret_question, str(secret_answer).strip(),
    ]):
        return (
            gr.update(value="All fields are required.", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    try:
        year = int(year_of_birth)
        if year < 1900 or year > 2015:
            raise ValueError
    except (ValueError, TypeError):
        return (
            gr.update(value="Please enter a valid year of birth (e.g. 1990).", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    ok, err = register_user(
        email.strip(), first_name.strip(), surname.strip(),
        year, password, secret_question, secret_answer.strip(),
    )
    if not ok:
        return (
            gr.update(value=err, visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    display_name = f"{first_name.strip()} {surname.strip()}"
    if request and request.request:
        request.request.session["user_email"] = email.strip().lower()
    return (
        gr.update(value="", visible=False),
        email.strip().lower(),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value=format_user_info(display_name), visible=True),
        gr.update(visible=True),
        gr.update(visible=False),
    )


def forgot_find_question(email: str):
    """Step 1 — look up the secret question for the given email."""
    if not email.strip():
        return (
            gr.update(value="Please enter your email address.", visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    question = get_user_secret_question(email.strip())
    if question is None:
        return (
            gr.update(value="No account found with that email address.", visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    return (
        gr.update(value="", visible=False),
        gr.update(value=f"**Your security question:** {question}", visible=True),
        gr.update(visible=True),
        gr.update(visible=True),
        gr.update(visible=True),
    )


def forgot_reset_password(email: str, answer: str, new_password: str):
    """Step 2 — verify the secret answer and update the password."""
    if not str(answer).strip() or not str(new_password).strip():
        return gr.update(value="Please fill in all fields.", visible=True)

    if not verify_secret_answer(email.strip(), answer.strip()):
        return gr.update(value="Incorrect answer. Please try again.", visible=True)

    if not update_password(email.strip(), new_password):
        return gr.update(value="Failed to update password. Please try again.", visible=True)

    return gr.update(value="**Password reset successfully. You can now log in.**", visible=True)


def complete_google_registration(year_of_birth: str, request: gr.Request):
    """Finish first-time Google signup after collecting the required birth year."""
    pending_google = None
    if request and request.request:
        pending_google = request.request.session.get("pending_google_user")
    if not pending_google:
        return (
            gr.update(value="Google signup session expired. Please try again.", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    try:
        year = int(year_of_birth)
        if year < 1900 or year > 2015:
            raise ValueError
    except (ValueError, TypeError):
        return (
            gr.update(value="Please enter a valid year of birth (e.g. 1990).", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    user = complete_google_signup(
        provider_user_id=pending_google["provider_user_id"],
        email=pending_google["email"],
        email_verified=bool(pending_google.get("email_verified")),
        display_name=pending_google.get("display_name"),
        avatar_url=pending_google.get("avatar_url"),
        year_of_birth=year,
    )
    if not user:
        return (
            gr.update(value="Unable to complete Google signup for this account.", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    if request and request.request:
        request.request.session.pop("pending_google_user", None)
        request.request.session["user_email"] = user["email"]
        request.request.session["user_id"] = user["user_id"]

    return (
        gr.update(value="", visible=False),
        user["email"],
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value=format_user_info(user["full_name"]), visible=True),
        gr.update(visible=True),
        gr.update(visible=False),
    )


# ── Panel visibility toggles ──────────────────────────────────────────────────

def show_login_panel():
    return gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)

def show_register_panel():
    return gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), gr.update(visible=False)

def show_forgot_panel():
    return gr.update(visible=False), gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)

def hide_all_panels():
    return gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)


# ── Example queries ────────────────────────────────────────────────────────────

EXAMPLES = [
    "What national rail trains run from Central (NR01) to Stonehaven (NR05)?",
    "What is the fastest metro route from MS01 to MS14?",
    "How do I get from Central Square (MS01) to Stonehaven (NR05)?",
    "If Old Town station (NR03) is closed, what alternative routes exist from NR01 to NR05?",
    "My train was delayed 45 minutes — what compensation am I entitled to?",
    "What is the company policy on travelling with a bicycle on national rail?",
]


# ── Build UI ───────────────────────────────────────────────────────────────────

with gr.Blocks(title="TransitFlow") as demo:

    # ── Hidden state ──────────────────────────────────────────────────
    agent_history_state = gr.State([])
    current_user_state  = gr.State(None)   # None = guest, email str = logged in

    # ── Header: title + auth buttons ─────────────────────────────────
    with gr.Row(equal_height=True):
        gr.Markdown("""
# 🚂 TransitFlow Intelligent Rail Assistant
*Powered by PostgreSQL · pgvector · Neo4j · LLM*
        """)
        with gr.Column(scale=0, min_width=280, elem_id="auth_header"):
            with gr.Row():
                login_btn    = gr.Button("👤 Login",    size="sm", variant="secondary")
                register_btn = gr.Button("📝 Register", size="sm", variant="secondary")
            user_info_display = gr.HTML("", visible=False)
            logout_btn = gr.Button("Logout", size="sm", variant="stop", visible=False)

    # ── Login panel (hidden by default) ──────────────────────────────
    with gr.Column(visible=False) as login_panel:
        gr.Markdown("### Login")
        login_email_in    = gr.Textbox(label="Email", placeholder="you@example.com")
        login_password_in = gr.Textbox(label="Password", type="password")
        login_error_msg   = gr.Markdown("", visible=False)
        # Keep all login actions aligned to make password and Google auth feel equally available.
        with gr.Row(equal_height=True, elem_classes="login-action-row"):
            login_submit_btn = gr.Button("Login", variant="primary")
            gr.HTML(GOOGLE_SIGNIN_BUTTON_HTML)
            forgot_link_btn  = gr.Button("Forgot password?", size="sm")
            login_cancel_btn = gr.Button("Cancel", size="sm")

    # ── Register panel (hidden by default) ───────────────────────────
    with gr.Column(visible=False) as register_panel:
        gr.Markdown("### Create an Account")
        with gr.Row():
            reg_first_name_in = gr.Textbox(label="First name")
            reg_surname_in    = gr.Textbox(label="Surname")
        reg_email_in    = gr.Textbox(label="Email", placeholder="you@example.com")
        reg_year_in     = gr.Textbox(label="Year of birth", placeholder="e.g. 1990")
        reg_password_in = gr.Textbox(label="Password", type="password")
        reg_question_in = gr.Dropdown(choices=SECRET_QUESTIONS, label="Security question")
        reg_answer_in   = gr.Textbox(label="Secret answer")
        reg_error_msg   = gr.Markdown("", visible=False)
        with gr.Row():
            reg_submit_btn = gr.Button("Register", variant="primary")
            reg_cancel_btn = gr.Button("Cancel", size="sm")

    # ── Forgot password panel (hidden by default) ─────────────────────
    with gr.Column(visible=False) as forgot_panel:
        gr.Markdown("### Reset Your Password")
        forgot_email_in          = gr.Textbox(label="Email address", placeholder="you@example.com")
        forgot_check_btn         = gr.Button("Find my question", variant="secondary")
        forgot_question_display  = gr.Markdown("", visible=False)
        forgot_answer_in         = gr.Textbox(label="Your answer", visible=False)
        forgot_new_password_in   = gr.Textbox(label="New password", type="password", visible=False)
        forgot_reset_btn         = gr.Button("Reset password", variant="primary", visible=False)
        forgot_msg               = gr.Markdown("")
        forgot_back_btn          = gr.Button("Back to login", size="sm")

    # ── Google signup completion panel (hidden by default) ───────────
    with gr.Column(visible=False) as google_complete_panel:
        gr.Markdown("### Complete Google Registration")
        google_signup_info = gr.Markdown("", visible=False)
        google_year_in     = gr.Textbox(label="Year of birth", placeholder="e.g. 1990")
        google_signup_msg  = gr.Markdown("", visible=False)
        with gr.Row():
            google_signup_btn = gr.Button("Complete registration", variant="primary")
            google_cancel_btn = gr.Button("Cancel", size="sm")

    # ── Main chat area ────────────────────────────────────────────────
    with gr.Row():

        # ── Left: chat ────────────────────────────────────────────────
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(label="TransitFlow Assistant", height=420)

            with gr.Row():
                msg = gr.Textbox(
                    placeholder="Ask e.g. 'Are there seats from London to Bristol?'",
                    show_label=False,
                    scale=4,
                )
                send_btn = gr.Button("Send", variant="primary", scale=1)

            with gr.Row():
                clear_btn    = gr.Button("🗑️ Clear conversation", size="sm")
                debug_toggle = gr.Checkbox(label="🔍 Show database debug panel", value=True)

            # Debug panel — hidden until checkbox is ticked and a message is sent
            debug_panel = gr.Markdown(
                value="",
                visible=False,
            )

        # ── Right: sidebar ────────────────────────────────────────────
        with gr.Column(scale=1):

            gr.Markdown("### 🤖 LLM Provider")
            chat_model_dropdown = gr.Dropdown(
                choices=get_chat_model_choices(),
                value=get_initial_chat_model_value(),
                label="Chat model",
                info="Local Ollama models run fully locally. Gemini uses your API key.",
            )
            provider_status = gr.Markdown(value="**Active:** llama3.2:1b")
            ollama_status   = gr.Markdown(value=get_ollama_status())

            gr.Markdown("---")

            gr.Markdown("### 💡 Try these examples")
            for example in EXAMPLES:
                gr.Button(example, size="sm").click(
                    fn=lambda e=example: e,
                    outputs=msg,
                    show_progress="hidden",
                    queue=False,
                )

    # ── Event wiring ──────────────────────────────────────────────────

    demo.load(
        fn=load_current_user,
        outputs=[
            current_user_state,
            login_btn,
            register_btn,
            user_info_display,
            logout_btn,
            login_panel,
            register_panel,
            forgot_panel,
            google_complete_panel,
            google_signup_info,
        ],
        show_progress="hidden",
        queue=False,
    )

    chat_model_dropdown.change(
        fn=on_chat_model_change,
        inputs=chat_model_dropdown,
        outputs=[provider_status, ollama_status],
        show_progress="hidden",
        queue=False,
    )

    send_btn.click(
        fn=chat,
        inputs=[msg, chatbot, agent_history_state, debug_toggle, current_user_state],
        outputs=[chatbot, agent_history_state, debug_panel],
    ).then(fn=lambda: "", outputs=msg)

    msg.submit(
        fn=chat,
        inputs=[msg, chatbot, agent_history_state, debug_toggle, current_user_state],
        outputs=[chatbot, agent_history_state, debug_panel],
    ).then(fn=lambda: "", outputs=msg)

    clear_btn.click(
        fn=clear_conversation,
        outputs=[chatbot, agent_history_state, debug_panel],
        show_progress="hidden",
        queue=False,
    )

    # Panel toggle buttons
    login_btn.click(
        fn=show_login_panel,
        outputs=[login_panel, register_panel, forgot_panel, google_complete_panel],
        show_progress="hidden",
        queue=False,
    )
    register_btn.click(
        fn=show_register_panel,
        outputs=[login_panel, register_panel, forgot_panel, google_complete_panel],
        show_progress="hidden",
        queue=False,
    )
    login_cancel_btn.click(
        fn=hide_all_panels,
        outputs=[login_panel, register_panel, forgot_panel, google_complete_panel],
        show_progress="hidden",
        queue=False,
    )
    reg_cancel_btn.click(
        fn=hide_all_panels,
        outputs=[login_panel, register_panel, forgot_panel, google_complete_panel],
        show_progress="hidden",
        queue=False,
    )
    forgot_link_btn.click(
        fn=show_forgot_panel,
        outputs=[login_panel, register_panel, forgot_panel, google_complete_panel],
        show_progress="hidden",
        queue=False,
    )
    forgot_back_btn.click(
        fn=show_login_panel,
        outputs=[login_panel, register_panel, forgot_panel, google_complete_panel],
        show_progress="hidden",
        queue=False,
    )
    google_cancel_btn.click(
        fn=hide_all_panels,
        outputs=[login_panel, register_panel, forgot_panel, google_complete_panel],
        show_progress="hidden",
        queue=False,
    )

    # Login
    login_submit_btn.click(
        fn=do_login,
        inputs=[login_email_in, login_password_in],
        outputs=[
            login_error_msg,
            current_user_state,
            login_btn,
            register_btn,
            user_info_display,
            logout_btn,
            login_panel,
        ],
        show_progress="hidden",
        queue=False,
    )

    # Logout
    logout_btn.click(
        fn=do_logout,
        outputs=[
            current_user_state,
            login_btn,
            register_btn,
            user_info_display,
            logout_btn,
            login_panel,
            register_panel,
            forgot_panel,
            google_complete_panel,
        ],
        show_progress="hidden",
        queue=False,
    )

    # Register
    reg_submit_btn.click(
        fn=do_register,
        inputs=[
            reg_email_in, reg_first_name_in, reg_surname_in,
            reg_year_in, reg_password_in, reg_question_in, reg_answer_in,
        ],
        outputs=[
            reg_error_msg,
            current_user_state,
            login_btn,
            register_btn,
            user_info_display,
            logout_btn,
            register_panel,
        ],
        show_progress="hidden",
        queue=False,
    )

    # Complete Google signup after OAuth verifies identity.
    google_signup_btn.click(
        fn=complete_google_registration,
        inputs=[google_year_in],
        outputs=[
            google_signup_msg,
            current_user_state,
            login_btn,
            register_btn,
            user_info_display,
            logout_btn,
            google_complete_panel,
        ],
        show_progress="hidden",
        queue=False,
    )

    # Forgot password — step 1: find question
    forgot_check_btn.click(
        fn=forgot_find_question,
        inputs=[forgot_email_in],
        outputs=[
            forgot_msg,
            forgot_question_display,
            forgot_answer_in,
            forgot_new_password_in,
            forgot_reset_btn,
        ],
        show_progress="hidden",
        queue=False,
    )

    # Forgot password — step 2: reset
    forgot_reset_btn.click(
        fn=forgot_reset_password,
        inputs=[forgot_email_in, forgot_answer_in, forgot_new_password_in],
        outputs=[forgot_msg],
        show_progress="hidden",
        queue=False,
    )

# ── FastAPI wrapper for Google OAuth routes ───────────────────────────────────

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY or "transitflow-local-dev-session-secret",
)


@app.get("/auth/google/login")
async def google_login(request: Request):
    """Start Google OAuth login using the configured redirect URI."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return RedirectResponse("/?login_error=google_oauth_not_configured")
    return await oauth.google.authorize_redirect(request, GOOGLE_REDIRECT_URI)


@app.get("/auth/google/callback")
async def google_callback(request: Request):
    """Handle Google OAuth callback and either login or start signup completion."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except MismatchingStateError:
        return RedirectResponse("/?login_error=oauth_state_mismatch")
    userinfo = token.get("userinfo")
    if not userinfo:
        response = await oauth.google.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            token=token,
        )
        userinfo = response.json()

    if not userinfo.get("email_verified"):
        return RedirectResponse("/?login_error=email_not_verified")

    user = login_or_create_google_user(
        provider_user_id=userinfo["sub"],
        email=userinfo["email"],
        email_verified=bool(userinfo.get("email_verified")),
        display_name=userinfo.get("name"),
        avatar_url=userinfo.get("picture"),
    )
    if not user:
        return RedirectResponse("/?login_error=google_account_inactive")

    if user.get("needs_birth_year"):
        request.session["pending_google_user"] = user
        request.session.pop("user_email", None)
        request.session.pop("user_id", None)
        return RedirectResponse("/")

    request.session.pop("pending_google_user", None)
    request.session["user_email"] = user["email"]
    request.session["user_id"] = user["user_id"]
    return RedirectResponse("/")


@app.get("/auth/logout")
async def google_logout(request: Request):
    """Clear server-side login session and return to the app."""
    request.session.clear()
    return RedirectResponse("/")


app = gr.mount_gradio_app(
    app,
    demo,
    path="/",
    theme=gr.themes.Soft(),
    css=GOOGLE_BUTTON_CSS,
)


if __name__ == "__main__":
    print("Running on local URL:  http://localhost:7860")
    print("Press CTRL+C to quit")
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=7860,
            log_level="warning",
            access_log=False,
            timeout_keep_alive=1,
            timeout_graceful_shutdown=1,
        )
    finally:
        print("Server stopped")
