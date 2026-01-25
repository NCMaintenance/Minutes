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
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# --- Configuration ---
GEMINI_MODEL_NAME = 'gemini-3-flash-preview'
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

# --- Robust API Wrapper with Key Rotation ---
def robust_api_call(task_description, api_func, *args, **kwargs):
    """
    Executes a Gemini API call with Key Rotation and Exponential Backoff.
    If Key 1 fails, it switches to Key 2, etc.
    """
    max_retries = 6 # Enough to cycle through 3 keys twice
    base_delay = 1
    
    keys = get_available_keys()
    
    for attempt in range(max_retries):
        try:
            # Always ensure we are using the current configured model
            model = configure_genai_with_current_key()
            
            # If the function passed is a method (like model.generate_content), 
            # we need to re-bind it to the NEW model instance because the old one 
            # is tied to the old API key.
            if hasattr(api_func, '__self__') and isinstance(api_func.__self__, genai.GenerativeModel):
                # Re-bind the method to the new model instance
                method_name = api_func.__name__
                actual_func = getattr(model, method_name)
            else:
                actual_func = api_func

            return actual_func(*args, **kwargs)
            
        except (ResourceExhausted, ServiceUnavailable):
            # ROTATION LOGIC
            old_index = st.session_state.key_index
            st.session_state.key_index = (st.session_state.key_index + 1) % len(keys)
            
            wait_time = base_delay * (1.5 ** attempt) # Slightly faster retry since we are switching keys
            
            st.toast(
                f"Quota limit on Key {old_index+1}. Switching to Key {st.session_state.key_index+1}...", 
                icon="🔄"
            )
            time.sleep(wait_time)
            
        except Exception as e:
            # Valid errors (like file too large) should fail immediately
            raise e
            
    raise Exception("All API keys are currently overloaded. Please try again later.")

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
def create_minutes_docx(content):
    doc = Document()
    doc.add_heading("HSE Capital & Estates Meeting Minutes", level=1)
    for line in content.splitlines():
        if line.strip().endswith(":") and not line.startswith("•"):
            try:
                doc.add_heading(line.strip(), level=2)
            except:
                doc.add_paragraph(line)
        elif line.strip() == "________________________________________":
            doc.add_paragraph("-" * 50)
        elif line.strip():
            doc.add_paragraph(line)
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
        # Initial config with whatever key is currently active
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

# --- Sidebar ---
with st.sidebar:
    st.image(LOGO_URL, use_container_width=True)
    st.title("MAI Recap Pro")
    st.caption("Capital & Estates Assistant")
    
    if st.button("🔄 New Meeting / Reset"):
        for key in list(st.session_state.keys()):
            # Keep password and key index
            if key not in ['password_verified', 'key_index']:
                del st.session_state[key]
        st.rerun()

    st.markdown("---")
    st.markdown("**Version:** 3.6 (Multi-Key)")
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
            # 1. Upload to Gemini (with Display Name)
            st.info("Uploading audio to secure server...")
            
            # Since upload_file is not a method of a model but the library, we wrap it too
            # but usually upload limit is different from generate limit.
            # However, to be safe, we configure the key before upload.
            configure_genai_with_current_key()
            audio_file = genai.upload_file(path=tmp_file_path, display_name="HSE_Meeting_Audio")
            
            st.success(f"Audio uploaded successfully: {audio_file.name}")
            
            # 2. Wait for processing
            while audio_file.state.name == "PROCESSING":
                time.sleep(2)
                audio_file = genai.get_file(audio_file.name)
                
            if audio_file.state.name == "FAILED":
                st.error("Audio processing failed on server.")
                st.stop()

            # 3. Prompt
            context_str = f"Context: {context_info}" if context_info else ""
            prompt = f"""
            You are a professional transcriber for HSE Capital & Estates.
            {context_str}
            Task: Transcribe the audio using strict Irish/UK English spelling (e.g. 'Programme', 'Paediatric', 'Centre').
            Format: Use '**Speaker Name**:' followed by text.
            Currency: Euro (€).
            Speaker IDs: If unknown, use 'Speaker 1', 'Speaker 2'.
            """
            
            # 4. Generate with Key Rotation & Timeout
            # We pass a fresh model getter to the retry wrapper
            model = configure_genai_with_current_key()
            
            response = robust_api_call(
                "Transcription",
                model.generate_content, 
                [prompt, audio_file], 
                request_options={"timeout": 1200}
            )
            
            st.session_state["transcript"] = response.text
            st.success("Transcript generated successfully.")

        except Exception as e:
            st.error(f"Error: {e}")
            
        finally:
            # 5. Cleanup
            if 'audio_file' in locals() and audio_file:
                try:
                    # Configure with current key to ensure we have permission to delete
                    configure_genai_with_current_key()
                    genai.delete_file(audio_file.name)
                    st.info(f"Cleaned up uploaded file: {audio_file.name}")
                except Exception as del_e:
                    pass 
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

# --- Output Section ---
if "transcript" in st.session_state:
    st.markdown("---")
    st.markdown("## 📄 Transcript")
    st.text_area("Full Transcript:", st.session_state["transcript"], height=300)

    if st.button("📊 Generate Official Minutes"):
        with st.spinner("Extracting HSE Data Points..."):
            try:
                current_transcript = st.session_state['transcript']
                prompt_structured = f"""
                You are an expert secretary for HSE Capital & Estates.
                Extract detailed structured data from this transcript using UK/Irish English.
                Dates: DD/MM/YYYY. Currency: Euro (€).
                
                Keys to extract (Return empty list [] if not found):
                - meetingTitle, meetingDate, startTime, endTime, location
                - chairperson, minuteTaker
                - attendees (list), apologies (list)
                - mattersArising (list)
                - declarationsOfInterest (string)
                - majorProjects (list - Projects > €Xm)
                - minorProjects (list - Minor Works/ICT)
                - estatesStrategy (list)
                - healthSafety (list)
                - riskRegister (list)
                - financeUpdate (list)
                - aob (list)
                - nextMeetingDate

                TRANSCRIPT:
                {current_transcript}

                Return ONLY valid JSON.
                """
                
                # We need to get the model again to ensure it uses the active key
                model = configure_genai_with_current_key()
                
                # EXECUTE WITH ROTATION & TIMEOUT
                response = robust_api_call(
                    "Minutes Generation",
                    model.generate_content,
                    prompt_structured,
                    request_options={"timeout": 600}
                )
                
                # Parse JSON
                json_match = re.search(r"```json\s*([\s\S]*?)\s*```|({[\s\S]*})", response.text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1) or json_match.group(2)
                    structured = json.loads(json_str.strip())
                    st.session_state["minutes"] = generate_hse_minutes(structured)
                    st.success("Minutes Generated Successfully.")
                else:
                    st.error("Could not parse AI response.")
            
            except Exception as e:
                st.error(f"Generation Error: {e}")

# --- Final Display ---
if "minutes" in st.session_state:
    st.markdown("---")
    st.markdown("## 🏥 Draft Minutes")
    st.text_area(
        "Editable Draft:",
        st.session_state["minutes"],
        height=800
    )
    st.download_button(
        label="📥 Download Minutes (DOCX)",
        data=create_minutes_docx(st.session_state["minutes"]),
        file_name=f"HSE_Minutes_{datetime.now().strftime('%Y%m%d')}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

# --- Footer ---
st.markdown("---")
st.caption("HSE Capital & Estates | Internal Use Only")

