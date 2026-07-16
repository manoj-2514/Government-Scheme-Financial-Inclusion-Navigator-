"""FastAPI backend application for the Scheme Eligibility Chatbot.

Defines the API endpoints, sets up CORS, and manages in-memory sessions.
Includes voice + multilingual support via /voice-query.
"""

import os
import uuid
import tempfile
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from models import ChatSession, UserProfile, EligibleScheme
from agent import run_agent
from tools.voice_assistant import speech_to_text, translate_text, text_to_speech

app = FastAPI(
    title="Government Scheme Eligibility Assistant API",
    description="Backend API for interacting with the scheme eligibility bot.",
    version="1.1.0",
)

# ---------------------------------------------------------------------------
# Static Files – serve generated audio responses
# ---------------------------------------------------------------------------
_AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "audio")
os.makedirs(_AUDIO_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# ---------------------------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------------------------
# Enable CORS for the local React/Next.js frontend development environment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-Memory Session Storage
# ---------------------------------------------------------------------------
# Key: session_id, Value: ChatSession
_sessions: Dict[str, ChatSession] = {}


# ---------------------------------------------------------------------------
# Request and Response Models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    """Payload format for sending a new message to the chat endpoint."""
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    """Response payload containing response text, extracted profile, and audit logs."""
    session_id: str
    response: str
    profile: UserProfile
    tools_used: List[dict]
    eligible_schemes: List[EligibleScheme] = []


class VoiceQueryResponse(BaseModel):
    """Response payload for the /voice-query endpoint."""
    session_id: str
    detected_language: str
    transcribed_text: str
    translated_query: str
    agent_response_english: str
    translated_response: str
    audio_url: str
    profile: UserProfile
    tools_used: List[dict]
    eligible_schemes: List[EligibleScheme] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    """Verify that the API is running and accessible."""
    return {
        "status": "online",
        "message": "Government Scheme Eligibility Assistant API is up and running. Visit /docs for the interactive UI."
    }


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest):
    """Processes a chat message within a session.

    Retrieves the existing session or creates a new one, updates state,
    runs the LLM reasoning agent loop, and returns the response details.
    """
    session_id = payload.session_id
    user_message = payload.message.strip()

    if not user_message:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")

    # 1. Retrieve or initialize the session state
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
    else:
        session = ChatSession()
        # If the user passed a session_id that isn't in memory, override the generated one
        if session_id:
            session.session_id = session_id
        _sessions[session.session_id] = session

    # 2. Run the agentic reasoning loop
    try:
        response_text, tools_used, eligible_schemes = run_agent(session, user_message)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution encountered an error: {str(e)}"
        )

    # 3. Return the response, updated profile, and tool logs
    return ChatResponse(
        session_id=session.session_id,
        response=response_text,
        profile=session.profile,
        tools_used=tools_used,
        eligible_schemes=eligible_schemes,
    )


@app.get("/session/{session_id}", response_model=ChatSession)
async def get_session_endpoint(session_id: str):
    """Utility endpoint to retrieve the current state of a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    return _sessions[session_id]


# ---------------------------------------------------------------------------
# Voice + Multilingual Endpoint
# ---------------------------------------------------------------------------
@app.post("/voice-query", response_model=VoiceQueryResponse)
async def voice_query_endpoint(
    audio: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
):
    """Accepts an audio file, transcribes, translates, queries the agent,
    translates back, generates TTS, and returns text + audio URL.

    Accepts an optional 'language' code (e.g. 'te' for Telugu, 'hi' for Hindi).
    If not provided, falls back to automatic language detection."""

    # ------------------------------------------------------------------
    # 1. Save the uploaded audio to a temporary file
    # ------------------------------------------------------------------
    suffix = os.path.splitext(audio.filename or "upload.wav")[1] or ".wav"
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=_AUDIO_DIR)
        contents = await audio.read()
        tmp.write(contents)
        tmp.close()
        tmp_audio_path = tmp.name
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded audio: {e}")

    # ------------------------------------------------------------------
    # 2. Speech-to-Text via Whisper
    # ------------------------------------------------------------------
    try:
        stt_result = speech_to_text(tmp_audio_path, language=language)
    except RuntimeError as e:
        # ffmpeg missing or similar system error
        _cleanup(tmp_audio_path)
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        # empty / unreadable transcription
        _cleanup(tmp_audio_path)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        _cleanup(tmp_audio_path)
        raise HTTPException(status_code=500, detail=f"Speech-to-text failed: {e}")
    finally:
        # Remove the temporary upload once Whisper is done
        _cleanup(tmp_audio_path)

    transcribed_text = stt_result["text"]
    detected_lang = stt_result["detected_language"]  # e.g. "hi", "en", "ta"

    # ------------------------------------------------------------------
    # 3. Translate to English if needed
    # ------------------------------------------------------------------
    if detected_lang == "en":
        english_query = transcribed_text
    else:
        try:
            english_query = translate_text(transcribed_text, detected_lang, "en")
        except RuntimeError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # ------------------------------------------------------------------
    # 4. Run the existing agent with the English query
    # ------------------------------------------------------------------
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
    else:
        session = ChatSession()
        if session_id:
            session.session_id = session_id
        _sessions[session.session_id] = session

    try:
        agent_response, tools_used, eligible_schemes = run_agent(session, english_query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    # ------------------------------------------------------------------
    # 5. Translate agent response back to user's language
    # ------------------------------------------------------------------
    if detected_lang == "en":
        translated_response = agent_response
    else:
        try:
            translated_response = translate_text(agent_response, "en", detected_lang)
        except RuntimeError as e:
            # Fall back to English if translation fails
            translated_response = agent_response

    # ------------------------------------------------------------------
    # 6. Text-to-Speech on the translated response
    # ------------------------------------------------------------------
    audio_filename = f"{uuid.uuid4().hex}.mp3"
    audio_out_path = os.path.join(_AUDIO_DIR, audio_filename)
    try:
        text_to_speech(translated_response, detected_lang, audio_out_path)
    except RuntimeError:
        # If TTS fails for the detected language, try English
        try:
            text_to_speech(agent_response, "en", audio_out_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Text-to-speech failed: {e}")

    audio_url = f"/static/audio/{audio_filename}"

    return VoiceQueryResponse(
        session_id=session.session_id,
        detected_language=detected_lang,
        transcribed_text=transcribed_text,
        translated_query=english_query,
        agent_response_english=agent_response,
        translated_response=translated_response,
        audio_url=audio_url,
        profile=session.profile,
        tools_used=tools_used,
        eligible_schemes=eligible_schemes,
    )


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Directly serve a generated audio file by name."""
    filepath = os.path.join(_AUDIO_DIR, filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Audio file not found.")
    return FileResponse(filepath, media_type="audio/mpeg", filename=filename)


def _cleanup(path: str):
    """Silently remove a temporary file if it exists."""
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
