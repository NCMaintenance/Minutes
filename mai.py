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
GEMINI_MODEL_NAME = 'gemini-3-flash-preview'

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

# --- Narrative DOCX Export ---
def create_narrative_docx(narrative_text):
    doc = Document()
    doc.add_heading("HSE Capital & Estates Meeting – Meeting Summary", level=1)
    doc.add_paragraph(narrative_text)
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

# --- Key Points Summary DOCX Export ---
def create_keypoints_docx(text):
    doc = Document()
    doc.add_heading("HSE Capital & Estates Meeting – Key Points & Actions", level=1)
    doc.add_paragraph(text)
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

# --- DOCX Export Function for Minutes ---
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

st.set_page_config(page_title="MAI Recap", layout="wide", page_icon="https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png")

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
        keys_to_clear = ['transcript', 'structured', 'minutes', 'narrative', 'keypoints_summary']
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

    if st.button("About this App", key="about_button_sidebar"):
        st.sidebar.info(
            "**MAI Recap** helps generate meeting minutes for the Health Service Executive (HSE). "
            "Upload or record audio, and the app will transcribe and summarise it."
        )
    if st.button("Created by Dave Maher", key="creator_button_sidebar"):
        st.sidebar.write("This application's intellectual property belongs to Dave Maher.")
    st.markdown("---")
    
    st.markdown(f"Model: {GEMINI_MODEL_NAME}")
    # UPDATED: Removed "(Bug Fixes)"
    st.markdown("Version: 1.2.3")

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

st.markdown("### 📤 Record or Upload Meeting Audio")

# --- Input Method Selection ---
mode = st.radio(
    "Choose input method:",
    ["Record using microphone","Upload audio file"],
    horizontal=True,
    key="input_mode_radio"
)

audio_bytes = None

if mode == "Upload audio file":
    uploaded_audio = st.file_uploader(
        "Upload an audio file (WAV, MP3, M4A, OGG, FLAC)",
        type=["wav", "mp3", "m4a", "ogg", "flac"],
        key="audio_uploader"
    )
    if uploaded_audio:
        st.audio(uploaded_audio)
        audio_bytes = uploaded_audio

elif mode == "Record using microphone":
    st.info("Recording functionality may vary by browser. Please use the upload feature for best results.")
    recorded_audio = st.audio_input("🎙️ Click the microphone to record, then click again to stop and process.", key="audio_recorder_main")
    if recorded_audio:
        st.audio(recorded_audio, format="audio/wav")
        audio_bytes = recorded_audio

# --- Transcription and Analysis ---
if audio_bytes and st.button("🧠 Transcribe & Analyse", key="transcribe_button"):
    with st.spinner(f"Processing with {GEMINI_MODEL_NAME}... This may take a few minutes for longer audio."):
        
        # Handle file data
        if hasattr(audio_bytes, "read") and callable(audio_bytes.read):
            audio_bytes.seek(0) # Reset pointer
            audio_data_bytes = audio_bytes.read()
        elif isinstance(audio_bytes, bytes):
            audio_data_bytes = audio_bytes
        else:
            st.error("Could not read audio data. Please try uploading/recording again.")
            st.stop()

        # Determine extension
        temp_file_suffix = ".wav"
        if hasattr(audio_bytes, 'name') and isinstance(audio_bytes.name, str):
            original_extension = os.path.splitext(audio_bytes.name)[1].lower()
            if original_extension in ['.mp3', '.m4a', '.ogg', '.flac']:
                temp_file_suffix = original_extension

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=temp_file_suffix) as tmp_file:
            tmp_file.write(audio_data_bytes)
            tmp_file_path = tmp_file.name
        
        audio_file = None
        try:
            st.info(f"Uploading audio to Gemini for processing (size: {len(audio_data_bytes) / (1024*1024):.2f} MB)...")
            audio_file_display_name = f"MAI_Recap_Audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Upload to Gemini
            audio_file = genai.upload_file(path=tmp_file_path, display_name=audio_file_display_name)
            
            # Wait for processing to complete (important for large files)
            while audio_file.state.name == "PROCESSING":
                import time
                time.sleep(2)
                audio_file = genai.get_file(audio_file.name)
            
            if audio_file.state.name == "FAILED":
                raise ValueError("Audio processing failed on Gemini side.")

            st.success(f"Audio uploaded successfully: {audio_file.name}")

            prompt = (
                "You are an expert transcriptionist for HSE Capital & Estates meetings. "
                "Transcribe in UK English the following meeting audio accurately. "
                "For each speaker, if a name is mentioned, use their name (e.g., Chairperson:, John Smith:). "
                "If not, label generically as Speaker 1:, Speaker 2:, etc., incrementing for each new unidentified voice. "
                "IMPORTANT: Output ONLY the transcript text. Do not include any conversational filler, introductory remarks, or sign-offs at the end. "
                "Ensure all currency figures are transcribed with the Euro symbol (€)."
            )
            
            # Generate Transcript
            result = model.generate_content([prompt, audio_file], request_options={"timeout": 1200})
            
            # Robust text extraction to handle "no valid Part" errors
            try:
                transcript = result.text
            except ValueError:
                # Handle cases where the model returns no content
                transcript = "(No transcript generated. The audio might be silent, or safety filters were triggered.)"
                if result.candidates:
                     st.warning(f"Model finish reason: {result.candidates[0].finish_reason}")
            
            st.session_state["transcript"] = transcript
            st.success("Transcript generated successfully.")

        except Exception as e:
            st.error(f"An error occurred during transcription: {e}")
            if audio_file:
                try:
                    genai.delete_file(audio_file.name)
                except Exception:
                    pass
        finally:
            # Cleanup Gemini file
            if audio_file:
                 try:
                    genai.delete_file(audio_file.name)
                    st.info(f"Processed and deleted uploaded file: {audio_file.name} from Gemini.")
                 except Exception as del_e:
                    st.warning(f"Could not delete uploaded file {audio_file.name} from Gemini: {del_e}")
            # Cleanup local temp file
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

