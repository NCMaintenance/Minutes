import streamlit as st
import google.generativeai as genai
import json
import os
import time
from datetime import datetime
from docx import Document
import io
import tempfile
import re
import base64
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, PermissionDenied

# --- Configuration ---
GEMINI_MODEL_NAME = 'gemini-3-flash-preview'
# TTS Model for Podcast Audio
TTS_MODEL_NAME = 'gemini-2.5-flash-preview-tts' 
LOGO_URL = "https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png"

# --- API Key Management ---
def get_available_keys():
    """Retrieves all defined API keys from secrets."""
    keys = []
    # Check for primary and backup keys
    key_names = ["GEMINI_API_KEY", "GEMINI_API_KEY2", "GEMINI_API_KEY3"]
    for name in key_names:
        if name in st.secrets:
            keys.append(st.secrets[name])
    
    if not keys:
        st.error("No API Keys found in secrets. Please add GEMINI_API_KEY.")
        st.stop()
    return keys

# Initialize Session State for Key Index if not present
if "key_index" not in st.session_state:
    st.session_state.key_index = 0

def configure_genai_with_current_key():
    """Configures GenAI with the current active key."""
    keys = get_available_keys()
    # Ensure index is within bounds
    if st.session_state.key_index >= len(keys):
        st.session_state.key_index = 0
    
    current_key = keys[st.session_state.key_index]
    genai.configure(api_key=current_key)
    return genai.GenerativeModel(model_name=GEMINI_MODEL_NAME)

# --- Robust Audio Processor (Transcribe) ---
def process_audio_with_rotation(tmp_file_path, context_info):
    """
    Handles the entire flow: Upload -> Wait -> Generate -> Delete.
    If ANY step fails (Quota or Permission), it rotates keys and RE-UPLOADS the file.
    """
    max_retries = 6 
    base_delay = 1
    keys = get_available_keys()
    
    context_str = f"Context: {context_info}" if context_info else ""
    prompt = f"""
    You are a professional transcriber for HSE Capital & Estates.
    {context_str}
    Task: Transcribe the audio using strict Irish/UK English spelling (e.g. 'Programme', 'Paediatric', 'Centre').
    Format: Use '**Speaker Name**:' followed by text.
    Currency: Euro (€).
    Speaker IDs: If unknown, use 'Speaker 1', 'Speaker 2'.
    """

    for attempt in range(max_retries):
        audio_file = None
        try:
            # 1. Configure Key (Rotates if needed)
            model = configure_genai_with_current_key()
            current_key_num = st.session_state.key_index + 1
            
            # 2. Upload with CURRENT Key
            if attempt > 0:
                st.toast(f"Retrying with Key {current_key_num}...", icon="🔄")
            
            # Use the library-level upload_file which uses the active `configure` key
            audio_file = genai.upload_file(path=tmp_file_path, display_name="HSE_Audio")
            
            # Wait for processing
            while audio_file.state.name == "PROCESSING":
                time.sleep(2)
                audio_file = genai.get_file(audio_file.name)
            
            if audio_file.state.name == "FAILED":
                raise Exception("Audio processing failed by Google.")

            # 3. Generate
            response = model.generate_content(
                [prompt, audio_file],
                request_options={"timeout": 1200}
            )
            
            # 4. Success! Cleanup and Return
            try:
                genai.delete_file(audio_file.name)
            except: pass
            
            return response.text

        except (ResourceExhausted, ServiceUnavailable, PermissionDenied, Exception) as e:
            # Cleanup failed file
            if audio_file:
                try:
                    genai.delete_file(audio_file.name)
                except: pass

            # Check if it's a retry-able error
            error_str = str(e)
            is_quota = "429" in error_str or "ResourceExhausted" in error_str
            is_perm = "403" in error_str or "PermissionDenied" in error_str
            
            # If it's a quota error OR a permission error (file owner mismatch), ROTATE.
            if is_quota or is_perm or attempt < max_retries:
                old_index = st.session_state.key_index
                st.session_state.key_index = (st.session_state.key_index + 1) % len(keys)
                wait_time = base_delay * (1.5 ** attempt)
                st.toast(f"Key {old_index+1} failed. Switching to Key {st.session_state.key_index+1}...", icon="⚠️")
                time.sleep(wait_time)
            else:
                raise e # Fatal error
                
    raise Exception("All API keys are currently overloaded. Please try again later.")

