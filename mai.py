import streamlit as st import google.generativeai as genai import json import os from datetime import datetime from docx import Document import io import tempfile import re

--- Utility to prettify keys ---

def prettify_key(key): key = key.replace('_', ' ') key = re.sub(r'([a-z])([A-Z])', r'\1 \2', key) return key.title() + ":"

--- Configure Gemini API ---

genai.configure(api_key=st.secrets["GEMINI_API_KEY"]) model = genai.GenerativeModel(model_name='gemini-2.0-flash-exp')

st.set_page_config(page_title="MAI Recap", layout="wide")

--- Password protection ---

if "password_verified" not in st.session_state: st.session_state.password_verified = False

if not st.session_state.password_verified: user_password = st.text_input("Enter password to access MAI Recap:", type="password", key="password_input") submit_button = st.button("Submit", key="submit_pwd") if submit_button: password = st.secrets["password"] if user_password == password: st.session_state.password_verified = True st.rerun() else: st.warning("Incorrect password. Please try again.") st.stop()

--- Sidebar ---

with st.sidebar: st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=200) st.title("🩺 MAI Recap") if st.button("Created by Dave Maher"): st.sidebar.write("This application intellectual property belongs to Dave Maher.")

--- Main UI Header ---

col1, col2 = st.columns([1, 6]) with col1: st.image("https://www.ehealthireland.ie/media/k1app1wt/hse-logo-black-png.png", width=80) with col2: st.title("📝 MAI Recap") st.markdown("#### Health Service Executive (HSE) Minutes Generator")

st.markdown("### 📤 Upload or Record Meeting Audio")

--- Input Method Selection ---

mode = st.radio("Choose input method:", ["Upload audio file", "Record using microphone"])

audio_bytes = None audio_format = "audio/wav"

if mode == "Upload audio file": uploaded_audio = st.file_uploader("Upload an audio file (WAV, MP3, M4A)", type=["wav", "mp3", "m4a"]) if uploaded_audio: st.audio(uploaded_audio, format=audio_format) audio_bytes = uploaded_audio

elif mode == "Record using microphone": recorded_audio = st.audio_input("🎙️ Click the microphone to record, then click again to stop and process.") if recorded_audio: st.audio(recorded_audio, format=audio_format) audio_bytes = recorded_audio

--- Transcription and Analysis ---

if audio_bytes and st.button("🧠 Transcribe & Analyse"): with st.spinner("Processing with Gemini..."): if hasattr(audio_bytes, "read"): audio_bytes = audio_bytes.read()

with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
        tmp_file.write(audio_bytes)
        tmp_file_path = tmp_file.name

    try:
        audio_file = genai.upload_file(path=tmp_file_path)

        prompt = (
            "You are a transcriptionist. Transcribe the following meeting and label speakers clearly."
        )
        result = model.generate_content([prompt, audio_file], request_options={"timeout": 600})
        transcript = result.text
        genai.delete_file(audio_file.name)

        st.session_state["transcript"] = transcript
        st.success("Transcript generated successfully.")
    finally:
        os.remove(tmp_file_path)

--- Display Transcript ---

if "transcript" in st.session_state: st.markdown("## 📄 Transcript") st.text_area("Transcript", st.session_state["transcript"], height=300)

if st.button("📊 Summarise Transcript"):
    with st.spinner("Generating structured, narrative and brief summaries..."):

        # --- Structured Summary ---
        prompt_structured = f"""

You are a scribe for HSE meetings. Extract structured information from this transcript in JSON with:

patientName

dateOfVisit

chiefComplaint

historyPresentIllness

pastMedicalHistory

medications

allergies

reviewOfSystems

physicalExam

assessment

plan

followUp


If not mentioned, use "Not mentioned". Transcript: {st.session_state['transcript']} """ response1 = model.generate_content(prompt_structured) json_match = re.search(r"{.*}", response1.text, re.DOTALL) if json_match: try: structured = json.loads(json_match.group()) except json.JSONDecodeError as e: st.error("❌ JSON found but failed to parse. Check formatting.") st.code(json_match.group(), language="json") raise e else: st.error("❌ No valid JSON object found in Gemini's response.") st.code(response1.text) raise ValueError("No valid JSON found.")

# --- Narrative Summary ---
        prompt_narrative = f"""

Summarise the transcript into a coherent, professional meeting narrative summary. Transcript: {st.session_state['transcript']} """ response2 = model.generate_content(prompt_narrative) narrative = response2.text

# --- Brief Summary ---
        prompt_brief = f"""

Summarise the key outcomes from this meeting for a brief HSE-style summary. Focus on only decisions made and action items. Keep it under 200 words. Transcript: {st.session_state['transcript']} """ response3 = model.generate_content(prompt_brief) brief_summary = response3.text

st.session_state["structured"] = structured
        st.session_state["narrative"] = narrative
        st.session_state["brief"] = brief_summary
        st.success("All summaries generated.")

--- DOCX Export Function ---

def create_docx(content, kind="structured"): doc = Document() if kind == "structured": doc.add_heading("Health Service Executive (HSE) – Full Meeting Minutes", level=1) for key, val in content.items(): doc.add_heading(prettify_key(key), level=2) doc.add_paragraph(val) elif kind == "brief": doc.add_heading("HSE Brief Summary – Decisions & Actions", level=1) doc.add_paragraph(content) else: doc.add_heading("Narrative Recap – HSE Meeting", level=1) doc.add_paragraph(content) output = io.BytesIO() doc.save(output) output.seek(0) return output

--- Display Summaries and Downloads ---

if "structured" in st.session_state and "narrative" in st.session_state: st.markdown("## 📑 Structured Summary") for k, v in st.session_state["structured"].items(): st.markdown(f"{prettify_key(k)} {v}")

st.download_button("📥 Download Structured Summary (DOCX)",
    data=create_docx(st.session_state["structured"], "structured"),
    file_name="structured_summary.docx",
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

st.markdown("---")
st.markdown("## 🧑‍⚕️ Narrative Recap")
st.write(st.session_state["narrative"])

st.download_button("📥 Download Narrative Summary (DOCX)",
    data=create_docx(st.session_state["narrative"], "narrative"),
    file_name="narrative_summary.docx",
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

st.markdown("---")
st.markdown("## 🧾 Brief Summary (Decisions & Actions Only)")
st.write(st.session_state["brief"])

st.download_button("📥 Download Brief Summary (DOCX)",
    data=create_docx(st.session_state["brief"], "brief"),
    file_name="HSE_brief_summary.docx",
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

--- Footer ---

st.markdown("---") st.markdown("This implementation has been tested using test data. Adjustments may be required to ensure optimal performance with real-world data.") st.markdown("Created by Dave Maher")
