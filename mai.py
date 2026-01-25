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

Return valid JSON only. Do not wrap in markdown code blocks.
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
    """
    if not text:
        return []
    
    pattern = r'(?m)^(?:[\*\_]{2})?([A-Za-z0-9\s\(\)\-\.]+?)(?:[\*\_]{2})?[:]'
    matches = re.findall(pattern, text)
    unique_speakers = sorted(list(set(matches)))
    clean_speakers = [s for s in unique_speakers if len(s) < 30 and s.strip()]
    
    logger.info(f"Detected {len(clean_speakers)} speakers")
    return clean_speakers

def clean_json_response(text: str) -> str:
    """Cleans markdown code blocks from JSON response."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

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
    try:
        header_para = header.paragraphs[0]
    except IndexError:
        header_para = header.add_paragraph()
        
    header_para.text = "Health Service Executive - Capital & Estates"
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    if kind == "minutes":
        # Title
        title = doc.add_heading("Meeting Minutes", level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        for line in content.splitlines():
            clean_line = line.strip()
            if clean_line.endswith(":") and not clean_line.startswith("•") and not clean_line.startswith("Minutes Prepared"):
                heading = doc.add_heading(clean_line, level=2)
                if heading.runs:
                    run = heading.runs[0]
                    run.font.color.rgb = RGBColor(0, 86, 59)  # HSE Green
            elif "________________________________________" in clean_line:
                doc.add_paragraph("-" * 50)
            elif clean_line:
                para = doc.add_paragraph(clean_line)
                if clean_line.startswith("•"):
                    para.style = 'List Bullet'
    else:
        doc.add_heading("Meeting Briefing / Overview", level=1)
        doc.add_paragraph(content)
    
    # Footer
    footer = doc.sections[0].footer
    try:
        footer_para = footer.paragraphs[0]
    except IndexError:
        footer_para = footer.add_paragraph()
        
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
        @import url('[https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap](https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap)');
        * { font-family: 'Inter', sans-serif; }
        .main { background: linear-gradient(135deg, #f5f7fa 0%, #e9ecef 100%); }
        h1 { color: #00563B !important; font-weight: 700 !important; }
        h2, h3 { color: #005EB8 !important; font-weight: 600 !important; }
        .stButton > button[kind="primary"] { background: linear-gradient(135deg, #00563B 0%, #007850 100%); }
        .metric-card {
            background: white; padding: 20px; border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-left: 4px solid #00563B;
            margin: 10px 0;
        }
        .metric-value { font-size: 2em; font-weight: 700; color: #00563B; }
        .metric-label { font-size: 0.9em; color: #666; text-transform: uppercase; }
        .stChatMessage { background: white; border-radius: 10px; padding: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# ==================== MAIN APPLICATION ====================
def main():
    st.set_page_config(page_title="MAI Recap Pro", layout="wide", page_icon="📝")
    load_custom_css()
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
            st.markdown(f"<h1 style='text-align: center; color: {config.HSE_GREEN};'>MAI Recap Pro</h1>", unsafe_allow_html=True)
            with st.container():
                with st.form("password_form"):
                    user_password = st.text_input("Access Password", type="password")
                    if st.form_submit_button("🔓 Login", use_container_width=True):
                        if st.secrets.get("password") and user_password == st.secrets["password"]:
                            st.session_state.password_verified = True
                            st.rerun()
                        elif not st.secrets.get("password"):
                            st.warning("⚠️ Password not configured in secrets.toml.")
                        else:
                            st.error("❌ Invalid credentials.")
        st.stop()
    
    # ==================== SIDEBAR ====================
    with st.sidebar:
        st.markdown(f"<h3 style='color: white;'>MAI Recap Pro</h3>", unsafe_allow_html=True)
        st.caption(f"v{config.APP_VERSION}")
        
        if st.button("🗑️ New Meeting", type="primary", use_container_width=True):
            SessionState.reset_meeting_data()
            st.rerun()
        
        if st.session_state.get("transcript"):
            st.markdown("---")
            st.markdown("### 👥 Speaker Manager")
            detected_speakers = detect_speakers(st.session_state["transcript"])
            
            with st.form("speaker_map_form"):
                replacements = {}
                for spk in detected_speakers:
                    new_name = st.text_input(f"**{spk}** →", placeholder="Real Name")
                    if new_name and new_name != spk:
                        replacements[spk] = new_name
                
                if st.form_submit_button("✅ Update Transcript"):
                    txt = st.session_state["transcript"]
                    count = 0
                    for old, new in replacements.items():
                        patterns = [f"{old}:", f"**{old}**:", f"**{old}**"]
                        for pattern in patterns:
                            if pattern in txt:
                                txt = txt.replace(pattern, pattern.replace(old, new))
                                count += 1
                    st.session_state["transcript"] = txt
                    st.success(f"Updated {count} references")
                    st.rerun()

    # ==================== MAIN HEADER ====================
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        # Use a placeholder or reliable URL for logo
        st.markdown("📝", unsafe_allow_html=True)
    with col_title:
        st.markdown("<h1 style='margin-bottom: 0;'>MAI Recap Pro</h1>", unsafe_allow_html=True)
        st.markdown("HSE Minute-AI Generator & Meeting Assistant")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ==================== APP LOGIC ====================
    
    # --- STEP 1: INPUT ---
    if not st.session_state["transcript"]:
        st.markdown("### 📥 Meeting Source Input")
        
        context_info = st.text_area(
            "Meeting Context & Attendees (Recommended):",
            placeholder="e.g., Present: Dr. Smith, Mr. Murphy. Topic: Budget Review.",
            height=100
        )
        
        tab_rec, tab_up = st.tabs(["🎙️ Record Audio", "📁 Upload File"])
        audio_bytes = None
        
        with tab_rec:
            recorded_audio = st.audio_input("Click to start recording")
            if recorded_audio: audio_bytes = recorded_audio
        
        with tab_up:
            uploaded_audio = st.file_uploader("Upload Audio File", type=["wav", "mp3", "m4a", "ogg"])
            if uploaded_audio: audio_bytes = uploaded_audio
        
        if audio_bytes:
            if st.button("🚀 Process Meeting Audio", type="primary", use_container_width=True):
                with st.status("Processing Meeting Audio...", expanded=True) as status:
                    try:
                        start_time = datetime.now()
                        status.write("📁 Preparing audio file...")
                        
                        # Handle file bytes
                        if hasattr(audio_bytes, "read"):
                            audio_bytes.seek(0)
                            data = audio_bytes.read()
                            file_name = audio_bytes.name
                        else:
                            data = audio_bytes
                            file_name = "recording.wav"

                        suffix = Path(file_name).suffix or ".wav"
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(data)
                            tmp_path = tmp.name
                        
                        file_size_mb = len(data) / (1024 * 1024)
                        
                        # Upload to Gemini
                        status.write(f"☁️ Uploading to {config.GEMINI_MODEL_NAME}...")
                        gemini_file = genai.upload_file(path=tmp_path)
                        
                        # Wait for processing
                        status.write("⏳ Analyzing audio...")
                        import time
                        while gemini_file.state.name == "PROCESSING":
                            time.sleep(2)
                            gemini_file = genai.get_file(gemini_file.name)
                        
                        if gemini_file.state.name == "FAILED":
                            raise TranscriptionError("Audio processing failed on Gemini servers")
                        
                        # Transcribe
                        status.write("🎯 Transcribing...")
                        context_prompt = f"Context/Attendees: {context_info}" if context_info else ""
                        full_prompt = PromptTemplates.TRANSCRIPTION_V1.format(context=context_prompt)
                        
                        response = model.generate_content([full_prompt, gemini_file])
                        transcript_text = get_gemini_text_safe(response)
                        
                        st.session_state["transcript"] = transcript_text
                        
                        # Stats
                        duration = (datetime.now() - start_time).total_seconds()
                        st.session_state["processing_stats"] = {
                            "Time": f"{duration:.1f}s",
                            "Size": f"{file_size_mb:.1f} MB"
                        }
                        
                        status.update(label="✅ Processing Complete!", state="complete", expanded=False)
                        st.rerun()

                    except Exception as e:
                        status.update(label="❌ Error Occurred", state="error")
                        st.error(f"Processing error: {str(e)}")
                        logger.error(f"Processing failed: {e}")
                    finally:
                        if 'tmp_path' in locals() and os.path.exists(tmp_path):
                            os.unlink(tmp_path)

    # --- STEP 2: OUTPUT & TOOLS ---
    else:
        tab_trans, tab_mins, tab_brief, tab_chat = st.tabs([
            "📝 Transcript", "📋 Minutes", "📄 Briefing", "💬 AI Chat"
        ])
        
        # --- TAB: TRANSCRIPT ---
        with tab_trans:
            col_t1, col_t2 = st.columns([3, 1])
            with col_t1:
                st.subheader("Raw Transcript")
            with col_t2:
                st.download_button(
                    "📥 Download TXT",
                    st.session_state["transcript"],
                    file_name="transcript.txt"
                )
            
            edited_transcript = st.text_area(
                "Edit transcript if needed:",
                value=st.session_state["transcript"],
                height=600,
                label_visibility="collapsed"
            )
            
            if edited_transcript != st.session_state["transcript"]:
                st.session_state["transcript"] = edited_transcript
                
        # --- TAB: MINUTES ---
        with tab_mins:
            st.subheader("Formal Minutes Generation")
            
            if st.button("✨ Generate Minutes", type="primary"):
                with st.spinner("Extracting structured data..."):
                    try:
                        prompt = PromptTemplates.MINUTES_GENERATION_V2.format(
                            transcript=st.session_state["transcript"][:config.MAX_TRANSCRIPT_LENGTH]
                        )
                        response = model.generate_content(prompt)
                        json_text = clean_json_response(get_gemini_text_safe(response))
                        
                        try:
                            structured_data = json.loads(json_text)
                            minutes_text = generate_capital_estates_minutes(structured_data)
                            st.session_state["minutes_text"] = minutes_text
                        except json.JSONDecodeError:
                            st.error("Failed to parse AI response into JSON. Showing raw text.")
                            st.session_state["minutes_text"] = json_text
                            
                    except Exception as e:
                        st.error(f"Generation failed: {e}")

            if st.session_state.get("minutes_text"):
                st.text_area("Preview:", st.session_state["minutes_text"], height=500)
                
                docx_file = create_professional_docx(st.session_state["minutes_text"], "minutes")
                st.download_button(
                    label="📥 Download Professional DOCX",
                    data=docx_file,
                    file_name="Minutes.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary"
                )

        # --- TAB: BRIEFING ---
        with tab_brief:
            st.subheader("Executive Briefing")
            if st.button("📊 Generate Briefing"):
                with st.spinner("Summarizing..."):
                    prompt = PromptTemplates.BRIEFING_V1.format(
                        transcript=st.session_state["transcript"][:config.MAX_TRANSCRIPT_LENGTH]
                    )
                    response = model.generate_content(prompt)
                    st.session_state["briefing"] = get_gemini_text_safe(response)

            if st.session_state.get("briefing"):
                st.markdown(st.session_state["briefing"])
                
                docx_file = create_professional_docx(st.session_state["briefing"], "briefing")
                st.download_button(
                    label="📥 Download Briefing DOCX",
                    data=docx_file,
                    file_name="Briefing.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )

        # --- TAB: CHAT ---
        with tab_chat:
            st.subheader("Chat with your Meeting")
            
            for msg in st.session_state["messages"]:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
            
            if prompt := st.chat_input("Ask about budget, decisions, or attendees..."):
                st.session_state["messages"].append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.write(prompt)
                
                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        full_prompt = PromptTemplates.CHAT_V1.format(
                            transcript=st.session_state["transcript"][:config.MAX_TRANSCRIPT_LENGTH],
                            question=prompt
                        )
                        response = model.generate_content(full_prompt)
                        reply = get_gemini_text_safe(response)
                        st.write(reply)
                        st.session_state["messages"].append({"role": "assistant", "content": reply})

if __name__ == "__main__":
    main()

