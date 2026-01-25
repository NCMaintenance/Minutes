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
GEMINI_MODEL_NAME = 'gemini-3-flash-preview'

# --- Custom CSS / Theming (The "100k" Look) ---
def inject_custom_css():
    st.markdown("""
    <style>
        /* IMPORT FONTS */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');

        /* MAIN BACKGROUND - Deep HSE Executive Theme */
        .stApp {
            background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
            font-family: 'Inter', sans-serif;
        }

        /* SIDEBAR - Frosted Glass */
        section[data-testid="stSidebar"] {
            background: rgba(0, 20, 10, 0.6);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }
        
        /* SIDEBAR TEXT */
        section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] p {
            color: #dcdcdc !important;
        }

        /* GLOBAL TEXT COLORS */
        h1, h2, h3, h4, h5, h6 {
            color: #ffffff !important;
            font-weight: 700;
            letter-spacing: -0.5px;
            text-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        p, label, li, .stMarkdown {
            color: #e0e6ed !important;
        }

        /* CARDS / CONTAINERS - The "Glass" Effect */
        div[data-testid="stExpander"], div[data-testid="stForm"], .stTabs [data-baseweb="tab-panel"] {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            padding: 20px;
            margin-bottom: 20px;
        }

        /* INPUT FIELDS - Dark Glass */
        .stTextInput > div > div > input, .stTextArea > div > div > textarea, .stSelectbox > div > div > div {
            background-color: rgba(0, 0, 0, 0.3) !important;
            color: white !important;
            border: 1px solid rgba(255, 255, 255, 0.15) !important;
            border-radius: 10px;
            backdrop-filter: blur(10px);
        }
        .stTextInput > div > div > input:focus, .stTextArea > div > div > textarea:focus {
            border-color: #00d2ff !important;
            box-shadow: 0 0 10px rgba(0, 210, 255, 0.2);
        }

        /* BUTTONS - Gradient & Glow */
        .stButton > button {
            background: linear-gradient(92.88deg, #00563B 9.16%, #007A53 43.89%, #009E6B 64.72%);
            color: white;
            font-weight: 600;
            border: none;
            border-radius: 8px;
            padding: 0.6rem 1.2rem;
            transition: all 0.3s ease;
            box-shadow: 0 4px 14px 0 rgba(0, 118, 83, 0.39);
        }
        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 158, 107, 0.5);
            color: #fff !important;
        }
        
        /* SECONDARY BUTTONS (e.g. Stop) */
        div[data-testid="stButton"] button[kind="secondary"] {
            background: transparent;
            border: 1px solid rgba(255,255,255,0.3);
        }

        /* TABS Styling */
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
            background-color: transparent;
        }
        .stTabs [data-baseweb="tab"] {
            height: 50px;
            white-space: pre-wrap;
            background-color: rgba(255,255,255,0.05);
            border-radius: 10px 10px 0 0;
            gap: 1px;
            padding-top: 10px;
            padding-bottom: 10px;
            color: #a0a0a0;
            border: 1px solid transparent;
        }
        .stTabs [aria-selected="true"] {
            background-color: rgba(255,255,255,0.1) !important;
            color: white !important;
            border-bottom: 2px solid #00d2ff !important;
        }

        /* STATUS WIDGET */
        div[data-testid="stStatusWidget"] {
            background: rgba(0, 50, 30, 0.8);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            color: white;
        }
        
        /* SCROLLBARS */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #0f2027; 
        }
        ::-webkit-scrollbar-thumb {
            background: #2c5364; 
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #00563B; 
        }
    </style>
    """, unsafe_allow_html=True)

# --- Utility Functions ---

def prettify_key(key):
    """Converts camelCase or snake_case to Title Case."""
    key = key.replace('_', ' ')
    key = re.sub(r'([a-z])([A-Z])', r'\1 \2', key)
    return key.title() + ":"

def get_gemini_text_safe(response):
    """Safely extracts text from a Gemini response."""
    try:
        return response.text
    except ValueError:
        error_msg = "⚠️ Model response was blocked or empty."
        if hasattr(response, "candidates") and response.candidates:
            finish_reason = response.candidates[0].finish_reason
            error_msg += f" (Reason: {finish_reason})"
        return error_msg