# --- Robust Text Generator (Minutes/Chat/Brief) ---
def robust_text_gen(prompt):
    max_retries = 6
    keys = get_available_keys()
    
    for attempt in range(max_retries):
        try:
            model = configure_genai_with_current_key()
            return model.generate_content(prompt, request_options={"timeout": 600})
        except (ResourceExhausted, ServiceUnavailable):
             # Rotate
            old_index = st.session_state.key_index
            st.session_state.key_index = (st.session_state.key_index + 1) % len(keys)
            st.toast(f"Key {old_index+1} busy. Switching...", icon="🔄")
            time.sleep(1)
        except Exception as e:
            raise e
    raise Exception("All keys busy.")

# --- Audio Generator (For Podcast - Fixed for compatibility) ---
def generate_podcast_audio(script_text):
    """
    Sends the script to Gemini TTS model using raw dictionary config
    to bypass version mismatches in the library.
    """
    # Configure with current key
    configure_genai_with_current_key()
    
    try:
        model = genai.GenerativeModel(model_name=TTS_MODEL_NAME)
        
        prompt = f"""
        Read the following podcast script naturally and engagingly.
        
        SCRIPT:
        {script_text}
        """
        
        # FIX: Sending raw dictionary instead of using genai.types.SpeechConfig
        # This prevents the 'no attribute SpeechConfig' error on older libs.
        response = model.generate_content(
            prompt,
            generation_config={
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": "Aoede"
                        }
                    }
                }
            }
        )
        
        # Extract audio blob
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    return part.inline_data.data # Returns base64/bytes
        return None

    except Exception as e:
        st.warning(f"Audio generation unavailable with current key/region: {e}")
        return None

