import streamlit as st
import google.generativeai as genai
import json
import os
from datetime import datetime
from docx import Document
import io
import tempfile
import re

# --- Configuration ---
# Update this string to the specific Gemini model version you have access to.
GEMINI_MODEL_NAME = 'gemini-2.0-flash-exp'

# --- Utility to prettify keys ---
def prettify_key(key):
    key = key.replace('_', ' ')
    key = re.sub(r'([a-z])([A-Z])', r'\1 \2', key)
    return key.title() + ":"

# --- HSE Capital & Estates Minutes Generator ---
def generate_capital_estates_minutes(structured):
    now = datetime.now()
    # Helper to get value or fallback
    def get(val, default="Not mentioned"):
        return val if val and val != "Not mentioned" else default

    # Helper for bullets
    def bullets(val):
        if isinstance(val, list) and val:
            # Filter empty strings if any
            valid_items = [v for v in val if v and str(v).strip()]
            return "".join([f"• {item}\n" for item in valid_items])
        elif isinstance(val, str) and val.strip():
            return f"• {val}\n"
        else:
            return "Not mentioned\n"

    # Fields mapping and fallback
    meeting_title = get(structured.get("meetingTitle"), "Capital & Estates Meeting")
    meeting_date = get(structured.get("meetingDate"), now.strftime("%d/%m/%Y"))
    start_time = get(structured.get("startTime"), now.strftime("%H:%M"))
    end_time = get(structured.get("endTime"), now.strftime("%H:%M"))
    location = get(structured.get("location"))
    chairperson = get(structured.get("chairperson"))
    minute_taker = get(structured.get("minuteTaker"))
    attendees = structured.get("attendees", [])
    apologies = structured.get("apologies", [])
    previous_meeting_date = get(structured.get("previousMeetingDate"))
    matters_arising = structured.get("mattersArising", [])
    declarations_of_interest = get(structured.get("declarationsOfInterest"), "None declared.")
    major_projects = structured.get("majorProjects", [])
    minor_projects = structured.get("minorProjects", [])
    estates_strategy = structured.get("estatesStrategy", [])
    health_safety = structured.get("healthSafety", [])
    risk_register = structured.get("riskRegister", [])
    finance_update = structured.get("financeUpdate", [])
    aob = structured.get("aob", [])
    next_meeting_date = get(structured.get("nextMeetingDate"))
    meeting_closed_time = get(structured.get("meetingClosedTime"), end_time)
    minutes_prepared_by = get(structured.get("minutesPreparedBy"), minute_taker or "Not mentioned")
    preparation_date = get(structured.get("preparationDate"), now.strftime("%d/%m/%Y"))

    # Compose the minutes
    template = f"""HSE Capital & Estates Meeting Minutes
Meeting Title: {meeting_title}
Date: {meeting_date}
Time: {start_time} - {end_time}
Location: {location}
Chairperson: {chairperson}
Minute Taker: {minute_taker}
________________________________________
1. Attendance
Present:
{bullets(attendees)}
Apologies:
{bullets(apologies)}
________________________________________
2. Minutes of Previous Meeting
• Confirmation of previous meeting minutes held on {previous_meeting_date}.
• Matters Arising:
{bullets(matters_arising)}
________________________________________
3. Declarations of Interest
• {declarations_of_interest}
________________________________________
4. Capital Projects Update
4.1 Major Projects (over €X million)
{bullets(major_projects)}
4.2 Minor Works / Equipment / ICT Projects
{bullets(minor_projects)}
________________________________________
5. Estates Strategy and Planning
{bullets(estates_strategy)}
________________________________________
6. Health & Safety / Regulatory Compliance
{bullets(health_safety)}
________________________________________
7. Risk Register
{bullets(risk_register)}
________________________________________
8. Finance Update
{bullets(finance_update)}
________________________________________
9. AOB (Any Other Business)
{bullets(aob)}
________________________________________
10. Date of Next Meeting
• {next_meeting_date}
________________________________________
Meeting Closed at: {meeting_closed_time}
Minutes Prepared by: {minutes_prepared_by}
Date: {preparation_date}
"""
    return template

# --- DOCX Helpers ---
def create_docx(content, kind="minutes"):
    doc = Document()
    if kind == "minutes":
        for line in content.splitlines():
            if line.strip(" _").endswith(":"):
                doc.add_heading(line.strip(), level=2)
            elif line.strip() == "________________________________________":
                doc.add_paragraph("-" * 50)
            elif line.strip():
                doc.add_paragraph(line)
    else:
        doc.add_heading("Meeting Export", level=1)
        doc.add_paragraph(content)
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

