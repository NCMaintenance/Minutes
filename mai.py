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
import struct
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, PermissionDenied

# --- Configuration ---
GEMINI_MODEL_NAME = 'gemini-3-flash-preview'
TTS_MODEL_NAME = 'gemini-2.5-flash-preview-tts'
LOGO_URL = "https://www.esther.ie/wp-content/uploads/2022/05/HSE-Logo-Green-NEW-no-background.png"
FAVICON_URL = "https://assets.hse.ie/static/hse-frontend/assets/favicons/favicon.ico"

# --- API Key Management ---
def get_available_keys():
    keys = []
    key_names = ["GEMINI_API_KEY", "GEMINI_API_KEY2", "GEMINI_API_KEY3"]
    for name in key_names:
        if name in st.secrets:
            keys.append(st.secrets[name])
    if not keys:
        st.error("No API Keys found in secrets. Please add GEMINI_API_KEY.")
        st.stop()
    return keys

if "key_index" not in st.session_state:
    st.session_state.key_index = 0

def configure_genai_with_current_key():
    keys = get_available_keys()
    if st.session_state.key_index >= len(keys):
        st.session_state.key_index = 0
    genai.configure(api_key=keys[st.session_state.key_index])
    return genai.GenerativeModel(model_name=GEMINI_MODEL_NAME)

# --- Helper: Safe Response Extractor ---
def safe_get_text(response):
    try:
        if not response.candidates: return None
        candidate = response.candidates[0]
        if candidate.content.parts: return candidate.content.parts[0].text
        return None
    except Exception: return None

# --- Helper: Detect Speakers ---
def detect_speakers(text):
    """Finds speaker labels like '**Speaker 1**:' or 'Speaker 1:'"""
    if not text: return []
    # Regex for bolded or plain speaker labels at start of lines
    pattern = r'(?m)^(?:[\*\_]{2})?([A-Za-z0-9\s\(\)\-\.]+?)(?:[\*\_]{2})?[:]'
    matches = re.findall(pattern, text)
    return sorted(list(set(matches)))