# --- HSE Capital & Estates Minutes Generator ---
def generate_hse_minutes(structured):
    now = datetime.now()
    
    def get(val, default="Not stated"):
        return val if val and str(val).strip().lower() != "not mentioned" else default

    def bullets(val):
        if isinstance(val, list) and val:
            items = [item for item in val if str(item).strip() and str(item).strip().lower() != "not mentioned"]
            if items:
                return "".join([f"• {item}\n" for item in items])
        elif isinstance(val, str) and val.strip() and val.strip().lower() != "not mentioned":
            return f"• {val}\n"
        return "• None recorded\n"

    # Extract Data
    meeting_title = get(structured.get("meetingTitle"), "Capital & Estates Meeting")
    meeting_date = get(structured.get("meetingDate"), now.strftime("%d/%m/%Y"))
    start_time = get(structured.get("startTime"), "00:00")
    end_time = get(structured.get("endTime"), "00:00")
    location = get(structured.get("location"))
    chairperson = get(structured.get("chairperson"))
    minute_taker = get(structured.get("minuteTaker"))
    
    # Lists
    attendees = bullets(structured.get("attendees", []))
    apologies = bullets(structured.get("apologies", []))
    matters_arising = bullets(structured.get("mattersArising", []))
    declarations = get(structured.get("declarationsOfInterest"), "None declared.")
    
    # HSE Specific Topics
    major_projects = bullets(structured.get("majorProjects", []))
    minor_projects = bullets(structured.get("minorProjects", []))
    estates_strategy = bullets(structured.get("estatesStrategy", []))
    health_safety = bullets(structured.get("healthSafety", []))
    risk_register = bullets(structured.get("riskRegister", []))
    finance = bullets(structured.get("financeUpdate", []))
    aob = bullets(structured.get("aob", []))
    next_meeting = get(structured.get("nextMeetingDate"))

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
{attendees}
Apologies:
{apologies}
________________________________________
2. Minutes of Previous Meeting / Matters Arising
{matters_arising}
________________________________________
3. Declarations of Interest
• {declarations}
________________________________________
4. Capital Projects Update
4.1 Major Projects (Capital)
{major_projects}
4.2 Minor Works / Equipment / ICT
{minor_projects}
________________________________________
5. Estates Strategy and Planning
{estates_strategy}
________________________________________
6. Health & Safety / Regulatory Compliance
{health_safety}
________________________________________
7. Risk Register
{risk_register}
________________________________________
8. Finance Update
{finance}
________________________________________
9. AOB (Any Other Business)
{aob}
________________________________________
10. Date of Next Meeting
• {next_meeting}
________________________________________
Minutes Approved By: ____________________ Date: ___________
"""
    return template

# --- DOCX Export Functions ---
def create_docx(content, kind="minutes"):
    doc = Document()
    if kind == "minutes":
        doc.add_heading("HSE Capital & Estates Meeting Minutes", level=1)
        for line in content.splitlines():
            if line.strip().endswith(":") and not line.startswith("•"):
                try: doc.add_heading(line.strip(), level=2)
                except: doc.add_paragraph(line)
            elif line.strip() == "________________________________________":
                doc.add_paragraph("-" * 50)
            elif line.strip():
                doc.add_paragraph(line)
    else:
        doc.add_heading("Meeting Document", level=1)
        doc.add_paragraph(content)
        
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

# --- Setup & Config ---
st.set_page_config(page_title="HSE MAI Recap", layout="wide", page_icon="🏥")

# Custom CSS for HSE Green Theme
st.markdown("""
<style>
    h1, h2, h3, h4 { color: #00563B !important; }
    .stButton > button { background-color: #00563B !important; color: white !important; }
    div[data-testid="stSidebar"] { background-color: #f8f9fa; }
    .stInfo { background-color: #e8f5e9; color: #00563B; }
</style>
""", unsafe_allow_html=True)

# Initial Config
try:
    if "GEMINI_API_KEY" in st.secrets:
        configure_genai_with_current_key()
    else:
        st.error("GEMINI_API_KEY missing from secrets.")
        st.stop()
except Exception as e:
    st.error(f"Config Error: {e}")
    st.stop()

# --- Password Protection ---
if "password_verified" not in st.session_state:
    st.session_state.password_verified = False

if not st.session_state.password_verified:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.image(LOGO_URL, width=150)
        st.markdown("### HSE Secure Login")
        with st.form("password_form"):
            user_password = st.text_input("Enter Access Code:", type="password")
            if st.form_submit_button("Login"):
                if st.secrets.get("password") and user_password == st.secrets["password"]:
                    st.session_state.password_verified = True
                    st.rerun()
                elif not st.secrets.get("password"):
                     st.warning("Password not set in secrets.")
                else:
                    st.error("Invalid code.")
    st.stop()

# --- App State Init ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Sidebar ---
with st.sidebar:
    # UPDATED: Replaced deprecated use_container_width=True with width="stretch" per user instruction
    st.image(LOGO_URL, width="stretch")
    st.title("MAI Recap Pro")
    st.caption("Capital & Estates Assistant")
    
    if st.button("🔄 New Meeting / Reset"):
        for key in list(st.session_state.keys()):
            # Keep password and key index
            if key not in ['password_verified', 'key_index']:
                del st.session_state[key]
        st.rerun()
        
    st.markdown("---")
    if st.button("Created by Dave Maher"):
        st.info("This application's intellectual property belongs to Dave Maher.")

    st.markdown("---")
    st.markdown("**Version:** 4.1 (Compat Fix)")
    st.info("System optimized for UK/Irish English.")

# --- Main UI Header ---
col1, col2 = st.columns([1, 6])
with col1:
    st.image(LOGO_URL, width=120)
with col2:
    st.title("HSE Meeting Minutes Generator")
    st.markdown("#### Automated Documentation System")

st.markdown("### 📤 Input Source")

# --- Input Selection ---
mode = st.radio(
    "Choose input method:",
    ["Record Microphone", "Upload Audio File"],
    horizontal=True
)

audio_bytes = None

if mode == "Upload Audio File":
    uploaded_audio = st.file_uploader(
        "Upload Audio (WAV, MP3, M4A)",
        type=["wav", "mp3", "m4a", "ogg"]
    )
    if uploaded_audio:
        st.audio(uploaded_audio)
        audio_bytes = uploaded_audio

elif mode == "Record Microphone":
    recorded_audio = st.audio_input("🎙️ Record Meeting")
    if recorded_audio:
        st.audio(recorded_audio)
        audio_bytes = recorded_audio

# --- Context Box ---
with st.expander("ℹ️ Add Context (Optional but Recommended)"):
    context_info = st.text_area(
        "Attendees / Topics:",
        placeholder="e.g. Chair: Sarah O'Brien. Topics: Mallow General Extension, Budget Review.",
        help="Helps the AI identify names and acronyms."
    )

# --- Transcription ---
if audio_bytes and st.button("🧠 Transcribe Audio"):
    with st.spinner("Processing audio with HSE Security Protocols..."):
        if hasattr(audio_bytes, "read"):
            audio_data_bytes = audio_bytes.read()
        else:
            data = audio_bytes
        
        # Temp file handling
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            tmp_file.write(audio_data_bytes)
            tmp_file_path = tmp_file.name
        
        try:
            # CALL THE ROBUST AUDIO PROCESSOR
            transcript_text = process_audio_with_rotation(tmp_file_path, context_info)
            
            st.session_state["transcript"] = transcript_text
            st.success("Transcript generated successfully.")
            st.info("Temporary audio files cleaned from server.")

        except Exception as e:
            st.error(f"Error: {e}")
            
        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

# --- Output Section ---
if "transcript" in st.session_state:
    st.markdown("---")
    
    # Updated Tabs
    t1, t2, t3, t4, t5 = st.tabs(["📄 Transcript", "🏥 Minutes", "📝 Briefing", "🎙️ Podcast Studio", "💬 Chat"])

    # --- TAB 1: TRANSCRIPT ---
    with t1:
        st.text_area("Full Transcript:", st.session_state["transcript"], height=500)

    # --- TAB 2: MINUTES ---
    with t2:
        if st.button("Generate Official Minutes"):
            with st.spinner("Extracting HSE Data Points..."):
                try:
                    prompt_structured = f"""
                    You are an expert secretary for HSE Capital & Estates.
                    Extract structured data from this transcript using UK/Irish English.
                    Return ONLY valid JSON.
                    TRANSCRIPT: {st.session_state['transcript']}
                    
                    Keys to extract: meetingTitle, meetingDate, startTime, endTime, location, chairperson, minuteTaker, attendees, apologies, mattersArising, declarationsOfInterest, majorProjects, minorProjects, estatesStrategy, healthSafety, riskRegister, financeUpdate, aob, nextMeetingDate.
                    """
                    
                    # EXECUTE WITH ROTATION
                    response = robust_text_gen(prompt_structured)
                    
                    # Parse JSON
                    json_match = re.search(r"```json\s*([\s\S]*?)\s*```|({[\s\S]*})", response.text, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1) or json_match.group(2)
                        structured = json.loads(json_str.strip())
                        st.session_state["minutes"] = generate_hse_minutes(structured)
                        st.success("Minutes Generated.")
                    else:
                        st.error("Could not parse AI response.")
                except Exception as e:
                    st.error(f"Error: {e}")

        if "minutes" in st.session_state:
            st.text_area("Draft Minutes:", st.session_state["minutes"], height=600)
            st.download_button("Download DOCX", create_docx(st.session_state["minutes"], "minutes"), "HSE_Minutes.docx")

    # --- TAB 3: BRIEFING ---
    with t3:
        st.info("Generate a high-level summary for executive review.")
        if st.button("Generate Briefing Note"):
            with st.spinner("Analyzing..."):
                p_brief = f"""
                Create a high-level "Executive Briefing Note" for HSE management based on this transcript.
                Use UK/Irish English.
                Sections: 
                1. Executive Summary
                2. Key Strategic Decisions
                3. Critical Risks / Issues
                4. Action Items Table
                TRANSCRIPT: {st.session_state['transcript']}
                """
                res = robust_text_gen(p_brief)
                st.session_state["briefing"] = res.text
        
        if "briefing" in st.session_state:
            st.markdown(st.session_state["briefing"])
            st.download_button("Download Briefing", create_docx(st.session_state["briefing"], "briefing"), "HSE_Briefing.docx")

    # --- TAB 4: PODCAST ---
    with t4:
        st.markdown("### 🎙️ HSE Podcast Studio")
        st.info("Step 1: Generate the script. Step 2: Generate the audio.")
        
        if st.button("Step 1: Create Script"):
            with st.spinner("Writing script..."):
                p_pod = f"""
                Convert this meeting transcript into a lively, engaging 3-minute podcast script for HSE staff.
                Format: Pure dialogue only. No stage directions like [Music] or [Laughs].
                Speakers: Sarah (Host) and Mike (Expert).
                Topic: Key outcomes of the Capital & Estates meeting.
                Tone: Professional but conversational Irish/UK English.
                TRANSCRIPT: {st.session_state['transcript']}
                """
                res = robust_text_gen(p_pod)
                st.session_state["podcast"] = res.text
        
        if "podcast" in st.session_state:
            st.text_area("Script Preview:", st.session_state["podcast"], height=300)
            st.download_button("Download Script", create_docx(st.session_state["podcast"], "other"), "Podcast_Script.docx")
            
            st.markdown("---")
            if st.button("🎧 Step 2: Generate Audio"):
                with st.spinner("Synthesizing voice (this may take 20-30 seconds)..."):
                    audio_data = generate_podcast_audio(st.session_state["podcast"])
                    if audio_data:
                        st.session_state["podcast_audio"] = audio_data
                        st.success("Audio Generated!")
                    else:
                        st.error("Audio generation failed. Please try again.")

        if "podcast_audio" in st.session_state:
            # Play Audio
            st.audio(st.session_state["podcast_audio"], format="audio/wav")

    # --- TAB 5: CHAT ---
    with t5:
        st.info("Ask questions about the meeting details.")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("E.g. What was the budget for Mallow?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                p_chat = f"""
                Answer strictly based on the transcript below.
                Use UK/Irish English. Currency: Euro (€).
                TRANSCRIPT: {st.session_state['transcript']}
                QUESTION: {prompt}
                """
                with st.spinner("Thinking..."):
                    res = robust_text_gen(p_chat)
                    st.markdown(res.text)
                    st.session_state.messages.append({"role": "assistant", "content": res.text})

# --- Footer ---
st.markdown("---")
st.caption("HSE Capital & Estates | Internal Use Only")


