"""FastAPI backend application for the Scheme Eligibility Chatbot.

Defines the API endpoints, sets up CORS, and manages in-memory sessions.
Includes voice + multilingual support via /voice-query.
"""

import os
import uuid
import tempfile
import time
from collections import defaultdict
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from models import ChatSession, UserProfile, EligibleScheme
from agent import run_agent
from tools.voice_assistant import speech_to_text, translate_text, text_to_speech

# Load environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# In-Memory Rate Limiter
# ---------------------------------------------------------------------------
class InMemoryRateLimiter:
    def __init__(self, limit: int = 20, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        # Key: identifier, Value: list of request timestamps
        self.requests = defaultdict(list)

    def is_rate_limited(self, identifier: str) -> bool:
        current_time = time.time()
        # Clean up timestamps older than the rate limiting window
        self.requests[identifier] = [
            t for t in self.requests[identifier]
            if current_time - t < self.window_seconds
        ]
        if len(self.requests[identifier]) >= self.limit:
            return True
        self.requests[identifier].append(current_time)
        return False

_rate_limiter = InMemoryRateLimiter(limit=20, window_seconds=60)

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
# Load allowed origins from the environment variable (comma-separated), fallback to localhost:3000
cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
allow_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-Memory Session Storage
# ---------------------------------------------------------------------------
# Key: session_id, Value: ChatSession
_sessions: Dict[str, ChatSession] = {}

# Tracks eligible schemes found across the entire session lifetime
# Key: session_id, Value: list of EligibleScheme (deduplicated by name)
_session_eligible: Dict[str, List[EligibleScheme]] = {}


# ---------------------------------------------------------------------------
# Request and Response Models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    """Payload format for sending a new message to the chat endpoint."""
    session_id: Optional[str] = None
    message: str
    language: Optional[str] = None  # ISO 639-1 code, e.g. "hi", "te"


class ChatResponse(BaseModel):
    """Response payload containing response text, extracted profile, and audit logs."""
    session_id: str
    response: str
    profile: UserProfile
    tools_used: List[dict]
    eligible_schemes: List[EligibleScheme] = []


class SessionSummaryResponse(BaseModel):
    """Aggregated dashboard data for a session."""
    total_checked: int
    eligible_count: int
    needs_more_info_count: int
    eligible_schemes: List[EligibleScheme]
    missing_fields: List[str]
    category_breakdown: dict  # {category_name: count}


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
async def chat_endpoint(payload: ChatRequest, request: Request):
    """Processes a chat message within a session.

    Retrieves the existing session or creates a new one, updates state,
    runs the LLM reasoning agent loop, and returns the response details.
    """
    # Rate Limiting: 20 requests per minute
    client_ip = request.client.host if request.client else "unknown"
    rate_limit_key = client_ip  # IP-based: session_id is client-forgeable
    if _rate_limiter.is_rate_limited(rate_limit_key):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment before sending another message."
        )

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

    # Keep the session language in sync with the frontend's selection so the
    # agent can translate its responses (agent skips translation for "en"/None).
    if payload.language:
        session.language = payload.language.strip().lower()

    # 2. Run the agentic reasoning loop
    try:
        response_text, tools_used, eligible_schemes = run_agent(session, user_message)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution encountered an error: {str(e)}"
        )

    # 3. Merge new eligible schemes into session-level history (deduplicate by name)
    _merge_eligible(session.session_id, eligible_schemes)

    # 4. Return the response, updated profile, and tool logs
    return ChatResponse(
        session_id=session.session_id,
        response=response_text,
        profile=session.profile,
        tools_used=tools_used,
        eligible_schemes=_coerce_schemes(eligible_schemes),
    )


