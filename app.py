# app.py
import streamlit as st
from langchain.agents import create_openai_functions_agent, AgentExecutor
from langchain_openai import ChatOpenAI
from agent_tools import TOOLS
from core.twitter_token import refresh_twitter_token
from core.linkedin_token import refresh_linkedin_token
from dotenv import load_dotenv
import os
from typing import Optional
from pydantic import SecretStr
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import agent_tools
import json as _json
from core.medium import get_unpublished_filenames
import urllib.parse
import webbrowser

# --- LLM providers: OpenAI → Gemini → DeepSeek ---

try:
    from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
except ImportError:
    ChatGoogleGenerativeAI = None

try:
    from langchain_community.chat_models import ChatDeepSeek  # type: ignore
except ImportError:
    ChatDeepSeek = None

def getenv_required(name: str) -> str:
    v: Optional[str] = os.getenv(name)
    if not v:                         # catches None and empty string
        raise RuntimeError(f"{name} is not set")
    return v

# === helper to build LLM ===
load_dotenv()

def build_llm(provider_priority: list[str]):
    """Return (llm, provider_name) picking the first available in priority list."""
    for prov in provider_priority:
        if prov == "openai" and os.getenv("OPENAI_API_KEY"):
            return (
                ChatOpenAI(
                    model="gpt-4o-mini",
                    api_key=SecretStr(getenv_required("OPENAI_API_KEY")),
                ),
                "openai",
            )
        if prov == "gemini" and os.getenv("GOOGLE_API_KEY") and ChatGoogleGenerativeAI:
            return (
                ChatGoogleGenerativeAI(
                    model="gemini-pro",
                    google_api_key=SecretStr(getenv_required("GOOGLE_API_KEY")),
                ),
                "gemini",
            )
        if prov == "deepseek" and ChatDeepSeek is not None:
            return (ChatDeepSeek(model_name="deepseek-chat"), "deepseek")
    raise RuntimeError("No suitable LLM provider configured. Provide API keys or install DeepSeek.")

# initial provider list
PROVIDERS_ORDER = ["openai", "gemini", "deepseek"]
llm, current_provider = build_llm(PROVIDERS_ORDER)

# Build a minimal prompt that meets the new API contract (must include agent_scratchpad)
prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are ContentBot. Never reveal or ask for API keys. "
        "The tools create_content, publish_medium, post_linkedin, and post_twitter "
        "already know where to locate drafts, keywords and credentials. "
        "create_content can optionally accept a comma-separated list of keyword(s) to target; "
        "publish_medium can optionally accept a filename to publish. "
        "The generate_keywords tool can optionally accept a comma-separated list of seed words; "
        "if the user provides such list pass it verbatim, otherwise invoke generate_keywords with no arguments. "
        "When the user explicitly names any of these tools, you MUST invoke that tool exactly once, even if you think it has nothing to do or will return an empty result. "
        "Do not ask follow-up questions first. "
        "Only call the token-refresh tools when the user explicitly requests a token reset.",
    ),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

# --- factory to rebuild Agent when we switch provider ---

def make_agent(llm_instance):
    runnable = create_openai_functions_agent(llm_instance, TOOLS, prompt)
    return AgentExecutor(agent=runnable, tools=TOOLS, verbose=False, max_iterations=2)

agent = make_agent(llm)

st.set_page_config(page_title="ContentBot", page_icon="📝")
st.title("📝 ContentBot – local")

if "history" not in st.session_state:
    st.session_state.history = []

# replay chat
for msg in st.session_state.history:
    st.chat_message(msg["role"]).write(msg["content"])

# ------------ CUSTOM DASHBOARD CONTROLS -------------------

KEYWORDS_JSON_PATH = os.getenv("KEYWORDS_FILE", "./keywords.json")

st.sidebar.header("🛠️ Tools Panel")
SIDEBAR_MIN_PX = 340
SIDEBAR_WIDTH_PX = 450   # pick any value; 380-400px feels roomy

st.markdown(
    f"""
    <style>
        /* Top-level sidebar element */
        [data-testid="stSidebar"] {{
            min-width: {SIDEBAR_MIN_PX}px;
            max-width: {SIDEBAR_WIDTH_PX}px;
        }}

        /* Inner sidebar content (optional) */
        [data-testid="stSidebar"] > div:first-child {{
            min-width: {SIDEBAR_MIN_PX}px;
            max-width: {SIDEBAR_WIDTH_PX}px;
        }}
    </style>
    """,
    unsafe_allow_html=True,
)

# 1. Generate Keywords ------------------------------------------------

with st.sidebar.expander("🔍 Keyword Research", expanded=False):
    seeds_input = st.text_input("Seed words (comma-separated) – leave blank to use defaults", key="seed_input")
    if st.button("Generate Keywords", key="btn_gen_kw"):
        cmd = "generate_keywords"
        if seeds_input.strip():
            cmd += f" seeds: {seeds_input.strip()}"
        st.session_state["pending_command"] = cmd

# 2. Create Content ---------------------------------------------------

