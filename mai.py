"""
MAI Recap Pro - Professional HSE Meeting Assistant
Version: 4.0 Professional Edition
"""

import streamlit as st
import google.generativeai as genai
import json
import os
from datetime import datetime
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import tempfile
import re
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path

# ==================== CONFIGURATION ====================
@dataclass
class AppConfig:
    """Application configuration"""
    GEMINI_MODEL_NAME: str = 'gemini-1.5-flash'
    MAX_TRANSCRIPT_LENGTH: int = 50000
    CACHE_TTL: int = 3600
    APP_VERSION: str = "4.0 Professional"
    HSE_GREEN: str = "#00563B"
    HSE_BLUE: str = "#005EB8"
    
config = AppConfig()

# ==================== LOGGING SETUP ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== CUSTOM EXCEPTIONS ====================
class TranscriptionError(Exception):
    """Custom exception for transcription failures"""
    pass

class APIConfigurationError(Exception):
    """Custom exception for API configuration issues"""
    pass

# ==================== PROMPT TEMPLATES ====================
class PromptTemplates:
    """Centralized prompt management with versioning"""
    
    TRANSCRIPTION_V1 = """You are a professional transcriber for HSE Capital & Estates.
{context}

Task: Transcribe the audio using strict Irish/UK English spelling (e.g. 'Analysing', 'Programme', 'Centre').
Format: Use '**Speaker Name**:' (bolded) followed by text. 
If you cannot identify the name, use '**Speaker 1**:', '**Speaker 2**:', etc.
Currency: Always use Euro (€).
Do not summarise yet, provide the full dialogue."""

    MINUTES_GENERATION_V2 = """You are an expert secretary for HSE Capital & Estates.
Extract detailed structured data from this transcript (Irish/UK English spelling).
Dates: DD/MM/YYYY. Currency: Euro (€).

Return valid JSON only:
{{
    "meetingTitle": "...", "meetingDate": "...", "startTime": "...", "endTime": "...",
    "location": "...", "chairperson": "...", "minuteTaker": "...",
    "attendees": ["Name 1", "Name 2"], "apologies": [],
    "previousMeetingDate": "...", "mattersArising": ["Item 1", "Item 2"],
    "declarationsOfInterest": "...",
    "majorProjects": ["Project A details", "Project B details"],
    "minorProjects": ["..."], "estatesStrategy": ["..."], 
    "healthSafety": ["..."], "riskRegister": ["..."], "financeUpdate": ["..."],
    "aob": ["..."], "nextMeetingDate": "...", "meetingClosedTime": "..."
}}

TRANSCRIPT:
{transcript}"""

    BRIEFING_V1 = """Create a high-level "Briefing Document" (Markdown) from this transcript using Irish/UK English.
Currency: Euro (€).

Include:
1. Executive Summary
2. Key Strategic Decisions
3. Action Items (Table format: Who | What)
4. Contentious Issues / Risks

TRANSCRIPT: {transcript}"""

    CHAT_V1 = """Answer strictly based on the transcript provided below. Use Irish/UK English spelling.
Currency: Euro (€).

TRANSCRIPT: {transcript}

QUESTION: {question}"""

# ==================== UTILITY FUNCTIONS ====================
def prettify_key(key: str) -> str:
    """Converts camelCase or snake_case to Title Case."""
    key = key.replace('_', ' ')
    key = re.sub(r'([a-z])([A-Z])', r'\1 \2', key)
    return key.title() + ":"

def get_gemini_text_safe(response: Any) -> str:
    """Safely extracts text from a Gemini response."""
    try:
        return response.text
    except ValueError:
        error_msg = "⚠️ Model response was blocked or empty."
        if hasattr(response, "candidates") and response.candidates:
            finish_reason = response.candidates[0].finish_reason
            error_msg += f" (Reason: {finish_reason})"
        logger.error(error_msg)
        return error_msg

def detect_speakers(text: str) -> List[str]:
    """
    Scans the transcript for speaker patterns.
    
    Args:
        text: Raw transcript text
        
    Returns:
        List of unique speaker identifiers
    """
    if not text:
        return []
    
    pattern = r'(?m)^(?:[\*\_]{2})?([A-Za-z0-9\s\(\)\-\.]+?)(?:[\*\_]{2})?[:]'
    matches = re.findall(pattern, text)
    unique_speakers = sorted(list(set(matches)))
    clean_speakers = [s for s in unique_speakers if len(s) < 30 and s.strip()]
    
    logger.info(f"Detected {len(clean_speakers)} speakers")
    return clean_speakers