@app.get("/session/{session_id}", response_model=ChatSession)
async def get_session_endpoint(session_id: str):
    """Utility endpoint to retrieve the current state of a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    return _sessions[session_id]


# ---------------------------------------------------------------------------
# Category mapping for dashboard breakdown chart
# ---------------------------------------------------------------------------
_SCHEME_CATEGORIES: Dict[str, str] = {
    # Income / Financial Support
    "PM-KISAN": "Income Support",
    "PMAY-G": "Housing",
    "PMAY-U": "Housing",
    "PM Ujjwala Yojana": "Energy & Fuel",
    "PM Jan Dhan Yojana": "Financial Inclusion",
    "Sukanya Samriddhi Yojana": "Savings & Investment",
    "Atal Pension Yojana": "Pension",
    "PM Vaya Vandana Yojana": "Pension",
    "Old Age Pension Scheme": "Pension",
    "Widow Pension Scheme": "Pension",
    "PMJJBY": "Insurance",
    "PMSBY": "Insurance",
    "Fasal Bima Yojana": "Insurance",
    "Rashtriya Swasthya Bima Yojana": "Insurance",
    "PM Ayushman Bharat": "Healthcare",
    "Janani Suraksha Yojana": "Healthcare",
    "Mid Day Meal Scheme": "Education",
    "PM Scholarship Scheme": "Education",
    "MGNREGA": "Employment",
    "PM Rozgar Protsahan Yojana": "Employment",
    "Kisan Credit Card": "Credit & Loans",
    "Mudra Loan": "Credit & Loans",
    "Stand-Up India": "Credit & Loans",
}


def _get_category(scheme_name: str) -> str:
    """Return the display category for a scheme name, defaulting to 'Other'."""
    for key, cat in _SCHEME_CATEGORIES.items():
        if key.lower() in scheme_name.lower():
            return cat
    return "Other"


def _coerce_schemes(schemes) -> List[EligibleScheme]:
    """Convert a mixed list of dicts / EligibleScheme objects into EligibleScheme objects.

    run_agent returns plain dicts; other code paths may already hold model
    objects. Malformed entries are skipped rather than crashing the request.
    """
    coerced: List[EligibleScheme] = []
    for scheme in schemes or []:
        if isinstance(scheme, EligibleScheme):
            coerced.append(scheme)
        elif isinstance(scheme, dict):
            try:
                coerced.append(EligibleScheme(**scheme))
            except Exception:
                continue
    return coerced


def _merge_eligible(session_id: str, new_schemes) -> None:
    """Merge newly found eligible schemes into the session-level store (dedup by name).

    Accepts both plain dicts (as returned by run_agent) and EligibleScheme objects.
    """
    existing = _session_eligible.setdefault(session_id, [])
    existing_names = {s.name.lower() for s in existing}
    for scheme in _coerce_schemes(new_schemes):
        if scheme.name.lower() not in existing_names:
            existing.append(scheme)
            existing_names.add(scheme.name.lower())


@app.get("/session/{session_id}/summary", response_model=SessionSummaryResponse)
async def get_session_summary(session_id: str):
    """Returns aggregated dashboard data for a session.

    Computes dynamically on each call:
    - Total schemes checked (all schemes in schemes.json)
    - How many are eligible vs. needing more info (based on the current profile)
    - Which profile fields are still missing
    - A category breakdown of eligible schemes

    Schemes found eligible by the live re-check are merged into the
    session's eligible list, so the stat card count and the scheme cards
    below it always agree.
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = _sessions[session_id]
    profile_dict = {
        k: v for k, v in session.profile.model_dump().items() if v is not None
    }

    # Run check_eligibility against all schemes to get aggregate counts
    from tools.eligibility import check_eligibility, _load_schemes, get_missing_fields_for_profile
    all_schemes = _load_schemes()
    total_checked = len(all_schemes)
    needs_more_info_count = 0

    live_eligible: List[EligibleScheme] = []
    for scheme in all_schemes:
        result = check_eligibility(profile_dict, scheme["scheme_id"])
        verdict = result.get("eligible")
        if verdict is True:
            live_eligible.append(EligibleScheme(
                name=scheme.get("name", scheme["scheme_id"]),
                benefit_amount=scheme.get("benefits", ""),
                reason=result.get("reason", "Your profile meets the eligibility criteria."),
                documents_needed=scheme.get("documents_needed", []),
                apply_link=scheme.get("apply_link", ""),
            ))
        elif verdict == "needs_more_info" or verdict is None:
            # Only count genuine "more info needed" — NOT outright ineligible schemes.
            needs_more_info_count += 1

    # Merge live-detected eligible schemes into the session store so the
    # count and the cards stay consistent.
    _merge_eligible(session_id, live_eligible)

    accumulated = _session_eligible.get(session_id, [])
    eligible_count = len(accumulated)

    # Build category breakdown
    breakdown: Dict[str, int] = {}
    for s in accumulated:
        cat = _get_category(s.name)
        breakdown[cat] = breakdown.get(cat, 0) + 1

    # Missing profile fields — use dynamic computation based on intent
    intent_tags = getattr(session, 'last_detected_intent', None) or None
    missing_fields = get_missing_fields_for_profile(
        session.profile.model_dump(), intent_tags=intent_tags
    )

    return SessionSummaryResponse(
        total_checked=total_checked,
        eligible_count=eligible_count,
        needs_more_info_count=needs_more_info_count,
        eligible_schemes=accumulated,
        missing_fields=missing_fields,
        category_breakdown=breakdown,
    )