# --- Configure Gemini API ---
try:
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel(model_name=GEMINI_MODEL_NAME)
    else:
        st.error("GEMINI_API_KEY not found in Streamlit secrets.")
        st.stop()
except Exception as e:
    st.error(f"Error configuring Gemini API: {e}")
    st.stop()

st.set_page_config(page_title="MAI Recap Pro", layout="wide", page_icon="https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png")

# --- Custom CSS for Chat Interface ---
st.markdown("""
<style>
    .stChatInputContainer {
        padding-bottom: 20px;
    }
    .chat-message {
        padding: 1.5rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex
    }
    .chat-message.user {
        background-color: #2b313e;
        border: 1px solid #4a4e59;
    }
    .chat-message.bot {
        background-color: #1c1f26;
        border: 1px solid #2e333d;
    }
</style>
""", unsafe_allow_html=True)

# --- Password protection ---
if "password_verified" not in st.session_state:
    st.session_state.password_verified = False

if not st.session_state.password_verified:
    st.title("🔒 MAI Recap Access")
    st.warning("This application requires a password to proceed.")
    with st.form("password_form"):
        user_password = st.text_input("Enter password:", type="password", key="password_input")
        submit_button = st.form_submit_button("Submit")
        if submit_button:
            try:
                expected_password = st.secrets.get("password")
                if expected_password and user_password == expected_password:
                    st.session_state.password_verified = True
                    st.rerun()
                elif not expected_password:
                      st.error("Password not configured in secrets.toml.")
                else:
                    st.error("Incorrect password. Please try again.")
            except Exception as e:
                st.error(f"An error occurred during password verification: {e}")
    st.stop()

# --- Sidebar ---
with st.sidebar:
    st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=200)
    st.title("📒 MAI Recap")
    
    if st.button("🔄 Restart Session"):
        st.session_state.clear()
        st.session_state.password_verified = True # Keep logged in
        st.rerun()

    st.markdown("---")
    st.markdown(f"**Model:** {GEMINI_MODEL_NAME}")
    st.markdown("**Version:** 3.0 (Notebook Features)")
    
    st.info(
        "**New Features:**\n"
        "- 💬 **Chat:** Ask questions about the meeting.\n"
        "- 📖 **Overview:** Get a briefing doc style summary."
    )

# --- Main UI Header ---
st.markdown(
    """
    <div style="display: flex; align-items: center;">
        <img src="https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png" width="80" style="margin-right: 15px;">
        <h1 style="margin: 0; display: inline-block; vertical-align: middle;">MAI Recap</h1>
    </div>
    <h4 style="margin-top: 5px;">HSE Minute-AI (MAI) Generator</h4>
    """,
    unsafe_allow_html=True
)

# --- Chat History Initialization ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Audio Input Section ---
if "transcript" not in st.session_state:
    st.markdown("### 1. Upload Meeting Audio")
    
    mode = st.radio("Input method:", ["Record Microphone", "Upload File"], horizontal=True)
    audio_bytes = None

    if mode == "Upload File":
        uploaded_audio = st.file_uploader("Upload audio (WAV, MP3, M4A)", type=["wav", "mp3", "m4a", "ogg", "flac"])
        if uploaded_audio:
            st.audio(uploaded_audio)
            audio_bytes = uploaded_audio
    else:
        recorded_audio = st.audio_input("Record audio")
        if recorded_audio:
            st.audio(recorded_audio)
            audio_bytes = recorded_audio

    if audio_bytes and st.button("🧠 Transcribe & Analyse"):
        with st.spinner("Processing audio... This may take a moment."):
            # Save to temp
            if hasattr(audio_bytes, "read"): audio_bytes.seek(0); data = audio_bytes.read()
            else: data = audio_bytes
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                # Upload to Gemini
                myfile = genai.upload_file(tmp_path)
                
                # Wait for processing
                import time
                while myfile.state.name == "PROCESSING":
                    time.sleep(1)
                    myfile = genai.get_file(myfile.name)

                # Transcribe
                prompt = "Transcribe this meeting in UK English. Identify speakers if possible. Output ONLY the transcript."
                res = model.generate_content([prompt, myfile])
                st.session_state["transcript"] = res.text
                st.rerun()

            except Exception as e:
                st.error(f"Error: {e}")
            finally:
                if os.path.exists(tmp_path): os.remove(tmp_path)