with st.sidebar.expander("📝 Create Content", expanded=False):
    # Load available (unused) keywords for multiselect
    keywords_options = []
    keyword_label_to_value: dict[str, str] = {}
    if os.path.exists(KEYWORDS_JSON_PATH):
        try:
            with open(KEYWORDS_JSON_PATH) as _kf:
                _data = _json.load(_kf)
                for item in _data:
                    if item.get("used"):
                        continue
                    kw = item.get("keyword", "?")
                    sc = item.get("avg_interest", 0)
                    label = f"{kw} ({sc:.1f})"
                    keywords_options.append(label)
                    keyword_label_to_value[label] = kw
        except Exception as _e:
            st.error(f"Failed to read keywords.json: {_e}")

    selected_labels = st.multiselect("Select keyword(s):", options=keywords_options, key="sel_kw")
    if st.button("Generate Content", key="btn_create_content"):
        if selected_labels:
            selected_keywords = [keyword_label_to_value[l] for l in selected_labels]
            cmd = "create_content keywords: " + ", ".join(selected_keywords)
        else:
            cmd = "create_content"  # fallback to default behaviour
        st.session_state["pending_command"] = cmd

# 3. Publish Medium ---------------------------------------------------

with st.sidebar.expander("📤 Publish to Medium", expanded=False):
    try:
        unpublished_files = get_unpublished_filenames()
    except Exception as _e:
        st.error(f"Could not fetch unpublished drafts: {_e}")
        unpublished_files = []

    selected_draft = st.selectbox("Choose a draft to publish:", options=["(random)"] + unpublished_files, key="sel_draft")
    if st.button("Publish Medium Article", key="btn_publish_medium"):
        if selected_draft == "(random)":
            cmd = "publish_medium"
        else:
            cmd = f"publish_medium filename: {selected_draft}"
        st.session_state["pending_command"] = cmd

# 4. Social Posting ----------------------------------------------------

with st.sidebar.expander("📣 Post on Social", expanded=False):
    if st.button("Post to Twitter", key="btn_tw"):
        st.session_state["pending_command"] = "post_twitter"
    if st.button("Post to LinkedIn", key="btn_li"):
        st.session_state["pending_command"] = "post_linkedin"

# 5. Token Refresh -----------------------------------------------------

with st.sidebar.expander("🔑 Tokens", expanded=False):
    if st.button("Refresh Twitter token", key="btn_ref_tw"):
        refresh_twitter_token()
        st.info(
            "Browser window opened for Twitter authentication. "
            "Complete the OAuth flow in the new tab; you'll see a ✅ message when done."
        )
    if st.button("Refresh LinkedIn token", key="btn_ref_li"):
        refresh_linkedin_token()
        st.info(
            "Browser window opened for LinkedIn authentication. "
            "Finish the sign-in flow and wait for the ✅ page; the token will be saved automatically."
        )

# ----------------------------------------------------------

# If a command was queued by the sidebar, process it
user_input = None
if "pending_command" in st.session_state and st.session_state["pending_command"]:
    user_input = st.session_state.pop("pending_command")

if user_input:
    # show user message instantly
    st.session_state.history.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)

    with st.chat_message("assistant"):
        # store provider in Streamlit session_state to avoid globals
        if "current_provider" not in st.session_state:
            st.session_state.current_provider = current_provider
            st.session_state.agent_obj = agent

        def is_rate_limit(err: Exception) -> bool:
            return any(
                kw in str(err).lower() for kw in ["rate limit", "429", "quota"]
            )

        provider_index = PROVIDERS_ORDER.index(st.session_state.current_provider)
        rendered = False  # track if we already showed a response (e.g. error)
        while True:
            try:
                # real-time log streaming container
                live_container = st.empty()
                agent_tools.set_live_container(live_container)
                resp = st.session_state.agent_obj.invoke({"input": user_input})
                agent_tools.set_live_container(None)
                break
            except Exception as e:
                if is_rate_limit(e) and provider_index + 1 < len(PROVIDERS_ORDER):
                    # switch to next provider
                    provider_index += 1
                    st.session_state.current_provider = PROVIDERS_ORDER[provider_index]
                    new_llm, _ = build_llm([st.session_state.current_provider])
                    st.session_state.agent_obj = make_agent(new_llm)
                    continue
                output = f"❌ {type(e).__name__}: {e}"
                st.error(output)
                st.session_state.history.append({"role": "assistant", "content": output})
                rendered = True
                break

        if not rendered:
            if 'output' not in locals():
                output = resp["output"]

            # Turn outputs into readable markdown
            if isinstance(output, str):
                display_text = output
            elif isinstance(output, dict):
                # Pretty-render content-generation result
                if output.get("status") == "success" and "details" in output:
                    md_lines = [
                        "Content generation was successful! Here are the details:\n"
                    ]
                    for item in output["details"]:
                        kw = item.get("keyword", "(unknown)")
                        md_lines.append(f"• **Keyword Processed:** `{kw}`")

                        medium = item.get("medium_file")
                        twitter = item.get("twitter_file")
                        linkedin = item.get("linkedin_file")

                        # Create simple local links if paths are present
                        if medium:
                            md_lines.append(f"• Medium Article File: [{medium}](./{medium})")
                        if twitter:
                            md_lines.append(f"• Twitter Summary File: [{twitter}](./{twitter})")
                        if linkedin:
                            md_lines.append(f"• LinkedIn Summary File: [{linkedin}](./{linkedin})")

                    display_text = "\n".join(md_lines)
                    st.markdown(display_text)

                    # Show logs if present
                    if "logs" in output:
                        logs = output["logs"]
                        with st.expander("🪵 Execution logs"):
                            st.text(logs)
                else:
                    # generic pretty-print
                    display_text = "```json\n" + _json.dumps(output, indent=2)[:3000] + "\n```"
                    st.markdown(display_text)
            else:
                # fallback for lists or other types
                display_text = "```json\n" + _json.dumps(output, indent=2)[:3000] + "\n```"
                st.markdown(display_text)

            st.session_state.history.append({"role": "assistant", "content": display_text})