# --- Display Transcript and Generate Minutes ---
if "transcript" in st.session_state:
    st.markdown("## 📄 Transcript")
    st.text_area("Full Meeting Transcript:", st.session_state["transcript"], height=300, key="transcript_display_area")

    if st.button("📊 Extract & Format Meeting Minutes", key="summarise_button"):
        with st.spinner("Generating structured meeting minutes..."):
            try:
                current_transcript = st.session_state['transcript']
                # --- Structured Summary, Capital & Estates ---
                prompt_structured = f"""
You are an AI assistant for Health Service Executive (HSE) Capital & Estates meetings.
Your task is to extract detailed UK English, structured information from the provided meeting transcript and return a JSON object matching the following keys.
Format all dates as DD/MM/YYYY and all times as HH:MM (24 hour).
Ensure all currency values use the Euro symbol (€), not Pounds (£).
If a key is not mentioned, use "Not mentioned" or an empty list if appropriate.

Keys to include:
- meetingTitle
- meetingDate
- startTime
- endTime
- location
- chairperson
- minuteTaker
- attendees (list)
- apologies (list)
- previousMeetingDate
- mattersArising (list)
- declarationsOfInterest
- majorProjects (list)
- minorProjects (list)
- estatesStrategy (list)
- healthSafety (list)
- riskRegister (list)
- financeUpdate (list)
- aob (list)
- nextMeetingDate
- meetingClosedTime
- minutesPreparedBy
- preparationDate

Transcript:
---
{current_transcript}
---

Provide ONLY the JSON object in your response. Do not include any other text before or after the JSON.
"""
                # Use generation config to enforce JSON if supported by the model
                generation_config = {"response_mime_type": "application/json"}
                
                response1 = model.generate_content(
                    prompt_structured, 
                    generation_config=generation_config,
                    request_options={"timeout": 600}
                )
                
                # Robust JSON parsing
                try:
                    # Safely access text
                    try:
                        response_text = response1.text
                    except ValueError:
                        response_text = ""
                    
                    structured = json.loads(response_text)
                except json.JSONDecodeError:
                    # Fallback regex extraction if raw text returned
                    # Re-use safe response_text from above
                    json_text_match = re.search(r"```json\s*([\s\S]*?)\s*```|({[\s\S]*})", response_text if 'response_text' in locals() else "", re.DOTALL)
                    if json_text_match:
                        json_str = json_text_match.group(1) or json_text_match.group(2)
                        structured = json.loads(json_str.strip())
                    else:
                        # Default to empty dict if JSON fails
                        structured = {}

                # FIX: Handle case where AI returns a list instead of a dictionary
                if isinstance(structured, list):
                    if len(structured) > 0 and isinstance(structured[0], dict):
                        structured = structured[0]
                    else:
                        # If list is empty or doesn't contain a dict, default to empty dict
                        structured = {}

                st.session_state["structured"] = structured

                # Generate formatted minutes
                if "structured" in st.session_state:
                    minutes_text = generate_capital_estates_minutes(st.session_state["structured"])
                    st.session_state["minutes"] = minutes_text
                    st.success("Meeting minutes generated in HSE Capital & Estates format.")

                # --- Generate Narrative Summary for Whole Meeting ---
                prompt_narrative = f"""
You are an AI assistant tasked with creating a professional, concise summary of a HSE Capital & Estates meeting in UK English.
Based on the following transcript, write a coherent, narrative summary of the meeting.
The summary should be well-organized, easy to read, and capture the main points, discussions, and outcomes.
Ensure all currency figures are formatted with the Euro symbol (€).
Clearly indicate who said what; if a speaker's name is not provided, use labels like "Speaker 1", "Speaker 2", etc.
Do not include speaker labels unless essential for context.

Transcript:
---
{current_transcript}
---

Narrative Summary:
"""
                response2 = model.generate_content(prompt_narrative, request_options={"timeout": 1200})
                
                try:
                    st.session_state["narrative"] = response2.text
                except ValueError:
                    st.session_state["narrative"] = "Unable to generate narrative summary (Empty response from model)."

            except Exception as e:
                st.error(f"An error occurred during summarization: {e}")
                st.error(f"Details: {str(e)}")

