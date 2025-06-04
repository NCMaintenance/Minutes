import streamlit as st
import google.generativeai as genai
import json
import os
from datetime import datetime # Imported but not actively used
from docx import Document
import io
import tempfile
import re

# --- Utility to prettify keys ---
def prettify_key(key):
    """
    Formats a string key for better display.
    Replaces underscores with spaces, adds spaces before capital letters in camelCase,
    title cases the string, and appends a colon.
    Example: "patientName_detail" -> "Patient Name Detail:"
    """
    key = key.replace('_', ' ')
    key = re.sub(r'([a-z])([A-Z])', r'\1 \2', key) # Add space before capital letters
    return key.title() + ":"

# --- Configure Gemini API ---
# Ensure the API key is set in Streamlit secrets
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel(model_name='gemini-2.0-flash-exp') # Using a specific Gemini model
except KeyError:
    st.error("GEMINI_API_KEY not found in Streamlit secrets. Please add it to continue.")
    st.stop()
except Exception as e:
    st.error(f"Error configuring Gemini API: {e}")
    st.stop()


st.set_page_config(page_title="MAI Recap", layout="wide")

# --- Password protection ---
# Initialize session state for password verification if not already present
if "password_verified" not in st.session_state:
    st.session_state.password_verified = False

# If password is not verified, show password input
if not st.session_state.password_verified:
    st.title("🔒 MAI Recap Access")
    st.warning("This application requires a password to proceed.")
    with st.form("password_form"):
        user_password = st.text_input("Enter password:", type="password", key="password_input")
        submit_button = st.form_submit_button("Submit")

        if submit_button:
            try:
                # Retrieve the password from Streamlit secrets
                expected_password = st.secrets["password"]
                if user_password == expected_password:
                    st.session_state.password_verified = True
                    st.rerun() # Rerun the script to show the main app
                else:
                    st.error("Incorrect password. Please try again.")
            except KeyError:
                st.error("Password not configured in Streamlit secrets. Please contact the administrator.")
            except Exception as e:
                st.error(f"An error occurred during password verification: {e}")
    st.stop() # Stop execution if password is not verified

# --- Sidebar ---
with st.sidebar:
    st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=200, caption="HSE Logo")
    st.title("🩺 MAI Recap")
    if st.button("About this App", key="about_button_sidebar"):
        st.sidebar.info(
            "**MAI Recap** helps generate meeting minutes for the Health Service Executive (HSE). "
            "Upload or record audio, and the app will transcribe and summarise it."
        )
    if st.button("Created by Dave Maher", key="creator_button_sidebar"):
        st.sidebar.write("This application's intellectual property belongs to Dave Maher.")
    st.markdown("---")
    st.markdown("Version: 1.0.0")


# --- Main UI Header ---
col1, col2 = st.columns([1, 6])
with col1:
    st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=80)
with col2:
    st.title("📝 MAI Recap")
    st.markdown("#### Health Service Executive (HSE) Minutes Generator")

st.markdown("### 📤 Upload or Record Meeting Audio")

# --- Input Method Selection ---
mode = st.radio(
    "Choose input method:",
    ["Upload audio file", "Record using microphone"],
    horizontal=True,
    key="input_mode_radio"
)

audio_bytes = None
# Note: audio_format is declared but its value might need to be dynamic based on uploaded file type
# For recording, it's often WAV. For uploads, it can vary.
# The st.audio component handles format detection for display.

if mode == "Upload audio file":
    uploaded_audio = st.file_uploader(
        "Upload an audio file (WAV, MP3, M4A, OGG, FLAC)",
        type=["wav", "mp3", "m4a", "ogg", "flac"], # Added more common audio types
        key="audio_uploader"
    )
    if uploaded_audio:
        st.audio(uploaded_audio) # Let st.audio handle format for playback
        audio_bytes = uploaded_audio # Keep as file-like object for now