def detect_speakers(text):
    """
    Scans the transcript for patterns like 'Speaker 1:', '**Speaker 1**:', etc.
    """
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
    
    def get(val, default="Not mentioned"):
        return val if val and val != "Not mentioned" else default

    def bullets(val):
        if isinstance(val, list) and val:
            valid_items = [v for v in val if v and str(v).strip()]
            return "".join([f"• {item}\n" for item in valid_items])
        elif isinstance(val, str) and val.strip():
            return f"• {val}\n"
        else:
            return "Not mentioned\n"

    # Fields mapping
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
        doc.add_heading("Meeting Briefing / Overview", level=1)
        doc.add_paragraph(content)
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

# --- Setup & Config ---
st.set_page_config(page_title="MAI Recap Pro", layout="wide", page_icon="🏛️")
inject_custom_css()

try:
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel(model_name=GEMINI_MODEL_NAME)
    else:
        st.error("GEMINI_API_KEY not found in Streamlit secrets.")
        st.stop()
except Exception as e:
    st.error(f"Error configuring Gemini API: {e}")
    st.info("Please ensure you have access to 'gemini-3-flash-preview' or update the code to use 'gemini-1.5-pro'.")
    st.stop()

# --- Authentication ---
if "password_verified" not in st.session_state:
    st.session_state.password_verified = False

if not st.session_state.password_verified:
    # Use empty containers for centering in the new layout
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown(
            """
            <div style="text-align: center; padding: 40px; background: rgba(0,0,0,0.2); border-radius: 20px; backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1);">
                <img src="https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png" style="filter: brightness(0) invert(1);" width="120">
                <h1 style="margin-top: 20px;">MAI Recap Pro</h1>
                <p style="opacity: 0.8;">Secure Enterprise Access</p>
            </div>
            <br>
            """, 
            unsafe_allow_html=True
        )
        with st.form("password_form"):
            st.markdown("Enter your credentials to access the Capital & Estates engine.")
            user_password = st.text_input("Access Key", type="password")
            submitted = st.form_submit_button("Authenticate System")
            
            if submitted:
                if st.secrets.get("password") and user_password == st.secrets["password"]:
                    st.session_state.password_verified = True
                    st.rerun()
                elif not st.secrets.get("password"):
                     st.warning("Password not configured in secrets.toml.")
                else:
                    st.error("Access Denied.")
    st.stop()

