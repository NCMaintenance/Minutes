import streamlit as st
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
import json
import os
from datetime import datetime
from docx import Document
import io
import tempfile
import re

# --- Configuration ---
# Using flash for speed, but handling quota errors gracefully
GEMINI_MODEL_NAME = 'gemini-2.0-flash-exp' 

# --- Custom CSS: HSE Corporate Theme (Clean, Green, Clinical) ---
def inject_custom_css():
    st.markdown("""
    <style>
        /* IMPORT FONTS */
        @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');

        /* MAIN LAYOUT */
        .stApp {
            background-color: #FFFFFF;
            font-family: 'Roboto', sans-serif;
            color: #333333;
        }

        /* HEADERS */
        h1, h2, h3 {
            color: #00563B !important; /* HSE Green */
            font-weight: 500;
        }
        
        /* LOGO AREA */
        .hse-header {
            border-bottom: 2px solid #00563B;
            padding-bottom: 15px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
        }

        /* SIDEBAR */
        section[data-testid="stSidebar"] {
            background-color: #F8F9FA; /* Light Grey */
            border-right: 1px solid #E0E0E0;
        }
        section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {
            color: #00563B !important;
        }

        /* BUTTONS - Primary HSE Green */
        .stButton > button {
            background-color: #00563B !important;
            color: white !important;
            border: none;
            border-radius: 4px;
            font-weight: 500;
            padding: 0.5rem 1rem;
            transition: opacity 0.2s;
        }
        .stButton > button:hover {
            opacity: 0.9;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }
        
        /* SECONDARY BUTTONS (Outlined) */
        div[data-testid="stButton"] button[kind="secondary"] {
            background-color: transparent !important;
            border: 1px solid #00563B !important;
            color: #00563B !important;
        }

        /* INPUT FIELDS */
        .stTextInput > div > div > input, .stTextArea > div > div > textarea, .stSelectbox > div > div > div {
            background-color: #FFFFFF !important;
            color: #333333 !important;
            border: 1px solid #CCCCCC !important;
            border-radius: 4px;
        }
        .stTextInput > div > div > input:focus, .stTextArea > div > div > textarea:focus {
            border-color: #00563B !important;
            box-shadow: 0 0 0 1px #00563B;
        }

        /* TABS */
        .stTabs [data-baseweb="tab-list"] {
            gap: 20px;
            border-bottom: 1px solid #E0E0E0;
        }
        .stTabs [data-baseweb="tab"] {
            height: 40px;
            background-color: transparent;
            border: none;
            color: #666666;
            font-weight: 500;
        }
        .stTabs [aria-selected="true"] {
            color: #00563B !important;
            border-bottom: 3px solid #00563B !important;
        }

        /* ALERTS / INFO BOXES */
        div[data-testid="stStatusWidget"] {
            background-color: #F0F7F4;
            color: #00563B;
            border: 1px solid #D1E7DD;
        }
        .stAlert {
            border-radius: 4px;
        }

        /* METRICS */
        div[data-testid="metric-container"] {
            background-color: #F8F9FA;
            padding: 10px;
            border-radius: 4px;
            border-left: 4px solid #00563B;
        }
    </style>
    """, unsafe_allow_html=True)

# --- Robust API Wrapper (Fixes the Error) ---
def generate_content_safe(model_instance, prompt, is_json=False):
    """
    Wraps the Gemini API call to catch quota errors and return user-friendly messages.
    """
    config = {"response_mime_type": "application/json"} if is_json else {}
    
    try:
        response = model_instance.generate_content(prompt, generation_config=config)
        return response
    except ResourceExhausted:
        st.error("⚠️ System Busy: The AI processing limit has been reached. Please wait 30-60 seconds and try again.")
        return None
    except Exception as e:
        st.error(f"⚠️ System Error: {str(e)}")
        return None

def get_text_from_response(response):
    if response and hasattr(response, 'text'):
        return response.text
    return ""