elif mode == "Record using microphone":
    # Streamlit's native audio recorder component
    # This component was experimental and its availability/API might change.
    # Using st.audio with type="bytes" for recording if available,
    # otherwise, this part might need a third-party component or updated Streamlit feature.
    # For now, assuming a hypothetical st.audio_recorder or similar.
    # The original code used `st.audio_input` which is not a standard Streamlit component.
    # Let's use a placeholder or a more common approach if st.audio_input is custom.
    # For demonstration, let's assume we get bytes from a recorder.
    # If using a library like `st_audiorec`, the usage would be different.
    # Given the original code's `st.audio_input`, it might be a custom component.
    # For robustness, we'll check if `st.audio_recorder` exists, else provide a message.

    if hasattr(st, "audio_recorder"): # Check if a built-in recorder exists
        recorded_audio_bytes = st.audio_recorder(
            text="🎙️ Click to record, click again to stop",
            icon_size="2x",
            key="audio_recorder_main"
        )
        if recorded_audio_bytes:
            st.audio(recorded_audio_bytes, format="audio/wav")
            audio_bytes = recorded_audio_bytes # Store as bytes
    else:
        st.info("Audio recording functionality might require a specific Streamlit version or a custom component (`st.audio_input` was used in the original script).")
        # Fallback if no recorder is available or for older Streamlit versions:
        # recorded_audio = st.file_uploader("Upload a recording (WAV)", type=["wav"])
        # if recorded_audio:
        #     st.audio(recorded_audio, format="audio/wav")
        #     audio_bytes = recorded_audio


# --- Transcription and Analysis ---
if audio_bytes and st.button("🧠 Transcribe & Analyse", key="transcribe_button"):
    with st.spinner("Processing with Gemini... This may take a few minutes for longer audio."):
        # If uploaded_audio is a file uploader object, read its bytes
        if hasattr(audio_bytes, "read") and callable(audio_bytes.read):
            audio_data_bytes = audio_bytes.read()
        elif isinstance(audio_bytes, bytes): # If it's already bytes (e.g., from recorder)
            audio_data_bytes = audio_bytes
        else:
            st.error("Could not read audio data. Please try uploading/recording again.")
            st.stop()

        # Use a temporary file to upload to Gemini API
        # Gemini API typically requires a file path or publicly accessible URI for `upload_file`
        # Suffix should ideally match the actual audio format, but .wav is often a safe bet for processing
        # For more robust handling, detect original format or convert.
        # Assuming WAV for simplicity here as Gemini often handles various inputs if not specified.
        temp_file_suffix = ".wav"
        if hasattr(audio_bytes, 'name') and isinstance(audio_bytes.name, str):
            original_extension = os.path.splitext(audio_bytes.name)[1].lower()
            if original_extension in ['.mp3', '.m4a', '.ogg', '.flac']:
                temp_file_suffix = original_extension
                # Note: Gemini might prefer certain formats or handle conversion.
                # If specific conversion is needed, libraries like pydub would be used here.

        with tempfile.NamedTemporaryFile(delete=False, suffix=temp_file_suffix) as tmp_file:
            tmp_file.write(audio_data_bytes)
            tmp_file_path = tmp_file.name
        try:
            st.info(f"Uploading audio to Gemini for processing (size: {len(audio_data_bytes) / (1024*1024):.2f} MB)...")
            # The display_name is optional but good for tracking in Gemini console
            audio_file_display_name = f"MAI_Recap_Audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            audio_file = genai.upload_file(path=tmp_file_path, display_name=audio_file_display_name)
            st.success(f"Audio uploaded successfully: {audio_file.name}")

            prompt = (
                "You are an expert transcriptionist specializing in medical meetings. "
                "Transcribe the following meeting audio accurately. "
                "Clearly label speakers if discernible (e.g., Speaker 1:, Dr. Smith:, Nurse Jones:). "
                "If speakers are not clearly distinguishable, use generic labels like 'Speaker A:', 'Speaker B:'."
            )
            # Increased timeout for potentially long audio files
            result = model.generate_content([prompt, audio_file], request_options={"timeout": 1200}) # 20 minutes
            transcript = result.text
            st.session_state["transcript"] = transcript
            st.success("Transcript generated successfully.")

        except Exception as e:
            st.error(f"An error occurred during transcription: {e}")
            if 'audio_file' in locals() and audio_file: # Clean up uploaded file if error occurs after upload
                try:
                    genai.delete_file(audio_file.name)
                    st.info(f"Cleaned up uploaded file: {audio_file.name}")
                except Exception as del_e:
                    st.warning(f"Could not delete uploaded file {audio_file.name} from Gemini: {del_e}")
        finally:
            if 'audio_file' in locals() and audio_file: # Ensure file is deleted from Gemini after processing
                 try:
                    genai.delete_file(audio_file.name)
                    st.info(f"Processed and deleted uploaded file: {audio_file.name} from Gemini.")
                 except Exception as del_e:
                    st.warning(f"Could not delete uploaded file {audio_file.name} from Gemini: {del_e}")
            if os.path.exists(tmp_file_path): # Delete local temporary file
                os.remove(tmp_file_path)