# ==================== STATE MANAGEMENT ====================
class SessionState:
    """Centralized session state management"""
    
    @staticmethod
    def initialize():
        """Initialize session state with defaults"""
        defaults = {
            "transcript": "",
            "messages": [],
            "minutes_text": None,
            "briefing": None,
            "password_verified": False,
            "processing_stats": {}
        }
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value
    
    @staticmethod
    def reset_meeting_data():
        """Clear meeting data while preserving auth"""
        keys_to_keep = {"password_verified"}
        for key in list(st.session_state.keys()):
            if key not in keys_to_keep:
                del st.session_state[key]
        SessionState.initialize()

# ==================== MINUTES GENERATOR ====================
def generate_capital_estates_minutes(structured: Dict[str, Any]) -> str:
    """Generate formatted HSE minutes from structured data"""
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

# ==================== DOCX CREATION ====================
def create_professional_docx(content: str, kind: str = "minutes") -> io.BytesIO:
    """Create a professionally formatted DOCX document"""
    doc = Document()
    
    # Add HSE header
    header = doc.sections[0].header
    header_para = header.paragraphs[0]
    header_para.text = "Health Service Executive - Capital & Estates"
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    if kind == "minutes":
        # Title
        title = doc.add_heading("Meeting Minutes", level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        for line in content.splitlines():
            if line.strip(" _").endswith(":") and not line.startswith("•"):
                heading = doc.add_heading(line.strip(), level=2)
                run = heading.runs[0]
                run.font.color.rgb = RGBColor(0, 86, 59)  # HSE Green
            elif line.strip() == "________________________________________":
                doc.add_paragraph("-" * 50)
            elif line.strip():
                para = doc.add_paragraph(line)
                if line.startswith("•"):
                    para.style = 'List Bullet'
    else:
        doc.add_heading("Meeting Briefing / Overview", level=1)
        doc.add_paragraph(content)
    
    # Footer
    footer = doc.sections[0].footer
    footer_para = footer.paragraphs[0]
    footer_para.text = f"Generated by MAI Recap Pro v{config.APP_VERSION} | {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

# ==================== API CONFIGURATION ====================
@st.cache_resource
def configure_gemini_api() -> genai.GenerativeModel:
    """Configure and return Gemini API model"""
    try:
        api_key = None
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
        elif os.getenv("GEMINI_API_KEY"):
            api_key = os.getenv("GEMINI_API_KEY")
        
        if not api_key:
            raise APIConfigurationError("GEMINI_API_KEY not found")
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name=config.GEMINI_MODEL_NAME)
        logger.info(f"Gemini API configured with model: {config.GEMINI_MODEL_NAME}")
        return model
    except Exception as e:
        logger.error(f"API configuration failed: {e}")
        raise APIConfigurationError(f"Failed to configure API: {e}")

# ==================== CUSTOM CSS ====================
def load_custom_css():
    """Load enhanced custom CSS with animations"""
    st.markdown("""
    <style>
        /* Import Google Fonts */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
        
        /* Global Styles */
        * {
            font-family: 'Inter', sans-serif;
        }
        
        .main {
            background: linear-gradient(135deg, #f5f7fa 0%, #e9ecef 100%);
        }
        
        /* Header Styles */
        h1 {
            color: #00563B !important;
            font-weight: 700 !important;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
            animation: fadeInDown 0.8s ease-in-out;
        }
        
        h2, h3 {
            color: #005EB8 !important;
            font-weight: 600 !important;
        }
        
        /* Card Effect for Tabs */
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
            background: white;
            padding: 10px;
            border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        
        .stTabs [data-baseweb="tab"] {
            height: 50px;
            padding: 0 24px;
            border-radius: 8px;
            transition: all 0.3s ease;
        }
        
        .stTabs [data-baseweb="tab"]:hover {
            background-color: rgba(0, 86, 59, 0.1);
            transform: translateY(-2px);
        }
        
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background: linear-gradient(135deg, #00563B 0%, #007850 100%);
            color: white !important;
        }
        
        /* Button Enhancements */
        .stButton > button {
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.15);
        }
        
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #00563B 0%, #007850 100%);
        }
        
        /* Input Fields */
        .stTextInput > div > div > input,
        .stTextArea > div > div > textarea {
            border-radius: 8px;
            border: 2px solid #e0e0e0;
            transition: border-color 0.3s ease;
        }
        
        .stTextInput > div > div > input:focus,
        .stTextArea > div > div > textarea:focus {
            border-color: #00563B;
            box-shadow: 0 0 0 3px rgba(0, 86, 59, 0.1);
        }
        
        /* Status Widget */
        div[data-testid="stStatusWidget"] {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            animation: slideInUp 0.5s ease-out;
        }
        
        /* Info/Warning/Success Boxes */
        .stAlert {
            border-radius: 10px;
            border-left: 4px solid;
            animation: slideInLeft 0.5s ease-out;
        }
        
        /* Sidebar Styling */
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #00563B 0%, #004d34 100%);
        }
        
        section[data-testid="stSidebar"] * {
            color: white !important;
        }
        
        /* Custom Card Component */
        .metric-card {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            border-left: 4px solid #00563B;
            margin: 10px 0;
            transition: transform 0.3s ease;
        }
        
        .metric-card:hover {
            transform: translateX(5px);
        }
        
        .metric-value {
            font-size: 2em;
            font-weight: 700;
            color: #00563B;
        }
        
        .metric-label {
            font-size: 0.9em;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        /* Loading Spinner */
        .stSpinner > div {
            border-top-color: #00563B !important;
        }
        
        /* Animations */
        @keyframes fadeInDown {
            from {
                opacity: 0;
                transform: translateY(-20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        @keyframes slideInUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        @keyframes slideInLeft {
            from {
                opacity: 0;
                transform: translateX(-20px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        /* Pulse Animation for Important Elements */
        .pulse {
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% {
                opacity: 1;
            }
            50% {
                opacity: 0.7;
            }
        }
        
        /* Progress Bar */
        .stProgress > div > div > div {
            background: linear-gradient(90deg, #00563B 0%, #007850 100%);
        }
        
        /* Download Button Special Styling */
        .stDownloadButton > button {
            background: linear-gradient(135deg, #005EB8 0%, #0077cc 100%);
            color: white;
        }
        
        /* Chat Messages */
        .stChatMessage {
            background: white;
            border-radius: 10px;
            padding: 15px;
            margin: 10px 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            animation: slideInLeft 0.3s ease-out;
        }
    </style>
    """, unsafe_allow_html=True)

