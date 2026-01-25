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
import time

# --- Configuration ---
# UPDATED: Using the specific preview model as requested
GEMINI_MODEL_NAME = 'gemini-3-flash-preview'
APP_VERSION = "5.0 Pro"
HSE_GREEN = "#00563B"
HSE_BLUE = "#005EB8"

# --- Setup & Config ---
st.set_page_config(
    page_title="MAI Recap Pro",
    layout="wide",
    page_icon="📝",
    initial_sidebar_state="expanded"
)

# --- Custom CSS (Professional / Minimalist) ---
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    * {{
        font-family: 'Inter', sans-serif;
    }}
    
    .stApp {{
        background-color: #f8f9fa;
    }}
    
    /* Headers */
    h1, h2, h3 {{
        color: {HSE_GREEN} !important;
        font-weight: 600 !important;
    }}
    
    /* Buttons */
    .stButton > button {{
        background-color: white;
        color: #333;
        border: 1px solid #ddd;
        border-radius: 4px;
        font-weight: 500;
        transition: all 0.2s;
    }}
    
    .stButton > button:hover {{
        border-color: {HSE_GREEN};
        color: {HSE_GREEN};
    }}
    
    /* Primary Action Buttons */
    .stButton > button[kind="primary"] {{
        background-color: {HSE_GREEN};
        color: white;
        border: 1px solid {HSE_GREEN};
    }}
    
    .stButton > button[kind="primary"]:hover {{
        background-color: {HSE_BLUE};
        border-color: {HSE_BLUE};
        color: white;
    }}
    
    /* Inputs */
    .stTextInput > div > div > input, .stTextArea > div > div > textarea {{
        border-radius: 4px;
        border-color: #dee2e6;
    }}
    
    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: #ffffff;
        border-right: 1px solid #eaeaea;
    }}
</style>
""", unsafe_allow_html=True)

# --- API Configuration ---
@st.cache_resource
def configure_genai():
    try:
        api_key = None
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
        elif os.getenv("GEMINI_API_KEY"):
            api_key = os.getenv("GEMINI_API_KEY")
            
        if not api_key:
            return None
            
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(model_name=GEMINI_MODEL_NAME)
    except Exception as e:
        return None

model = configure_genai()

# --- Utility Functions ---

def get_gemini_text_safe(response):
    """Safely extracts text from a Gemini response."""
    try:
        return response.text
    except ValueError:
        error_msg = "[System: Model response was blocked or empty]"
        if hasattr(response, "candidates") and response.candidates:
            finish_reason = response.candidates[0].finish_reason
            error_msg += f" (Reason: {finish_reason})"
        return error_msg

def detect_speakers(text):
    """
    Scans the transcript for patterns like 'Speaker 1:', '**Speaker 1**:', etc.
    Returns a clean list of unique speaker names.
    """
    if not text:
        return []
    
    # Pattern looks for names followed by a colon at the start of lines
    pattern = r'(?m)^(?:[\*\_]{2})?([A-Za-z0-9\s\(\)\-\.]+?)(?:[\*\_]{2})?[:]'
    matches = re.findall(pattern, text)
    unique_speakers = sorted(list(set(matches)))
    clean_speakers = [s for s in unique_speakers if len(s) < 40 and s.strip()]
    return clean_speakers

def create_docx(content, kind="minutes"):
    """Generates a DOCX file with HSE specific formatting."""
    doc = Document()
    
    # Header
    section = doc.sections[0]
    header = section.header
    try:
        paragraph = header.paragraphs[0]
    except IndexError:
        paragraph = header.add_paragraph()
        
    paragraph.text = "HSE Capital & Estates - Internal Document"
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    if kind == "minutes":
        doc.add_heading("Meeting Minutes", level=1)
        
        for line in content.splitlines():
            clean_line = line.strip()
            # Detect Headers (Ends in colon, not a bullet point)
            if clean_line.endswith(":") and not clean_line.startswith("•") and len(clean_line) < 60:
                heading = doc.add_heading(clean_line, level=2)
                if heading.runs:
                    run = heading.runs[0]
                    run.font.color.rgb = RGBColor(0, 86, 59) # HSE Green
            # Detect Divider
            elif "___" in clean_line:
                doc.add_paragraph("-" * 50)
            # Standard Text
            elif clean_line:
                p = doc.add_paragraph(clean_line)
                if clean_line.startswith("•") or clean_line.startswith("-"):
                    p.style = 'List Bullet'
                    
    else:
        doc.add_heading("Meeting Briefing / Overview", level=1)
        doc.add_paragraph(content)
        
    # Footer
    footer = section.footer
    try:
        p = footer.paragraphs[0]
    except IndexError:
        p = footer.add_paragraph()
        
    p.text = f"Generated by MAI Recap Pro v{APP_VERSION} | {datetime.now().strftime('%d/%m/%Y')}"
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

# --- HSE Minutes Generator Logic ---
def generate_minutes_text(structured_data):
    def get(val, default="Not mentioned"):
        return val if val and str(val).lower() != "not mentioned" else default

    def fmt_list(val):
        if isinstance(val, list) and val:
            return "".join([f"• {item}\n" for item in val if item])
        if isinstance(val, str) and val.strip():
            return f"• {val}\n"
        return "Not mentioned\n"

    meta = structured_data
    
    text = f"""Meeting Title: {get(meta.get('meetingTitle'), 'General Meeting')}