# --- Main Application Tabs ---
else:
    st.success("✅ Transcript Ready")
    
    # Create the NotebookLM style tab layout
    tab1, tab2, tab3, tab4 = st.tabs(["📄 Minutes & Actions", "🔍 Briefing Overview", "💬 Chat with Meeting", "📝 Raw Transcript"])

    # --- TAB 1: Minutes Generation (Original Functionality) ---
    with tab1:
        st.header("Formal Minutes")
        if "minutes" not in st.session_state:
            if st.button("Generate Minutes"):
                with st.spinner("Extracting structured data..."):
                    prompt_minutes = f"""
                    Extract structured JSON data from this transcript for a HSE Capital & Estates meeting.
                    Keys: meetingTitle, meetingDate, attendees, apologies, mattersArising, majorProjects, minorProjects, estatesStrategy, healthSafety, riskRegister, financeUpdate, aob, nextMeetingDate.
                    Use 'Not mentioned' if missing. Dates as DD/MM/YYYY. Currency in Euro (€).
                    Transcript: {st.session_state['transcript']}
                    """
                    # Enforce JSON
                    try:
                        res = model.generate_content(prompt_minutes, generation_config={"response_mime_type": "application/json"})
                        structured = json.loads(res.text)
                        
                        # Handle potential list wrapper
                        if isinstance(structured, list): structured = structured[0]
                        
                        st.session_state["structured"] = structured
                        st.session_state["minutes"] = generate_capital_estates_minutes(structured)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to generate minutes: {e}")
        
        if "minutes" in st.session_state:
            st.text_area("Minutes Draft:", st.session_state["minutes"], height=600)
            st.download_button(
                "📥 Download Minutes (DOCX)",
                create_docx(st.session_state["minutes"]),
                "Minutes.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

    # --- TAB 2: Briefing Overview (NotebookLM Style) ---
    with tab2:
        st.header("Meeting Briefing")
        st.caption("A high-level overview of the meeting's themes and dynamics.")
        
        if "overview" not in st.session_state:
            if st.button("Generate Briefing Doc"):
                with st.spinner("Analyzing meeting dynamics..."):
                    prompt_overview = f"""
                    You are an expert analyst. Create a "Briefing Document" based on this transcript.
                    Format it clearly with Markdown. Include the following sections:
                    1. **Executive Summary**: A 3-sentence high-level summary.
                    2. **Key Themes**: The 3-4 main topics discussed (e.g., Budget Deficits, Staffing).
                    3. **Key Decisions**: What was actually decided (vs just discussed).
                    4. **Contention Points**: Were there any disagreements or areas of concern?
                    5. **Quote of the Meeting**: The most impactful quote.
                    
                    Transcript:
                    {st.session_state['transcript']}
                    """
                    res = model.generate_content(prompt_overview)
                    st.session_state["overview"] = res.text
                    st.rerun()

        if "overview" in st.session_state:
            st.markdown(st.session_state["overview"])
            st.download_button(
                "📥 Download Briefing",
                create_docx(st.session_state["overview"], kind="overview"),
                "Briefing_Doc.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

    # --- TAB 3: Chat with Meeting (NotebookLM Style) ---
    with tab3:
        st.header("Chat with your Meeting")
        st.caption("Ask questions like 'What was the budget for the new wing?' or 'Did John agree to the timeline?'")

        # Display chat history
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Chat Input
        if prompt := st.chat_input("Ask about the meeting..."):
            # Add user message
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # Generate response
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    chat_prompt = f"""
                    You are a helpful assistant answering questions about a specific meeting transcript.
                    
                    RULES:
                    1. Answer ONLY based on the transcript provided below.
                    2. If the info isn't there, say "I couldn't find that in the transcript."
                    3. Be concise and professional.
                    4. Use UK English.
                    
                    TRANSCRIPT:
                    {st.session_state['transcript']}
                    
                    USER QUESTION:
                    {prompt}
                    """
                    
                    response = model.generate_content(chat_prompt)
                    st.markdown(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})

    # --- TAB 4: Raw Transcript ---
    with tab4:
        st.header("Raw Transcript")
        st.text_area("Full Text", st.session_state["transcript"], height=600)