# --- Helper: Add WAV Header ---
def add_wav_header(pcm_data, sample_rate=24000, channels=1, bit_depth=16):
    header = b'RIFF'
    header += struct.pack('<I', 36 + len(pcm_data))
    header += b'WAVEfmt '
    header += struct.pack('<I', 16)
    header += struct.pack('<H', 1)
    header += struct.pack('<H', channels)
    header += struct.pack('<I', sample_rate)
    header += struct.pack('<I', sample_rate * channels * (bit_depth // 8))
    header += struct.pack('<H', channels * (bit_depth // 8))
    header += struct.pack('<H', bit_depth)
    header += b'data'
    header += struct.pack('<I', len(pcm_data))
    return header + pcm_data

# --- Robust Audio Processor ---
def process_audio_with_rotation(tmp_file_path, context_info):
    max_retries = 6 
    base_delay = 1
    keys = get_available_keys()
    
    context_str = f"Context: {context_info}" if context_info else ""
    prompt = f"""
    You are a precise transcription engine for the Health Service Executive (HSE) Ireland.
    {context_str}
    Task: Output the raw transcription of this audio. 
    Constraint: Do NOT include preamble like "Here is the transcript". Do NOT include markdown blocks. Just the dialogue.
    Language: Strict Irish English spelling (e.g. 'Programme', 'Paediatric', 'Centre', 'Realise', 'Colour').
    Format:
    **Speaker Name**: Text...
    **Speaker Name**: Text...
    """

    for attempt in range(max_retries):
        audio_file = None
        try:
            model = configure_genai_with_current_key()
            if attempt > 0: st.toast(f"Retry {attempt}...", icon="🔄")
            audio_file = genai.upload_file(path=tmp_file_path, display_name="HSE_Audio")
            
            while audio_file.state.name == "PROCESSING":
                time.sleep(2)
                audio_file = genai.get_file(audio_file.name)
            
            if audio_file.state.name == "FAILED": raise Exception("Audio processing failed.")

            response = model.generate_content([prompt, audio_file], request_options={"timeout": 1200})
            text = safe_get_text(response)
            
            try: genai.delete_file(audio_file.name)
            except: pass
            
            if text: return text
            else: raise Exception("Empty response from AI")

        except Exception as e:
            if audio_file:
                try: genai.delete_file(audio_file.name)
                except: pass
            
            st.session_state.key_index = (st.session_state.key_index + 1) % len(keys)
            time.sleep(base_delay * (1.5 ** attempt))
            
    raise Exception("System busy. Please try again.")

# --- Robust Text Generator ---
def robust_text_gen(prompt):
    max_retries = 6
    keys = get_available_keys()
    
    for attempt in range(max_retries):
        try:
            model = configure_genai_with_current_key()
            response = model.generate_content(prompt, request_options={"timeout": 600})
            text = safe_get_text(response)
            if text: return text
        except Exception:
            pass
        
        st.session_state.key_index = (st.session_state.key_index + 1) % len(keys)
        time.sleep(1)
        
    raise Exception("Unable to generate text.")

# --- Audio Generator (Podcast) ---
def generate_podcast_audio(script_text):
    configure_genai_with_current_key()
    try:
        model = genai.GenerativeModel(model_name=TTS_MODEL_NAME)
        prompt = f"Read this naturally:\n{script_text}"
        response = model.generate_content(
            prompt,
            generation_config={
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {"prebuilt_voice_config": {"voice_name": "Aoede"}}
                }
            }
        )
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    return part.inline_data.data, part.inline_data.mime_type
        return None, None
    except Exception as e:
        st.warning(f"Audio Unavailable: {e}")
        return None, None

# --- Minutes Structure ---
def generate_hse_minutes(structured):
    now = datetime.now()
    def get(val, default="Not stated"): return val if val and str(val).strip().lower() != "not mentioned" else default
    def bullets(val):
        if isinstance(val, list) and val:
            items = [item for item in val if str(item).strip() and str(item).strip().lower() != "not mentioned"]
            if items: return "".join([f"• {item}\n" for item in items])
        return "• None recorded\n"

    template = f"""HSE Capital & Estates Meeting Minutes
Meeting Title: {get(structured.get("meetingTitle"), "Meeting")}
Date: {get(structured.get("meetingDate"), now.strftime("%d/%m/%Y"))}
Time: {get(structured.get("startTime"), "00:00")} - {get(structured.get("endTime"), "00:00")}
Location: {get(structured.get("location"))}
Chairperson: {get(structured.get("chairperson"))}
Minute Taker: {get(structured.get("minuteTaker"))}
________________________________________
1. Attendance
Present:
{bullets(structured.get("attendees", []))}
Apologies:
{bullets(structured.get("apologies", []))}
________________________________________
2. Minutes of Previous Meeting / Matters Arising
{bullets(structured.get("mattersArising", []))}
________________________________________
3. Declarations of Interest
• {get(structured.get("declarationsOfInterest"), "None declared.")}
________________________________________
4. Capital Projects Update
4.1 Major Projects (Capital)
{bullets(structured.get("majorProjects", []))}
4.2 Minor Works / Equipment / ICT
{bullets(structured.get("minorProjects", []))}
________________________________________
5. Estates Strategy and Planning
{bullets(structured.get("estatesStrategy", []))}
________________________________________
6. Health & Safety / Regulatory Compliance
{bullets(structured.get("healthSafety", []))}
________________________________________
7. Risk Register
{bullets(structured.get("riskRegister", []))}
________________________________________
8. Finance Update
{bullets(structured.get("financeUpdate", []))}
________________________________________
9. AOB
{bullets(structured.get("aob", []))}
________________________________________
10. Next Meeting
• {get(structured.get("nextMeetingDate"))}
________________________________________
Minutes Approved By: ____________________ Date: ___________
"""
    return template

def create_docx(content, kind="minutes"):
    doc = Document()
    doc.add_heading("Meeting Document", level=1)
    doc.add_paragraph(content)
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

# --- Setup ---
st.set_page_config(page_title="HSE MAI Recap", layout="wide", page_icon=FAVICON_URL)
st.markdown("""
<style>
    h1, h2, h3, h4 { color: #00563B !important; }
    .stButton > button { background-color: #00563B !important; color: white !important; }
    div[data-testid="stSidebar"] { background-color: #f8f9fa; }
    .stInfo { background-color: #e8f5e9; color: #00563B; }
</style>
""", unsafe_allow_html=True)

try:
    if "GEMINI_API_KEY" in st.secrets:
        configure_genai_with_current_key()
    else:
        st.error("Secrets missing.")
        st.stop()
except:
    pass

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
                     st.warning("Password not set.")
                else:
                    st.error("Invalid code.")
    st.stop()

if "messages" not in st.session_state: st.session_state.messages = []
if "transcript" not in st.session_state: st.session_state.transcript = ""

# --- Sidebar ---
with st.sidebar:
    st.image(LOGO_URL, width="stretch")
    st.title("MAI Recap")
    
    # 1. Reset
    if st.button("🔄 New Meeting / Reset"):
        for key in list(st.session_state.keys()):
            if key not in ['password_verified', 'key_index']: del st.session_state[key]
        st.rerun()
    
    st.markdown("---")
    
    # 2. Context Input (Moved here)
    st.markdown("### ℹ️ Meeting Context")
    context_info = st.text_area("Details (Chair, Topics):", placeholder="e.g. Chair: Sarah. Topic: Budget.", height=80)
    
    # 3. Speaker Renaming (Visible only when transcript exists)
    if st.session_state.transcript:
        st.markdown("---")
        st.markdown("### 👥 Speaker ID Manager")
        detected = detect_speakers(st.session_state.transcript)
        if detected:
            with st.form("speaker_update_form"):
                replacements = {}
                for spk in detected:
                    new_name = st.text_input(f"Rename '{spk}':", placeholder=spk)
                    if new_name and new_name != spk:
                        replacements[spk] = new_name
                
                if st.form_submit_button("Update Transcript"):
                    txt = st.session_state.transcript
                    for old, new in replacements.items():
                        # Replace "**Speaker 1**:" and "Speaker 1:" patterns
                        txt = txt.replace(f"**{old}**", f"**{new}**")
                        txt = txt.replace(f"{old}:", f"{new}:")
                    st.session_state.transcript = txt
                    st.toast("Transcript updated with new names!", icon="✅")
                    st.rerun()
        else:
            st.caption("No speakers detected yet.")

    st.markdown("---")
    if st.button("Created by Dave Maher"):
        st.info("Property of Dave Maher.")
    st.markdown("**Version:** 5.2")

# --- Header ---
c1, c2 = st.columns([1, 6])
with c1: st.image(LOGO_URL, width=120)
with c2: 
    st.title("Meeting Minutes Generator")
    st.markdown("#### Automated Documentation System")

# --- Input ---
mode = st.radio("Input Source:", ["Record Microphone", "Upload Audio File"], horizontal=True)
audio_bytes = None
if mode == "Upload Audio File":
    audio_bytes = st.file_uploader("Upload (WAV, MP3, M4A)", type=["wav", "mp3", "m4a", "ogg"])
    if audio_bytes: st.audio(audio_bytes)
else:
    audio_bytes = st.audio_input("🎙️ Record")
    if audio_bytes: st.audio(audio_bytes)

if audio_bytes and st.button("🧠 Transcribe"):
    with st.spinner("Processing..."):
        if hasattr(audio_bytes, "read"): data = audio_bytes.read()
        else: data = audio_bytes
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        
        try:
            # Pass sidebar context info
            transcript_text = process_audio_with_rotation(tmp_path, context_info)
            st.session_state["transcript"] = transcript_text
            st.success("Transcription Complete.")
        except Exception as e:
            st.error(f"Error: {e}")
        finally:
            if os.path.exists(tmp_path): os.remove(tmp_path)

# --- Output Tabs ---
if st.session_state.transcript:
    st.markdown("---")
    t1, t2, t3, t4, t5 = st.tabs(["📄 Transcript", "🏥 Minutes", "📝 Briefing", "🎙️ Podcast", "💬 Chat"])

    # 1. Transcript
    with t1:
        st.text_area("Full Transcript:", st.session_state.transcript, height=500)

    # 2. Minutes
    with t2:
        if st.button("Generate Minutes", key="btn_min"):
            with st.spinner("Extracting..."):
                prompt = f"""
                Extract structured data from transcript (JSON). 
                Language: Strict Irish English (e.g. 'Paediatric', 'Programme'). Currency: Euro.
                Transcript: {st.session_state.transcript}
                Keys: meetingTitle, meetingDate, startTime, endTime, location, chairperson, minuteTaker, attendees, apologies, mattersArising, declarationsOfInterest, majorProjects, minorProjects, estatesStrategy, healthSafety, riskRegister, financeUpdate, aob, nextMeetingDate.
                """
                try:
                    res = robust_text_gen(prompt)
                    json_match = re.search(r"({[\s\S]*})", res, re.DOTALL)
                    if json_match:
                        structured = json.loads(json_match.group(1))
                        st.session_state.minutes = generate_hse_minutes(structured)
                except Exception as e: st.error(f"Error: {e}")
        
        if "minutes" in st.session_state:
            st.text_area("Draft:", st.session_state.minutes, height=600)
            st.download_button("Download DOCX", create_docx(st.session_state.minutes), "Minutes.docx")

    # 3. Briefing
    with t3:
        if st.button("Generate Briefing", key="btn_brief"):
            with st.spinner("Analyzing..."):
                prompt = f"""
                Write a neutral, matter-of-fact Executive Briefing based on this transcript.
                Language: Strict Irish English spelling (e.g. 'Realise', 'Centre', 'Colour').
                Do NOT use corporate fluff. Be candid and objective.
                Sections: Executive Summary, Key Decisions, Critical Risks, Action Items.
                Transcript: {st.session_state.transcript}
                """
                st.session_state.briefing = robust_text_gen(prompt)
        
        if "briefing" in st.session_state:
            st.markdown(st.session_state.briefing)
            st.download_button("Download Briefing", create_docx(st.session_state.briefing), "Briefing.docx")

    # 4. Podcast
    with t4:
        st.info("NotebookLM Style: Two neutral analysts discussing the meeting.")
        if st.button("Generate Script", key="btn_script"):
            with st.spinner("Writing script..."):
                prompt = f"""
                Convert this transcript into a podcast script between two hosts (Host and Expert).
                Language: Irish English spelling and phrasing.
                Tone: Candid, neutral, analytical (Like NotebookLM) but with Irish nuances. NOT corporate/PR.
                They should discuss the meeting outcomes naturally, pointing out interesting dynamics or risks.
                Transcript: {st.session_state.transcript}
                """
                st.session_state.podcast = robust_text_gen(prompt)
        
        if "podcast" in st.session_state:
            st.text_area("Script:", st.session_state.podcast, height=300)
            if st.button("Generate Audio", key="btn_audio"):
                with st.spinner("Synthesizing..."):
                    audio, mime = generate_podcast_audio(st.session_state.podcast)
                    if audio:
                        if "pcm" in mime.lower() or "raw" in mime.lower():
                             audio = add_wav_header(audio)
                             mime = "audio/wav"
                        st.session_state.pod_audio = audio
                        st.session_state.pod_mime = mime
                    else: st.error("Audio generation failed.")
        
        if "pod_audio" in st.session_state:
            st.audio(st.session_state.pod_audio, format=st.session_state.pod_mime)

    # 5. Chat
    with t5:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        
        if q := st.chat_input("Question?"):
            st.session_state.messages.append({"role": "user", "content": q})
            with st.chat_message("user"): st.markdown(q)
            with st.chat_message("assistant"):
                prompt = f"Answer neutrally using Irish English spelling/grammar. Transcript: {st.session_state.transcript}\nQ: {q}"
                ans = robust_text_gen(prompt)
                st.markdown(ans)
                st.session_state.messages.append({"role": "assistant", "content": ans})
# --- Footer ---
st.markdown("---")
st.markdown(
    "**Disclaimer:** This implementation has been tested using sample data. "
    "Adjustments may be required to ensure optimal performance and accuracy with real-world meeting audio. "
    "Always verify the accuracy of transcriptions and minutes."
)
st.markdown("Created by Dave Maher | For HSE internal use.")