Date: {get(meta.get('meetingDate'))}
Time: {get(meta.get('startTime'))} - {get(meta.get('endTime'))}
Location: {get(meta.get('location'))}
Chairperson: {get(meta.get('chairperson'))}
________________________________________
1. Attendance
Present:
{fmt_list(meta.get('attendees'))}
Apologies:
{fmt_list(meta.get('apologies'))}
________________________________________
2. Minutes of Previous Meeting
• Date of previous meeting: {get(meta.get('previousMeetingDate'))}
• Matters Arising:
{fmt_list(meta.get('mattersArising'))}
________________________________________
3. Capital Projects Update
3.1 Major Projects:
{fmt_list(meta.get('majorProjects'))}
3.2 Minor Works / Equipment:
{fmt_list(meta.get('minorProjects'))}
________________________________________
4. Key Discussions & Decisions
{fmt_list(meta.get('keyDiscussions'))}
________________________________________
5. Action Items
{fmt_list(meta.get('actionItems'))}
________________________________________
6. Next Meeting
• Date: {get(meta.get('nextMeetingDate'))}
"""
    return text

# --- State Management ---
if "transcript" not in st.session_state:
    st.session_state["transcript"] = ""
if "password_verified" not in st.session_state:
    st.session_state["password_verified"] = False
if "messages" not in st.session_state:
    st.session_state["messages"] = []

# --- Authentication ---
if not st.session_state.password_verified:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(f"<h2 style='text-align: center; color: {HSE_GREEN};'>MAI Recap Pro</h2>", unsafe_allow_html=True)
        st.info("Secure Access: HSE Capital & Estates")
        
        with st.form("login_form"):
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)
            
            if submitted:
                if st.secrets.get("password") and password == st.secrets["password"]:
                    st.session_state.password_verified = True
                    st.rerun()
                elif not st.secrets.get("password"):
                     st.warning("Password not configured in secrets.toml.")
                else:
                    st.error("Invalid credentials.")
    st.stop()

# --- Sidebar ---
with st.sidebar:
    st.markdown("### MAI Recap Pro")
    st.caption(f"Version {APP_VERSION}")
    st.caption(f"Engine: {GEMINI_MODEL_NAME}")
    
    if st.button("New Meeting Session", type="primary", use_container_width=True):
        st.session_state["transcript"] = ""
        st.session_state["messages"] = []
        st.rerun()

    st.markdown("---")
    
    # --- Speaker Identity Manager ---
    if st.session_state["transcript"]:
        st.markdown("#### Speaker Management")
        st.caption("Map generic IDs (e.g., Speaker 1) to real names.")
        
        detected = detect_speakers(st.session_state["transcript"])
        
        if not detected:
            st.caption("No speaker labels detected.")
        else:
            with st.form("speaker_map"):
                replacements = {}
                for spk in detected:
                    new_val = st.text_input(f"{spk} →", placeholder="Real Name")
                    if new_val and new_val != spk:
                        replacements[spk] = new_val
                
                if st.form_submit_button("Update Transcript", use_container_width=True):
                    txt = st.session_state["transcript"]
                    count = 0
                    for old, new in replacements.items():
                        # Replace "Speaker 1:" and "**Speaker 1**:"
                        patterns = [f"{old}:", f"**{old}**:"]
                        for p in patterns:
                            if p in txt:
                                txt = txt.replace(p, f"**{new}**:")
                                count += 1
                    
                    if count > 0:
                        st.session_state["transcript"] = txt
                        st.success(f"Updated {count} speaker references.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("No matches found to update.")

# --- Main Content ---
st.title("MAI Recap Pro")
st.markdown("**HSE Capital & Estates Meeting Assistant**")

if not model:
    st.error(f"API Key missing or invalid model `{GEMINI_MODEL_NAME}`. Please check settings.")
    st.stop()

# --- INPUT SECTION ---
if not st.session_state["transcript"]:
    st.markdown("### 1. Meeting Source")
    
    with st.expander("Meeting Context (Optional but Recommended)", expanded=True):
        context = st.text_area(
            "Attendees & Topic:",
            placeholder="e.g. Present: Dr. Murphy, Sarah O'Connor. Topic: Budget Q3.",
            height=70
        )
    
    tab1, tab2 = st.tabs(["Upload Audio", "Record Audio"])
    
    audio_file = None
    
    with tab1:
        uploaded_file = st.file_uploader("Select File (MP3, WAV, M4A)", type=['mp3', 'wav', 'm4a'])
        if uploaded_file:
            audio_file = uploaded_file
            
    with tab2:
        recorded_file = st.audio_input("Microphone Input")
        if recorded_file:
            audio_file = recorded_file

    if audio_file:
        if st.button("Process Audio", type="primary"):
            with st.status("Processing meeting audio...", expanded=True) as status:
                try:
                    # 1. Save to temp
                    status.write("Preparing file...")
                    suffix = ".wav"
                    if hasattr(audio_file, 'name'):
                        _, ext = os.path.splitext(audio_file.name)
                        if ext: suffix = ext
                        
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(audio_file.getvalue())
                        tmp_path = tmp.name
                    
                    # 2. Upload
                    status.write(f"Uploading to {GEMINI_MODEL_NAME}...")
                    gemini_file = genai.upload_file(tmp_path)
                    
                    while gemini_file.state.name == "PROCESSING":
                        time.sleep(2)
                        gemini_file = genai.get_file(gemini_file.name)
                        
                    if gemini_file.state.name == "FAILED":
                        raise Exception("Processing failed on server.")
                        
                    # 3. Transcribe
                    status.write("Transcribing with UK English constraints...")
                    prompt = f"""
                    You are a professional transcriber for the HSE (Health Service Executive).
                    Context: {context}
                    
                    Task: Transcribe the audio verbatim using strict UK/Irish English spelling (e.g. 'Programme', 'Centre', 'Analysing').
                    Formatting: Identify speakers as '**Speaker Name**:'. If unknown, use '**Speaker 1**:'.
                    Currency: Convert all monetary values to Euro (€).
                    """
                    
                    response = model.generate_content([prompt, gemini_file])
                    st.session_state["transcript"] = get_gemini_text_safe(response)
                    
                    status.update(label="Complete", state="complete", expanded=False)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    if 'tmp_path' in locals() and os.path.exists(tmp_path):
                        os.unlink(tmp_path)

# --- OUTPUT SECTION ---
else:
    tab_trans, tab_mins, tab_brief, tab_chat = st.tabs(["Transcript", "Minutes", "Briefing", "Chat"])
    
    # TAB: TRANSCRIPT
    with tab_trans:
        col_head, col_dl = st.columns([4, 1])
        with col_head:
            st.markdown("### Raw Transcript")
        with col_dl:
            st.download_button("Download .txt", st.session_state["transcript"], "transcript.txt")
            
        edited = st.text_area("Editor (Source of Truth)", st.session_state["transcript"], height=600)
        if edited != st.session_state["transcript"]:
            st.session_state["transcript"] = edited
            
    # TAB: MINUTES
    with tab_mins:
        st.markdown("### Formal Minutes")
        if st.button("Generate Minutes", type="primary"):
            with st.spinner("Extracting structured data..."):
                prompt = f"""
                Act as an HSE Secretary. Extract structured data from the transcript.
                Use UK/Irish English spelling. Currency: Euro (€).
                Dates: DD/MM/YYYY.
                
                Return valid JSON strictly matching this structure:
                {{
                    "meetingTitle": "string",
                    "meetingDate": "string",
                    "startTime": "string",
                    "endTime": "string",
                    "location": "string",
                    "chairperson": "string",
                    "attendees": ["string"],
                    "apologies": ["string"],
                    "previousMeetingDate": "string",
                    "mattersArising": ["string"],
                    "majorProjects": ["string"],
                    "minorProjects": ["string"],
                    "keyDiscussions": ["string"],
                    "actionItems": ["string (Who: What)"],
                    "nextMeetingDate": "string"
                }}
                
                Transcript:
                {st.session_state["transcript"]}
                """
                try:
                    res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
                    data = json.loads(get_gemini_text_safe(res))
                    # Handle if Gemini returns a list wrapped in json
                    if isinstance(data, list): data = data[0]
                    
                    minutes_text = generate_minutes_text(data)
                    st.session_state["minutes_text"] = minutes_text
                except Exception as e:
                    st.error(f"Generation failed: {e}")
                    
        if "minutes_text" in st.session_state:
            st.text_area("Preview", st.session_state["minutes_text"], height=500)
            st.download_button(
                "Download Minutes (.docx)",
                create_docx(st.session_state["minutes_text"], "minutes"),
                "HSE_Minutes.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

    # TAB: BRIEFING
    with tab_brief:
        st.markdown("### Executive Briefing")
        if st.button("Generate Briefing"):
            with st.spinner("Summarizing..."):
                prompt = f"""
                Create a high-level briefing document (Markdown) from this transcript.
                Target Audience: Senior Management.
                Style: UK English, Professional, Concise.
                Sections: Executive Summary, Key Decisions, Risks/Issues, Strategic alignment.
                Transcript: {st.session_state["transcript"]}
                """
                res = model.generate_content(prompt)
                st.session_state["briefing"] = get_gemini_text_safe(res)
                
        if "briefing" in st.session_state:
            st.markdown(st.session_state["briefing"])
            st.download_button(
                "Download Briefing (.docx)",
                create_docx(st.session_state["briefing"], "briefing"),
                "Briefing.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

    # TAB: CHAT
    with tab_chat:
        st.markdown("### Meeting Assistant")
        
        for msg in st.session_state["messages"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
        if user_input := st.chat_input("Ask about the meeting..."):
            st.session_state["messages"].append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)
                
            with st.chat_message("assistant"):
                prompt = f"""
                You are a helpful assistant answering questions about the provided meeting transcript.
                Use UK/Irish English. Quote the speaker if relevant.
                Transcript: {st.session_state["transcript"]}
                Question: {user_input}
                """
                res = model.generate_content(prompt)
                reply = get_gemini_text_safe(res)
                st.markdown(reply)
                st.session_state["messages"].append({"role": "assistant", "content": reply})