# ---------------------------------------------------------------------------
# Voice + Multilingual Endpoint
# ---------------------------------------------------------------------------
@app.post("/voice-query", response_model=VoiceQueryResponse)
async def voice_query_endpoint(
    request: Request,
    audio: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
):
    """Accepts an audio file, transcribes, translates, queries the agent,
    translates back, generates TTS, and returns text + audio URL.

    Accepts an optional 'language' code (e.g. 'te' for Telugu, 'hi' for Hindi).
    If not provided, falls back to automatic language detection."""

    # Rate Limiting: 20 requests per minute
    client_ip = request.client.host if request.client else "unknown"
    rate_limit_key = client_ip  # IP-based: session_id is client-forgeable
    if _rate_limiter.is_rate_limited(rate_limit_key):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment before sending another voice query."
        )

    # ------------------------------------------------------------------
    # 1. Save the uploaded audio to a temporary file
    # ------------------------------------------------------------------
    suffix = os.path.splitext(audio.filename or "upload.wav")[1] or ".wav"
    try:
        # Use the system temp dir — NOT the publicly served static/audio folder
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
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
    confidence = stt_result.get("confidence_score", 0)

    # Diagnostic log — shows exactly what Whisper heard and how confident it
    # was, so real accuracy problems can be told apart from threshold issues.
    print(f"[STT] lang={detected_lang} confidence={confidence} text={transcribed_text[:160]!r}")

    # ── Low-confidence gate (language-aware, two-tier) ────────────────
    # Whisper's confidence runs systematically lower for Indic languages even
    # on correct transcriptions, so English keeps the strict threshold while
    # other languages get a more forgiving one. Below the hard floor the
    # transcription is near-certain garbage regardless of language.
    _HARD_FLOOR = 0.22
    _STRICT_THRESHOLD = 0.45   # English
    _RELAXED_THRESHOLD = 0.30  # Indic languages
    threshold = _STRICT_THRESHOLD if detected_lang == "en" else _RELAXED_THRESHOLD

    if confidence < _HARD_FLOOR or (stt_result.get("low_confidence") and confidence < threshold):
        raise HTTPException(
            status_code=422,
            detail=(
                f"I couldn't hear that clearly (confidence {confidence}). "
                "Please try again in a quiet place, speaking slowly and close to the microphone."
            ),
        )

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
        # The voice pipeline does its own translation below, so ask the agent
        # for the plain English response here.
        agent_response, tools_used, eligible_schemes = run_agent(
            session, english_query, apply_language_translation=False
        )
        _merge_eligible(session.session_id, eligible_schemes)
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
        eligible_schemes=_coerce_schemes(eligible_schemes),
    )


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Directly serve a generated audio file by name."""
    # Reject anything that isn't a bare filename (path traversal hardening)
    if os.path.basename(filename) != filename or ".." in filename:
        raise HTTPException(status_code=404, detail="Audio file not found.")
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