# --- Key Points and Actions Summary ---
if "transcript" in st.session_state and "minutes" in st.session_state:
    if st.button("🧾 Summarise Meeting: Key Points & Actions", key="keypoints_button"):
        with st.spinner("Summarising transcript for key points and actions..."):
            try:
                prompt_keypoints = f"""
You are an AI assistant for HSE Capital & Estates meetings.
Summarise the following transcript into concise bullet points, focusing on:
- Key discussion points
- Major decisions made
- All action items (with responsible persons/roles and deadlines, if mentioned)

Ensure all currency figures are formatted with the Euro symbol (€).
Be succinct, avoid repetition, and use bullet points.

Transcript:
---
{st.session_state['transcript']}
---
"""
                response = model.generate_content(prompt_keypoints, request_options={"timeout": 600})
                
                try:
                    st.session_state["keypoints_summary"] = response.text
                except ValueError:
                    st.session_state["keypoints_summary"] = "Unable to generate key points (Empty response from model)."

                st.success("Key points and action summary generated.")
            except Exception as e:
                st.error(f"An error occurred during key points summarisation: {e}")

if "keypoints_summary" in st.session_state:
    st.markdown("## 🔑 Key Points & Actions Summary")
    st.text_area(
        "Meeting Key Points & Actions:",
        st.session_state["keypoints_summary"],
        height=500,
        key="keypoints_text_area"
    )
    st.download_button(
        label="📥 Download Key Points & Actions (DOCX)",
        data=create_keypoints_docx(st.session_state["keypoints_summary"]),
        file_name=f"HSE_Meeting_KeyPoints_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="download_keypoints_docx"
    )

# --- Display Formatted Minutes and Download ---
if "minutes" in st.session_state:
    st.markdown("---")
    st.markdown("## 🏢 Capital & Estates Meeting Minutes (Draft)")
    st.text_area(
        "Drafted HSE Capital & Estates Meeting Minutes:",
        st.session_state["minutes"],
        height=900,
        key="minutes_text_area"
    )
    st.download_button(
        label="📥 Download Minutes (DOCX)",
        data=create_docx(st.session_state["minutes"], kind="minutes"),
        file_name=f"HSE_Capital_Estates_Minutes_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="download_minutes_docx"
    )

# --- Download Narrative Summary as DOCX ---
if "narrative" in st.session_state:
    st.markdown("## 📝 Download Meeting Summary")
    st.text_area(
        "Meeting Narrative Summary:",
        st.session_state["narrative"],
        height=600,
        key="narrative_text_area"
    )
    st.download_button(
        label="📥 Download Meeting Summary (DOCX)",
        data=create_narrative_docx(st.session_state["narrative"]),
        file_name=f"HSE_Meeting_Summary_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="download_narrative_docx"
    )

# --- Footer ---
st.markdown("---")
st.markdown(
    "**Disclaimer:** This implementation has been tested using sample data. "
    "Adjustments may be required to ensure optimal performance and accuracy with real-world meeting audio. "
    "Always verify the accuracy of transcriptions and minutes."
)
st.markdown("Created by Dave Maher | For HSE internal use.")