# --- Display Transcript ---
if "transcript" in st.session_state:
    st.markdown("## 📄 Transcript")
    st.text_area("Full Meeting Transcript:", st.session_state["transcript"], height=300, key="transcript_display_area")

    if st.button("📊 Summarise Transcript", key="summarise_button"):
        with st.spinner("Generating structured, narrative, and brief summaries... This may take a moment."):
            try:
                current_transcript = st.session_state['transcript']
                # --- Structured Summary ---
                # This prompt is quite specific. The model's ability to follow this structure perfectly
                # depends on its training and the clarity of the transcript.
                prompt_structured = f"""
You are an AI assistant for Health Service Executive (HSE) meetings.
Your task is to extract detailed, structured information from the provided meeting transcript.
Format the output as a single, valid JSON object.
The JSON object should include the following keys. If a piece of information is not mentioned in the transcript, use the string "Not mentioned".

Keys to include:
- "meetingTitle": (e.g., "Patient Case Review - John Doe")
- "meetingDate": (e.g., "YYYY-MM-DD", if mentioned, otherwise "Not mentioned")
- "attendees": (List of strings, e.g., ["Dr. Smith", "Nurse Jones"], or "Not mentioned")
- "patientName": (If applicable, otherwise "Not applicable" or "Not mentioned")
- "dateOfVisit": (If applicable, e.g., "YYYY-MM-DD", otherwise "Not applicable" or "Not mentioned")
- "chiefComplaint": (Patient's main reason for visit, if applicable)
- "historyPresentIllness": (Detailed history of current issues, if applicable)
- "pastMedicalHistory": (Relevant past medical conditions, if applicable)
- "medications": (List of current medications, if applicable)
- "allergies": (List of allergies, if applicable)
- "reviewOfSystems": (Systematic review of body systems, if applicable)
- "physicalExamFindings": (Key findings from physical examination, if applicable)
- "assessmentAndDiagnosis": (Assessment of the situation and any diagnoses made)
- "planOfAction": (Specific steps to be taken, treatments, referrals)
- "keyDecisionsMade": (List of important decisions)
- "actionItems": (List of objects, each with "task" and "assignedTo" and "dueDate" if mentioned, e.g., [{{"task": "Schedule follow-up", "assignedTo": "Admin", "dueDate": "YYYY-MM-DD"}}])
- "followUpInstructions": (Instructions for follow-up care or next steps)
- "discussionPoints": (List of main topics discussed)
- "questionsRaised": (List of significant questions asked during the meeting)
- "resolutionsReached": (List of how issues or questions were resolved)

Transcript:
---
{current_transcript}
---

Provide ONLY the JSON object in your response. Do not include any other text before or after the JSON.
"""
                response1 = model.generate_content(prompt_structured, request_options={"timeout": 600})
                # Robust JSON extraction: find content between ```json and ``` or just { and }
                json_text_match = re.search(r"```json\s*([\s\S]*?)\s*```|({[\s\S]*})", response1.text, re.DOTALL)

                if json_text_match:
                    json_str = json_text_match.group(1) or json_text_match.group(2)
                    try:
                        structured = json.loads(json_str.strip())
                        st.session_state["structured"] = structured
                    except json.JSONDecodeError as e:
                        st.error(f"❌ JSON found but failed to parse. Error: {e}")
                        st.error("Problematic JSON content received from Gemini:")
                        st.code(json_str.strip(), language="json")
                        # Optionally, try to get Gemini to fix it or use a fallback
                        st.session_state["structured"] = {"error": "Failed to parse structured summary from Gemini.", "raw_response": json_str.strip()}
                else:
                    st.error("❌ No valid JSON object found in Gemini's response for structured summary.")
                    st.info("Gemini's raw response for structured summary:")
                    st.code(response1.text)
                    st.session_state["structured"] = {"error": "No JSON object found in structured summary response.", "raw_response": response1.text}


                # --- Narrative Summary ---
                prompt_narrative = f"""
You are an AI assistant tasked with creating a professional meeting summary.
Based on the following transcript, write a coherent, narrative summary of the meeting.
The summary should be well-organized, easy to read, and capture the main points, discussions, and outcomes.
Maintain a formal and objective tone suitable for HSE meeting minutes.
Do not include speaker labels unless essential for context.

Transcript:
---
{current_transcript}
---

Narrative Summary:
"""
                response2 = model.generate_content(prompt_narrative, request_options={"timeout": 600})
                narrative = response2.text
                st.session_state["narrative"] = narrative

                # --- Brief Summary ---
                prompt_brief = f"""
You are an AI assistant for the HSE.
Summarise the key outcomes, decisions made, and critical action items from the following meeting transcript.
The summary should be very concise, ideally under 200 words, in a bullet-point or short paragraph format.
Focus strictly on actionable information and final decisions.

Transcript:
---
{current_transcript}
---

Brief HSE-Style Summary (Decisions & Actions):
"""
                response3 = model.generate_content(prompt_brief, request_options={"timeout": 600})
                brief_summary = response3.text
                st.session_state["brief"] = brief_summary

                st.success("All summaries generated successfully.")

            except Exception as e:
                st.error(f"An error occurred during summarization: {e}")
                # Clean up session state for summaries if an error occurs
                for key in ["structured", "narrative", "brief"]:
                    if key in st.session_state:
                        del st.session_state[key]

