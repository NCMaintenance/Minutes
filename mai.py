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
    Returns a clean list of speaker names without markdown formatting.
    """
    if not text:
        return []
    
    # Regex to catch:
    # 1. Start of line
    # 2. Optional markdown bold (** or __)
    # 3. The Name (Group 1)
    # 4. Optional markdown bold closure
    # 5. A colon
    pattern = r'(?m)^(?:[\*\_]{2})?([A-Za-z0-9\s\(\)\-\.]+?)(?:[\*\_]{2})?[:]'
    
    matches = re.findall(pattern, text)
    
    # Filter and sort unique names
    unique_speakers = sorted(list(set(matches)))
    
    # Filter out very long matches or empty strings
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
st.set_page_config(page_title="MAI Recap Pro", layout="wide", page_icon="📝")

# --- Custom CSS ---
st.markdown("""
<style>
    .stChatInputContainer {padding-bottom: 20px;}
    .reportview-container {background: #f0f2f6;}
    h1 {color: #00563B !important;} /* HSE Green */
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 1.1rem; font-weight: 600;
    }
    div[data-testid="stStatusWidget"] div {
        font-size: 1.1em;
    }
</style>
""", unsafe_allow_html=True)

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
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown(
            """
            <div style="text-align: center;">
                <img src="https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png" width="100">
                <h2>MAI Recap Access</h2>
            </div>
            """, 
            unsafe_allow_html=True
        )
        st.info("Restricted Access: HSE Capital & Estates AI Tool")
        with st.form("password_form"):
            user_password = st.text_input("Enter Access Password:", type="password")
            if st.form_submit_button("Secure Login"):
                if st.secrets.get("password") and user_password == st.secrets["password"]:
                    st.session_state.password_verified = True
                    st.rerun()
                elif not st.secrets.get("password"):
                     st.warning("Password not configured in secrets.toml.")
                else:
                    st.error("Invalid credentials.")
    st.stop()

# --- Application State ---
if "transcript" not in st.session_state:
    st.session_state["transcript"] = ""
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Sidebar Controls ---
with st.sidebar:
    st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=180)
    st.markdown(f"**Engine:** `{GEMINI_MODEL_NAME}`")
    st.markdown("**Version:** 3.3 Pro")
    
    st.markdown("### 🛠️ Session Tools")
    if st.button("🗑️ New Meeting", type="primary"):
        for key in list(st.session_state.keys()):
            if key != 'password_verified':
                del st.session_state[key]
        st.rerun()
        
    st.markdown("---")
    
    # --- SPEAKER MAPPING LOGIC ---
    if st.session_state.get("transcript"):
        st.subheader("👥 Speaker Identity Manager")
        st.info("Map generic IDs to real names here.")
        
        # Detect current labels in the transcript
        detected_speakers = detect_speakers(st.session_state["transcript"])
        
        if not detected_speakers:
            st.caption("No speaker labels detected (e.g. 'Speaker 1:').")
        else:
            with st.form("speaker_map_form"):
                replacements = {}
                st.markdown("#### Rename detected speakers:")
                for spk in detected_speakers:
                    # Provide a text input for each detected speaker
                    new_name = st.text_input(f"Who is **{spk}**?", placeholder="e.g. Dr. O'Connor")
                    if new_name and new_name != spk:
                        replacements[spk] = new_name
                
                if st.form_submit_button("Update All Documents"):
                    # Perform replace
                    txt = st.session_state["transcript"]
                    count = 0
                    for old, new in replacements.items():
                        # Try plain replacement: "Speaker 1:" -> "Dr. Smith:"
                        if f"{old}:" in txt:
                            txt = txt.replace(f"{old}:", f"{new}:")
                            count += 1
                        
                        # Try markdown bold replacement: "**Speaker 1**:" -> "**Dr. Smith**:"
                        # This catches cases where Gemini formatted the output with bolding
                        elif f"**{old}**:" in txt:
                            txt = txt.replace(f"**{old}**:", f"**{new}**:")
                            count += 1
                            
                        # Try markdown bold replacement without colon match (rare but possible)
                        elif f"**{old}**" in txt:
                             txt = txt.replace(f"**{old}**", f"**{new}**")
                             count += 1

                    st.session_state["transcript"] = txt
                    if count > 0:
                        st.toast(f"Success! Updated speakers in transcript.", icon="✅")
                    else:
                        st.toast("No changes made. Check the exact spelling matches.", icon="⚠️")
                    st.rerun()

# --- Main Layout ---
col_logo, col_title = st.columns([1, 5])
with col_logo:
    st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=80)
with col_title:
    st.title("MAI Recap Pro")
    st.caption("HSE Minute-AI Generator & Meeting Assistant")

# --- Step 1: Input & Processing ---
if not st.session_state["transcript"]:
    st.markdown("### 1. Meeting Source")
    
    # Optional Context Context
    with st.expander("ℹ️ Provide Context (Recommended for better speaker ID)", expanded=True):
        context_info = st.text_area(
            "Context & Attendees:",
            placeholder="e.g., Present: Dr. Smith, Mr. Murphy. Chair: Sarah O'Brien. Topic: Budget Review.",
            help="Providing names here helps the AI identify speakers correctly during the initial listen."
        )

    # REORDERED TABS: Record First
    tab_rec, tab_up = st.tabs(["🎙️ Record Audio", "📁 Upload File"])
    
    audio_bytes = None
    
    with tab_rec:
        recorded_audio = st.audio_input("Record Microphone")
        if recorded_audio:
            st.audio(recorded_audio)
            audio_bytes = recorded_audio

    with tab_up:
        uploaded_audio = st.file_uploader("Upload Audio (MP3, WAV, M4A)", type=["wav", "mp3", "m4a", "ogg"])
        if uploaded_audio:
            st.audio(uploaded_audio)
            audio_bytes = uploaded_audio

    if audio_bytes and st.button("🚀 Process Meeting"):
        with st.status("Processing Meeting Audio...", expanded=True) as status:
            try:
                # 1. Prepare File
                status.write("Preparing audio file...")
                if hasattr(audio_bytes, "read"):
                    audio_bytes.seek(0)
                    data = audio_bytes.read()
                else:
                    data = audio_bytes
                
                # Determine suffix
                suffix = ".wav"
                if hasattr(audio_bytes, 'name'):
                    _, ext = os.path.splitext(audio_bytes.name)
                    if ext: suffix = ext
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name

                # 2. Upload to Gemini
                status.write(f"Uploading to {GEMINI_MODEL_NAME}...")
                gemini_file = genai.upload_file(path=tmp_path)
                
                # Wait for processing
                while gemini_file.state.name == "PROCESSING":
                    import time
                    time.sleep(2)
                    gemini_file = genai.get_file(gemini_file.name)
                
                if gemini_file.state.name == "FAILED":
                    status.update(label="Audio processing failed", state="error")
                    st.stop()

                # 3. Transcribe
                status.write("Transcribing and analysing speakers...")
                context_prompt = f"Context/Attendees: {context_info}" if context_info else ""
                
                # PROMPT UPDATE: Enforce Irish/UK English and specific formatting
                prompt = f"""
                You are a professional transcriber for HSE Capital & Estates.
                {context_prompt}
                Task: Transcribe the audio using strict Irish/UK English spelling (e.g. 'Analysing', 'Programme', 'Centre').
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
                    status.update(label="Complete!", state="complete", expanded=False)
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
    # Top Level metrics
    word_count = len(st.session_state["transcript"].split())
    st.success(f"Transcript Ready ({word_count} words).")
    
    # Notification for Speaker Map
    if "Speaker 1" in st.session_state["transcript"]:
        st.info("💡 Tip: Use the **Speaker Identity Manager** in the sidebar to rename 'Speaker 1' to a real name.")

    t1, t2, t3, t4 = st.tabs(["📝 Edit Transcript", "📄 Minutes Generator", "🔍 Briefing & Insights", "💬 Chat Agent"])

    # --- TAB 1: EDIT TRANSCRIPT (Source of Truth) ---
    with t1:
        col_head, col_save = st.columns([4, 1])
        with col_head:
            st.subheader("Raw Transcript Editor")
            st.caption("This text is the 'Source of Truth' for the Minutes and Chat.")
        
        # Text Area that updates session state
        edited_text = st.text_area(
            "Transcript Content:", 
            value=st.session_state["transcript"], 
            height=600,
            key="transcript_editor"
        )
        
        # Sync changes back to session state
        if edited_text != st.session_state["transcript"]:
            st.session_state["transcript"] = edited_text
            st.rerun()

    # --- TAB 2: MINUTES ---
    with t2:
        col_act, col_prev = st.columns([1, 1])
        with col_act:
            st.markdown("##### Action")
            if st.button("✨ Generate / Update Minutes", type="primary"):
                with st.spinner("Analysing transcript and structuring minutes..."):
                    # PROMPT UPDATE: Irish English + Euro
                    prompt_minutes = f"""
                    You are an expert secretary for HSE Capital & Estates.
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

        if "minutes_text" in st.session_state:
            st.markdown("---")
            c1, c2 = st.columns([3, 1])
            with c1:
                st.subheader("Draft Minutes")
                st.text_area("Final Output (Editable)", st.session_state["minutes_text"], height=800)
            with c2:
                st.subheader("Export")
                st.download_button(
                    "📥 Download DOCX",
                    create_docx(st.session_state["minutes_text"]),
                    f"HSE_Minutes_{datetime.now().strftime('%Y%m%d')}.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )

    # --- TAB 3: INSIGHTS ---
    with t3:
        if st.button("📊 Generate Briefing Doc"):
            with st.status("Analysing dynamics..."):
                # PROMPT UPDATE: Irish English + Euro
                p_insight = f"""
                Create a high-level "Briefing Document" (Markdown) from this transcript using Irish/UK English (e.g. Analysing, Centre).
                Currency: Euro (€).
                Include:
                1. Executive Summary
                2. Key Strategic Decisions
                3. Action Items (Table format: Who | What)
                4. Contentious Issues / Risks
                
                TRANSCRIPT: {st.session_state['transcript']}
                """
                res = model.generate_content(p_insight)
                st.session_state["briefing"] = get_gemini_text_safe(res)

        if "briefing" in st.session_state:
            st.markdown(st.session_state["briefing"])
            st.download_button("📥 Download Briefing DOCX", create_docx(st.session_state["briefing"], "overview"), "Briefing.docx")

    # --- TAB 4: CHAT ---
    with t4:
        st.subheader("Chat with the Meeting")
        st.caption("Ask questions like 'What was the budget for the Cork project?' or 'Who disagreed with the plan?'")
        
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Ask a question about the meeting..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                # PROMPT UPDATE: Irish English + Euro
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