# --- Application State ---
if "transcript" not in st.session_state:
    st.session_state["transcript"] = ""
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Sidebar Controls ---
with st.sidebar:
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 20px;">
            <img src="https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png" style="filter: brightness(0) invert(1); opacity: 0.9;" width="140">
        </div>
        """, unsafe_allow_html=True
    )
    st.markdown("### System Status")
    st.markdown(f"**Engine:** `{GEMINI_MODEL_NAME}`")
    st.markdown("**Version:** v4.0 (Glass UI)")
    st.markdown("**Region:** Cork, IE")
    
    st.markdown("---")
    st.markdown("### 🛠️ Session Tools")
    if st.button("🗑️ Reset Session", type="primary"):
        for key in list(st.session_state.keys()):
            if key != 'password_verified':
                del st.session_state[key]
        st.rerun()
    
    # --- SPEAKER MAPPING LOGIC ---
    if st.session_state.get("transcript"):
        st.markdown("---")
        st.subheader("👥 Speaker ID")
        st.caption("Map generic IDs to real names.")
        
        detected_speakers = detect_speakers(st.session_state["transcript"])
        
        if not detected_speakers:
            st.caption("No speaker labels detected.")
        else:
            with st.form("speaker_map_form"):
                replacements = {}
                for spk in detected_speakers:
                    new_name = st.text_input(f"ID for: {spk}", placeholder="e.g. Dr. O'Connor")
                    if new_name and new_name != spk:
                        replacements[spk] = new_name
                
                if st.form_submit_button("Update Transcript"):
                    txt = st.session_state["transcript"]
                    count = 0
                    for old, new in replacements.items():
                        if f"{old}:" in txt:
                            txt = txt.replace(f"{old}:", f"{new}:")
                            count += 1
                        elif f"**{old}**:" in txt:
                            txt = txt.replace(f"**{old}**:", f"**{new}**:")
                            count += 1
                        elif f"**{old}**" in txt:
                             txt = txt.replace(f"**{old}**", f"**{new}**")
                             count += 1

                    st.session_state["transcript"] = txt
                    if count > 0:
                        st.toast(f"Success! Updated speakers in transcript.", icon="✅")
                    else:
                        st.toast("No changes made.", icon="⚠️")
                    st.rerun()

# --- Main Layout ---
col_title, col_status = st.columns([3, 1])
with col_title:
    st.title("MAI Recap Pro")
    st.markdown("<h4 style='font-weight: 300; opacity: 0.7; margin-top: -15px;'>Capital & Estates Intelligent Assistant</h4>", unsafe_allow_html=True)

# --- Step 1: Input & Processing ---
if not st.session_state["transcript"]:
    st.markdown("<br>", unsafe_allow_html=True)
    st.info("👋 Welcome. Please upload a meeting audio file to begin the analysis.")
    
    # Glass Container for Context
    with st.expander("ℹ️ Meeting Context (Recommended)", expanded=True):
        col_c1, col_c2 = st.columns([1,1])
        with col_c1:
            context_info = st.text_area(
                "Attendees & Topics",
                placeholder="e.g. Chair: Sarah O'Brien. Present: Mr. Murphy, Dr. Smith. Topic: Budget Review.",
                height=100
            )
        with col_c2:
            st.markdown("""
            **Why add context?**
            * Helps identifying speakers by name immediately.
            * Improves acronym recognition (e.g. 'PCRs', 'CapEx').
            * Clarifies ambiguous terms.
            """)

    # Glass Tabs
    tab_rec, tab_up = st.tabs(["🎙️ Record Audio", "📁 Upload File"])
    
    audio_bytes = None
    
    with tab_rec:
        st.markdown("##### Microphone Input")
        recorded_audio = st.audio_input("Start Recording")
        if recorded_audio:
            st.audio(recorded_audio)
            audio_bytes = recorded_audio

    with tab_up:
        st.markdown("##### File Input")
        uploaded_audio = st.file_uploader("Upload Audio (MP3, WAV, M4A)", type=["wav", "mp3", "m4a", "ogg"])
        if uploaded_audio:
            st.audio(uploaded_audio)
            audio_bytes = uploaded_audio

    if audio_bytes:
        st.markdown("---")
        if st.button("🚀 Initiate Processing Sequence"):
            with st.status("Processing Meeting Audio...", expanded=True) as status:
                try:
                    # 1. Prepare File
                    status.write("Encryption & Upload Sequence...")
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

                    # 2. Upload to Gemini
                    status.write(f"Transmitting to {GEMINI_MODEL_NAME} Secure Cloud...")
                    gemini_file = genai.upload_file(path=tmp_path)
                    
                    while gemini_file.state.name == "PROCESSING":
                        import time
                        time.sleep(2)
                        gemini_file = genai.get_file(gemini_file.name)
                    
                    if gemini_file.state.name == "FAILED":
                        status.update(label="Audio processing failed", state="error")
                        st.stop()

                    # 3. Transcribe
                    status.write("Generating Transcript & Speaker Diarization...")
                    context_prompt = f"Context/Attendees: {context_info}" if context_info else ""
                    prompt = f"""
                    You are a professional transcriber for HSE Capital & Estates.
                    {context_prompt}
                    Task: Transcribe the audio using strict Irish/UK English spelling.
                    Format: Use '**Speaker Name**:' (bolded) followed by text. 
                    If you cannot identify the name, use '**Speaker 1**:', '**Speaker 2**:', etc.
                    Currency: Always use Euro (€).
                    Do not summarise yet, provide the full dialogue.
                    """
                    
                    res = model.generate_content([prompt, gemini_file])
                    text = get_gemini_text_safe(res)
                    
                    if "⚠️" in text:
                        status.update(label="AI Safety Block Triggered", state="error")
                        st.error(text)
                    else:
                        st.session_state["transcript"] = text
                        status.update(label="Analysis Complete!", state="complete", expanded=False)
                        st.rerun()

                except Exception as e:
                    status.update(label="System Error", state="error")
                    st.error(f"Error details: {e}")
                finally:
                    if 'gemini_file' in locals():
                        try: genai.delete_file(gemini_file.name)
                        except: pass
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

# --- Step 2: Post-Processing Interface ---
else:
    # Stats Bar
    word_count = len(st.session_state["transcript"].split())
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Word Count", f"{word_count:,}")
    col_s2.metric("Date", datetime.now().strftime("%d %b %Y"))
    col_s3.metric("Status", "Active", "Verified")
    
    st.markdown("<br>", unsafe_allow_html=True)

    t1, t2, t3, t4 = st.tabs(["📝 Transcript Editor", "📄 Minutes Generator", "🔍 Executive Briefing", "💬 AI Assistant"])

    # --- TAB 1: EDIT TRANSCRIPT ---
    with t1:
        st.markdown("#### Source Transcript")
        edited_text = st.text_area(
            "Raw text content (Editable)", 
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
            st.info("Click below to parse the transcript into the standard HSE C&E format.")
            if st.button("✨ Generate Minutes", type="primary"):
                with st.spinner("Structuring data..."):
                    prompt_minutes = f"""
                    You are an expert secretary for HSE Capital & Estates.
                    Extract detailed structured data from this transcript (Irish/UK English spelling).
                    Dates: DD/MM/YYYY. Currency: Euro (€).
                    Return valid JSON only.
                    TRANSCRIPT:
                    {st.session_state['transcript']}
                    """
                    try:
                        res = model.generate_content(prompt_minutes, generation_config={"response_mime_type": "application/json"})
                        text_response = get_gemini_text_safe(res)
                        structured = json.loads(text_response)
                        if isinstance(structured, list): structured = structured[0]
                        st.session_state["minutes_text"] = generate_capital_estates_minutes(structured)
                    except Exception as e:
                        st.error(f"Generation Error: {e}")

        with col_prev:
            if "minutes_text" in st.session_state:
                st.markdown("#### Preview")
                st.text_area("Draft Minutes", st.session_state["minutes_text"], height=500, label_visibility="collapsed")
                st.download_button(
                    "📥 Download DOCX",
                    create_docx(st.session_state["minutes_text"]),
                    f"HSE_Minutes_{datetime.now().strftime('%Y%m%d')}.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )

    # --- TAB 3: INSIGHTS ---
    with t3:
        if st.button("📊 Generate Executive Briefing"):
            with st.status("Analyzing strategic points..."):
                p_insight = f"""
                Create a high-level "Briefing Document" (Markdown) from this transcript using Irish/UK English.
                Currency: Euro (€).
                Include: Executive Summary, Strategic Decisions, Action Items, Risks.
                TRANSCRIPT: {st.session_state['transcript']}
                """
                res = model.generate_content(p_insight)
                st.session_state["briefing"] = get_gemini_text_safe(res)

        if "briefing" in st.session_state:
            st.markdown(st.session_state["briefing"])
            st.download_button("📥 Download Briefing DOCX", create_docx(st.session_state["briefing"], "overview"), "Briefing.docx")

    # --- TAB 4: CHAT ---
    with t4:
        st.markdown("#### Interactive Assistant")
        
        # Chat container styled as a glass panel
        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        if prompt := st.chat_input("Ask about the meeting..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                p_chat = f"""
                Answer strictly based on the transcript provided below. Use Irish/UK English spelling.
                Currency: Euro (€).
                TRANSCRIPT: {st.session_state['transcript']}
                QUESTION: {prompt}
                """
                with st.spinner("Thinking..."):
                    res = model.generate_content(p_chat)
                    response = get_gemini_text_safe(res)
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})