# --- DOCX Export Function ---
def create_docx(content, kind="structured"):
    """
    Creates a DOCX file from the provided content.
    'content' can be a dictionary (for structured) or string (for narrative/brief).
    'kind' specifies the type of summary to format the document accordingly.
    """
    doc = Document()
    doc.add_heading(f"MAI Recap - {datetime.now().strftime('%Y-%m-%d %H:%M')}", level=0) # Overall document title

    if kind == "structured":
        doc.add_heading("Health Service Executive (HSE) – Detailed Meeting Minutes", level=1)
        if isinstance(content, dict):
            for key, val in content.items():
                doc.add_heading(prettify_key(key), level=2)
                if isinstance(val, list):
                    if all(isinstance(item, dict) for item in val): # Handle list of dictionaries (e.g., actionItems)
                        for item_dict in val:
                            for sub_key, sub_val in item_dict.items():
                                doc.add_paragraph(f"{sub_key.title()}: {sub_val}", style='ListBullet')
                            doc.add_paragraph() # Add a small space between list items
                    else: # Handle list of strings or other primitives
                        for item in val:
                            doc.add_paragraph(str(item), style='ListBullet')
                elif isinstance(val, dict): # Handle nested dictionaries
                     for sub_key, sub_val in val.items():
                        doc.add_paragraph(f"{prettify_key(sub_key)} {sub_val}")
                else:
                    doc.add_paragraph(str(val) if val is not None else "Not mentioned")
        else:
            doc.add_paragraph("Error: Structured content is not in the expected format (dictionary).")
            doc.add_paragraph(str(content))

    elif kind == "brief":
        doc.add_heading("HSE Brief Summary – Key Decisions & Action Items", level=1)
        doc.add_paragraph(str(content))
    else: # Default to narrative
        doc.add_heading("Narrative Recap – HSE Meeting Summary", level=1)
        doc.add_paragraph(str(content))

    # Save to a BytesIO object to be used by st.download_button
    output = io.BytesIO()
    doc.save(output)
    output.seek(0) # Rewind the buffer to the beginning
    return output