# ==================== MAIN APPLICATION ====================
def main():
    """Main application entry point"""
    
    # Page Configuration
    st.set_page_config(
        page_title="MAI Recap Pro",
        layout="wide",
        page_icon="📝",
        initial_sidebar_state="expanded"
    )
    
    # Load Custom CSS
    load_custom_css()
    
    # Initialize State
    SessionState.initialize()
    
    # Configure API
    try:
        model = configure_gemini_api()
    except APIConfigurationError as e:
        st.error(f"⚠️ {str(e)}")
        st.info("Please configure GEMINI_API_KEY in secrets or environment variables.")
        st.stop()
    
    # ==================== AUTHENTICATION ====================
    if not st.session_state.password_verified:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("""
            <div style="text-align: center; animation: fadeInDown 1s ease-out;">
                <img src="https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png" width="120" style="margin-bottom: 20px;">
                <h1 style="color: #00563B; margin-bottom: 10px;">MAI Recap Pro</h1>
                <p style="color: #666; font-size: 1.1em;">Secure Access Portal</p>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            with st.container():
                st.markdown("""
                <div class="metric-card">
                    <div style="text-align: center;">
                        <p style="font-size: 0.9em; color: #666;">🔒 Restricted Access</p>
                        <p style="font-size: 0.85em; color: #999;">HSE Capital & Estates AI Tool</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                with st.form("password_form"):
                    user_password = st.text_input("Access Password", type="password", placeholder="Enter your credentials")
                    col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
                    with col_btn2:
                        submit = st.form_submit_button("🔓 Secure Login", use_container_width=True)
                    
                    if submit:
                        if st.secrets.get("password") and user_password == st.secrets["password"]:
                            st.session_state.password_verified = True
                            logger.info("User authenticated successfully")
                            st.rerun()
                        elif not st.secrets.get("password"):
                            st.warning("⚠️ Password not configured in secrets.toml.")
                        else:
                            st.error("❌ Invalid credentials. Access denied.")
                            logger.warning("Failed login attempt")
        st.stop()
    
    # ==================== SIDEBAR ====================
    with st.sidebar:
        st.markdown("""
        <div style="text-align: center; padding: 20px 0;">
            <img src="https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png" width="160">
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="metric-card" style="background: rgba(255,255,255,0.1); border-left-color: white;">
            <div class="metric-label" style="color: rgba(255,255,255,0.8);">Engine</div>
            <div style="color: white; font-weight: 600;">{config.GEMINI_MODEL_NAME}</div>
            <div class="metric-label" style="color: rgba(255,255,255,0.8); margin-top: 10px;">Version</div>
            <div style="color: white; font-weight: 600;">{config.APP_VERSION}</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("### 🛠️ Session Tools")
        if st.button("🗑️ New Meeting", type="primary", use_container_width=True):
            SessionState.reset_meeting_data()
            logger.info("Session reset by user")
            st.rerun()
        
        st.markdown("---")
        
        # Speaker Mapping
        if st.session_state.get("transcript"):
            st.markdown("### 👥 Speaker Manager")
            st.info("Map generic IDs to real names")
            
            detected_speakers = detect_speakers(st.session_state["transcript"])
            
            if not detected_speakers:
                st.caption("No speaker labels detected")
            else:
                with st.form("speaker_map_form"):
                    st.markdown("#### Rename speakers:")
                    replacements = {}
                    for spk in detected_speakers:
                        new_name = st.text_input(f"**{spk}** →", placeholder="e.g. Dr. O'Connor")
                        if new_name and new_name != spk:
                            replacements[spk] = new_name
                    
                    if st.form_submit_button("✅ Update Documents", use_container_width=True):
                        txt = st.session_state["transcript"]
                        count = 0
                        for old, new in replacements.items():
                            patterns = [f"{old}:", f"**{old}**:", f"**{old}**"]
                            for pattern in patterns:
                                if pattern in txt:
                                    replacement = pattern.replace(old, new)
                                    txt = txt.replace(pattern, replacement)
                                    count += 1
                        
                        st.session_state["transcript"] = txt
                        if count > 0:
                            st.toast(f"✅ Updated {count} speaker references", icon="✅")
                            logger.info(f"Updated {count} speaker references")
                        else:
                            st.toast("⚠️ No changes made", icon="⚠️")
                        st.rerun()
        
        # Statistics
        if st.session_state.get("processing_stats"):
            st.markdown("---")
            st.markdown("### 📊 Session Stats")
            stats = st.session_state["processing_stats"]
            for key, value in stats.items():
                st.metric(key, value)
    
    # ==================== MAIN HEADER ====================
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=80)
    with col_title:
        st.markdown("""
        <h1 style="margin-bottom: 0;">MAI Recap Pro</h1>
        <p style="color: #666; font-size: 1.1em; margin-top: 5px;">HSE Minute-AI Generator & Meeting Assistant</p>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ==================== STEP 1: INPUT ====================
    if not st.session_state["transcript"]:
        st.markdown("""
        <div class="metric-card">
            <h3 style="color: #00563B; margin-top: 0;">📥 Meeting Source Input</h3>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander("ℹ️ Provide Context (Recommended)", expanded=True):
            context_info = st.text_area(
                "Meeting Context & Attendees:",
                placeholder="e.g., Present: Dr. Smith, Mr. Murphy. Chair: Sarah O'Brien. Topic: Budget Review Q4 2024.",
                help="Providing names helps AI identify speakers accurately",
                height=100
            )
        
        tab_rec, tab_up = st.tabs(["🎙️ Record Audio", "📁 Upload File"])
        
        audio_bytes = None
        
        with tab_rec:
            st.markdown("**Live Recording**")
            recorded_audio = st.audio_input("Click to start recording")
            if recorded_audio:
                st.audio(recorded_audio)
                audio_bytes = recorded_audio
        
        with tab_up:
            st.markdown("**File Upload**")
            uploaded_audio = st.file_uploader(
                "Upload Audio File",
                type=["wav", "mp3", "m4a", "ogg"],
                help="Supported formats: WAV, MP3, M4A, OGG"
            )
            if uploaded_audio:
                st.audio(uploaded_audio)
                audio_bytes = uploaded_audio
        
        if audio_bytes:
            col_process1, col_process2, col_process3 = st.columns([1, 2, 1])
            with col_process2:
                if st.button("🚀 Process Meeting Audio", type="primary", use_container_width=True):
                    with st.status("Processing Meeting Audio...", expanded=True) as status:
                        try:
                            start_time = datetime.now()
                            
                            # Prepare File
                            status.write("📁 Preparing audio file...")
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
                            
                            file_size_mb = len(data) / (1024 * 1024)
                            status.write(f"✅ File prepared ({file_size_mb:.2f} MB)")
                            
                            # Upload to Gemini
                            status.write(f"☁️ Uploading to {config.GEMINI_MODEL_NAME}...")
                            gemini_file = genai.upload_file(path=tmp_path)
                            
                            # Wait for processing
                            status.write("⏳ Processing audio...")
                            import time
                            while gemini_file.state.name == "PROCESSING":
                                time.sleep(2)
                                gemini_file = genai.get_file(gemini_file.name)
                            
                            if gemini_file.state.name == "FAILED":
                                raise TranscriptionError("Audio processing failed on Gemini servers")
                            
                            # Transcribe
                            status.write("🎯 Transcribing and identifying speakers...")
                            context_prompt = f"Context/Attendees: {context_info}" if