def detect_speakers(text):
    if not text:
        return []
    pattern = r'(?m)^(?:[\*\_]{2})?([A-Za-z0-9\s\(\)\-\.]+?)(?:[\*\_]{2})?[:]'
    matches = re.findall(pattern, text)
    unique_speakers = sorted(list(set(matches)))
    clean_speakers = [s for s in unique_speakers if len(s) < 30 and s.strip()]
    return clean_speakers

# --- HSE Capital & Estates Minutes Generator ---
def generate_capital_estates_minutes(structured):
    now = datetime.now()
    
    def get(val, default="Not stated"):
        return val if val and val != "Not stated" else default

    def bullets(val):
        if isinstance(val, list) and val:
            valid_items = [v for v in val if v and str(v).strip()]
            return "".join([f"• {item}\n" for item in valid_items])
        elif isinstance(val, str) and val.strip():
            return f"• {val}\n"
        else:
            return "None recorded\n"

    # Fields mapping (Matches HSE Template)
    meeting_title = get(structured.get("meetingTitle"), "Capital & Estates Meeting")
    meeting_date = get(structured.get("meetingDate"), now.strftime("%d/%m/%Y"))
    start_time = get(structured.get("startTime"), "00:00")
    end_time = get(structured.get("endTime"), "00:00")
    location = get(structured.get("location"))
    chairperson = get(structured.get("chairperson"))
    minute_taker = get(structured.get("minuteTaker"))
    attendees = structured.get("attendees", [])
    apologies = structured.get("apologies", [])
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

    template = f"""HSE Capital & Estates Meeting Minutes
Meeting Title: {meeting_title}
Date: {meeting_date} | Time: {start_time} - {end_time}
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
2. Minutes of Previous Meeting / Matters Arising
{bullets(matters_arising)}
________________________________________
3. Declarations of Interest
• {declarations_of_interest}
________________________________________
4. Capital Projects Update
4.1 Major Projects (Capital)
{bullets(major_projects)}
4.2 Minor Works / Equipment / ICT
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
Minutes Approved By: ____________________ Date: ___________
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
        doc.add_heading("Executive Briefing Note", level=1)
        doc.add_paragraph(content)
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

# --- Setup & Config ---
st.set_page_config(page_title="MAI Recap Pro", layout="wide", page_icon="🏥")
inject_custom_css()

# --- API Config ---
try:
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel(model_name=GEMINI_MODEL_NAME)
    else:
        st.error("System Configuration Error: API Key missing.")
        st.stop()
except Exception as e:
    st.error(f"Configuration Error: {e}")
    st.stop()

# --- Authentication ---
if "password_verified" not in st.session_state:
    st.session_state.password_verified = False

if not st.session_state.password_verified:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=150)
        st.markdown("### MAI Recap Pro")
        st.caption("Capital & Estates Secure Login")
        
        with st.form("password_form"):
            user_password = st.text_input("Authorisation Code", type="password")
            if st.form_submit_button("Log In"):
                if st.secrets.get("password") and user_password == st.secrets["password"]:
                    st.session_state.password_verified = True
                    st.rerun()
                elif not st.secrets.get("password"):
                     st.warning("System Config: Password not set.")
                else:
                    st.error("Incorrect authorisation code.")
    st.stop()

# --- Application State ---
if "transcript" not in st.session_state:
    st.session_state["transcript"] = ""
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Sidebar ---
with st.sidebar:
    st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=160)
    st.markdown("### System Status")
    st.success("Online: Cork Region")
    
    st.markdown("---")
    if st.button("New Session / Reset", type="secondary"):
        for key in list(st.session_state.keys()):
            if key != 'password_verified':
                del st.session_state[key]
        st.rerun()
    
    # Speaker Mapping
    if st.session_state.get("transcript"):
        st.markdown("---")
        st.markdown("**Speaker Identification**")
        detected_speakers = detect_speakers(st.session_state["transcript"])
        
        if detected_speakers:
            with st.form("speaker_map_form"):
                replacements = {}
                for spk in detected_speakers:
                    new_name = st.text_input(spk, placeholder="Enter Name")
                    if new_name and new_name != spk:
                        replacements[spk] = new_name
                
                if st.form_submit_button("Update Transcripts"):
                    txt = st.session_state["transcript"]
                    count = 0
                    for old, new in replacements.items():
                        txt = txt.replace(f"{old}:", f"{new}:")
                        txt = txt.replace(f"**{old}**", f"**{new}**")
                    st.session_state["transcript"] = txt
                    st.rerun()

# --- Header ---
c_logo, c_title = st.columns([1, 6])
with c_logo:
     # Standard HSE logo, no inversion filter
    st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=100)
with c_title:
    st.title("MAI Recap Pro")
    st.markdown("Capital & Estates | Automated Documentation System")

st.markdown("<hr style='border-top: 2px solid #00563B; margin-top: -10px;'>", unsafe_allow_html=True)

# --- Step 1: Input ---
if not st.session_state["transcript"]:
    
    # Context Box (Clean Grey)
    with st.container():
        st.markdown("**Meeting Context** (Optional)")
        st.markdown("Providing names and topics helps the system identify speakers and acronyms correctly.")
        context_info = st.text_area(
            "Details",
            placeholder="e.g. Chair: Sarah O'Brien. Attendees: Mr. Murphy, Dr. Smith. Topic: Mallow General Hospital Extension.",
            height=80,
            label_visibility="collapsed"
        )

    st.markdown("<br>", unsafe_allow_html=True)
    
    tab_rec, tab_up = st.tabs(["Audio Recording", "File Upload"])
    
    audio_bytes = None
    
    with tab_rec:
        recorded_audio = st.audio_input("Microphone Input")
        if recorded_audio:
            st.audio(recorded_audio)
            audio_bytes = recorded_audio

    with tab_up:
        uploaded_audio = st.file_uploader("Select Audio File (MP3, WAV, M4A)", type=["wav", "mp3", "m4a", "ogg"])
        if uploaded_audio:
            st.audio(uploaded_audio)
            audio_bytes = uploaded_audio

    if audio_bytes:
        if st.button("Process Audio"):
            with st.status("System Processing...", expanded=True) as status:
                try:
                    # 1. Temp File
                    status.write("Encrypting and preparing file...")
                    if hasattr(audio_bytes, "read"):
                        audio_bytes.seek(0)
                        data = audio_bytes.read()
                    else:
                        data = audio_bytes
                    
                    suffix = ".wav"
                    if hasattr(audio_bytes, 'name'):
                        _, ext = os.path.splitext(audio_bytes.name)
                        if ext: suffix = ext
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(data)
                        tmp_path = tmp.name

                    # 2. Upload
                    status.write("Transmitting to secure processing engine...")
                    gemini_file = genai.upload_file(path=tmp_path)
                    
                    while gemini_file.state.name == "PROCESSING":
                        import time
                        time.sleep(2)
                        gemini_file = genai.get_file(gemini_file.name)
                    
                    if gemini_file.state.name == "FAILED":
                        status.update(label="Processing Failed", state="error")
                        st.stop()

                    # 3. Transcribe
                    status.write("Generating transcription...")
                    context_prompt = f"Context: {context_info}" if context_info else ""
                    
                    # PROMPT: Strict Irish/UK English
                    prompt = f"""
                    You are a professional transcriber for HSE Capital & Estates Ireland.
                    {context_prompt}
                    Task: Transcribe the audio.
                    Language: Strict UK/Irish English spelling (e.g., 'Programme', 'Paediatric', 'Centre', 'Analysing').
                    Format: Use '**Speaker Name**:' followed by text.
                    Currency: Euro (€).
                    Speaker IDs: If unknown, use 'Speaker 1', 'Speaker 2'.
                    """
                    
                    # Call API with Try/Except wrapper
                    res = generate_content_safe(model, [prompt, gemini_file])
                    
                    if res:
                        text = get_text_from_response(res)
                        st.session_state["transcript"] = text
                        status.update(label="Complete", state="complete", expanded=False)
                        st.rerun()
                    else:
                        status.update(label="System Busy", state="error")

                except Exception as e:
                    status.update(label="Error", state="error")
                    st.error(f"Details: {e}")
                finally:
                    if 'gemini_file' in locals():
                        try: genai.delete_file(gemini_file.name)
                        except: pass
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

# --- Step 2: Output ---
else:
    # Dashboard Metrics
    word_count = len(st.session_state["transcript"].split())
    c1, c2, c3 = st.columns(3)
    c1.metric("Word Count", f"{word_count:,}")
    c2.metric("Date", datetime.now().strftime("%d %b %Y"))
    c3.metric("Status", "Active Session")
    
    st.markdown("<br>", unsafe_allow_html=True)

    t1, t2, t3, t4 = st.tabs(["Transcript", "Minutes Generator", "Executive Briefing", "Q&A Assistant"])

    # --- TAB 1: TRANSCRIPT ---
    with t1:
        st.markdown("#### Transcript Source")
        edited_text = st.text_area(
            "Editor", 
            value=st.session_state["transcript"], 
            height=600,
            key="transcript_editor",
            label_visibility="collapsed"
        )
        if edited_text != st.session_state["transcript"]:
            st.session_state["transcript"] = edited_text
            st.rerun()

    # --- TAB 2: MINUTES ---
    with t2:
        col_act, col_prev = st.columns([1, 2])
        with col_act:
            st.info("Parse transcript into standard HSE template.")
            if st.button("Generate Minutes"):
                with st.spinner("Processing..."):
                    prompt_minutes = f"""
                    You are an expert secretary for HSE Capital & Estates.
                    Extract structured data from this transcript.
                    Language: Irish/UK English. Currency: Euro (€).
                    Return valid JSON only.
                    TRANSCRIPT:
                    {st.session_state['transcript']}
                    """
                    # Robust API Call
                    res = generate_content_safe(model, prompt_minutes, is_json=True)
                    
                    if res:
                        text_response = get_text_from_response(res)
                        try:
                            structured = json.loads(text_response)
                            if isinstance(structured, list): structured = structured[0]
                            st.session_state["minutes_text"] = generate_capital_estates_minutes(structured)
                        except json.JSONDecodeError:
                            st.error("Error parsing AI response. Please try again.")

        with col_prev:
            if "minutes_text" in st.session_state:
                st.markdown("#### Preview")
                st.text_area("Draft", st.session_state["minutes_text"], height=500, label_visibility="collapsed")
                st.download_button(
                    "Download DOCX",
                    create_docx(st.session_state["minutes_text"]),
                    f"HSE_Minutes_{datetime.now().strftime('%Y%m%d')}.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )

    # --- TAB 3: BRIEFING ---
    with t3:
        if st.button("Generate Briefing Note"):
            with st.status("Analysing strategic points..."):
                p_insight = f"""
                Create a high-level "Executive Briefing Note" from this transcript.
                Language: Irish/UK English. Currency: Euro (€).
                Include: Executive Summary, Strategic Decisions, Action Items, Risk Analysis.
                TRANSCRIPT: {st.session_state['transcript']}
                """
                # Robust API Call
                res = generate_content_safe(model, p_insight)
                if res:
                    st.session_state["briefing"] = get_text_from_response(res)

        if "briefing" in st.session_state:
            st.markdown(st.session_state["briefing"])
            st.download_button("Download Briefing DOCX", create_docx(st.session_state["briefing"], "overview"), "Briefing.docx")

    # --- TAB 4: ASSISTANT ---
    with t4:
        st.markdown("#### Meeting Assistant")
        
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Query transcript..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                p_chat = f"""
                Answer strictly based on the transcript provided below.
                Language: Irish/UK English. Currency: Euro (€).
                TRANSCRIPT: {st.session_state['transcript']}
                QUESTION: {prompt}
                """
                with st.spinner("Thinking..."):
                    # Robust API Call
                    res = generate_content_safe(model, p_chat)
                    if res:
                        response = get_text_from_response(res)
                        st.markdown(response)
                        st.session_state.messages.append({"role": "assistant", "content": response})