# --- Display Summaries and Downloads ---
# Check if all summaries are available to avoid partial display issues
if "structured" in st.session_state and "narrative" in st.session_state and "brief" in st.session_state:
    st.markdown("---") # Separator
    st.markdown("## 📑 Summaries & Downloads")

    # --- Structured Summary Display ---
    st.markdown("### Detailed Structured Summary")
    structured_summary_data = st.session_state["structured"]
    if isinstance(structured_summary_data, dict) and "error" not in structured_summary_data:
        for k, v in structured_summary_data.items():
            st.markdown(f"**{prettify_key(k)}**")
            if isinstance(v, list):
                if all(isinstance(item, dict) for item in v): # e.g. action items
                    for item_dict in v:
                        with st.container(): # Group related items
                            for sub_key, sub_val in item_dict.items():
                                st.markdown(f"  - {sub_key.title()}: {sub_val}")
                            st.markdown("") # Small space
                else:
                    for item in v:
                        st.markdown(f"- {item}")
            elif isinstance(v, dict): # Nested dictionary
                 for sub_key, sub_val in v.items():
                    st.markdown(f"  - **{prettify_key(sub_key)}** {sub_val}")
            else:
                st.markdown(f"{v}")
            st.markdown("---") # Separator between fields

        st.download_button(
            label="📥 Download Structured Summary (DOCX)",
            data=create_docx(structured_summary_data, "structured"),
            file_name=f"HSE_Structured_Summary_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="download_structured_docx"
        )
    elif isinstance(structured_summary_data, dict) and "error" in structured_summary_data:
        st.error(f"Could not display structured summary: {structured_summary_data.get('error')}")
        st.info("Raw response for structured summary (if available):")
        st.code(structured_summary_data.get('raw_response', 'Not available'), language="text")
    else:
         st.warning("Structured summary is not in the expected format or is missing.")


    st.markdown("---")
    # --- Narrative Recap Display ---
    st.markdown("### 🧑‍⚕️ Narrative Recap")
    st.markdown(st.session_state["narrative"]) # Use markdown for better formatting if narrative contains it
    st.download_button(
        label="📥 Download Narrative Summary (DOCX)",
        data=create_docx(st.session_state["narrative"], "narrative"),
        file_name=f"HSE_Narrative_Summary_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="download_narrative_docx"
    )

    st.markdown("---")
    # --- Brief Summary Display ---
    st.markdown("### 🧾 Brief Summary (Decisions & Actions Only)")
    st.markdown(st.session_state["brief"]) # Use markdown for better formatting
    st.download_button(
        label="📥 Download Brief Summary (DOCX)",
        data=create_docx(st.session_state["brief"], "brief"),
        file_name=f"HSE_Brief_Summary_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="download_brief_docx"
    )

# --- Footer ---
st.markdown("---")
st.markdown(
    "**Disclaimer:** This implementation has been tested using sample data. "
    "Adjustments may be required to ensure optimal performance and accuracy with real-world clinical meeting audio. "
    "Always verify the accuracy of transcriptions and summaries."
)
st.markdown("Created by Dave Maher | For HSE internal use.")
