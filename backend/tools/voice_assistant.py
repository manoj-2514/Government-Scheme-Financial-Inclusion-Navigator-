import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Tuple

from deep_translator import GoogleTranslator
from gtts import gTTS
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

logger = logging.getLogger(__name__)

# Minimum audio duration (in seconds) after silence trimming.
# Clips shorter than this are almost certainly noise, clicks, or accidental taps.
_MIN_DURATION_SEC = 1.0

# Global cache for the Whisper model object
_cached_whisper_model = None


def get_whisper_model():
    """Retrieve or load the Whisper model from memory cache."""
    global _cached_whisper_model
    if _cached_whisper_model is None:
        import whisper
        logger.info("Whisper model cache miss. Loading Whisper 'small' model...")
        t0 = time.time()
        _cached_whisper_model = whisper.load_model("small")
        t1 = time.time()
        print(f"[TIMING] Loaded Whisper model: {t1 - t0:.2f}s")
    return _cached_whisper_model


# ---------------------------------------------------------------------------
# Groq-hosted Whisper (primary STT)
# ---------------------------------------------------------------------------
# whisper-large-v3 on Groq hardware: far more accurate for Indic languages
# than the local 'small' model, and transcribes in seconds instead of minutes.
# Uses the same GROQ_API_KEY(_2, _3...) env vars as the chat agent; audio
# quota is separate from chat-token quota. Local Whisper remains the
# offline fallback if Groq is unreachable.

_GROQ_STT_MODEL = "whisper-large-v3"
_groq_stt_clients = None

_LANG_NAME_TO_CODE = {
    "english": "en", "hindi": "hi", "telugu": "te", "tamil": "ta",
    "kannada": "kn", "malayalam": "ml", "marathi": "mr",
}


def _get_groq_stt_clients():
    global _groq_stt_clients
    if _groq_stt_clients is None:
        try:
            from groq import Groq
        except ImportError:
            _groq_stt_clients = []
            return _groq_stt_clients
        keys = [
            v for k, v in sorted(os.environ.items())
            if k.startswith("GROQ_API_KEY") and v
        ]
        _groq_stt_clients = [Groq(api_key=key) for key in keys]
    return _groq_stt_clients


def _transcribe_with_groq(audio_path: str, language: str = None) -> dict:
    """Transcribe via Groq's hosted whisper-large-v3. Raises on failure so the
    caller can fall back to local Whisper."""
    clients = _get_groq_stt_clients()
    if not clients:
        raise RuntimeError("No Groq API keys configured")

    with open(audio_path, "rb") as fh:
        audio_bytes = fh.read()

    last_exc = None
    for client in clients:
        try:
            kwargs = {
                "file": (os.path.basename(audio_path), audio_bytes),
                "model": _GROQ_STT_MODEL,
                "response_format": "verbose_json",
            }
            if language:
                kwargs["language"] = language.strip().lower()
            tr = client.audio.transcriptions.create(**kwargs)

            text = (getattr(tr, "text", "") or "").strip()
            detected = getattr(tr, "language", None) or language or "en"
            detected = _LANG_NAME_TO_CODE.get(
                str(detected).strip().lower(), str(detected).strip().lower()
            )

            # Adapt Groq's segment objects for the shared confidence scorer
            segments = getattr(tr, "segments", None) or []
            seg_dicts = []
            for s in segments:
                if isinstance(s, dict):
                    seg_dicts.append(s)
                else:
                    seg_dicts.append({
                        "avg_logprob": getattr(s, "avg_logprob", 0.0),
                        "no_speech_prob": getattr(s, "no_speech_prob", 0.0),
                    })
            if seg_dicts:
                low_confidence, score = _compute_confidence({"segments": seg_dicts})
            else:
                low_confidence, score = False, 0.9

            return {
                "text": text,
                "detected_language": detected,
                "low_confidence": low_confidence,
                "confidence_score": round(score, 3),
            }
        except Exception as exc:
            last_exc = exc
            continue

    raise last_exc if last_exc else RuntimeError("Groq STT failed")


# Supported languages with their native-script display names for reference by the frontend
SUPPORTED_LANGUAGES = {
    "hi": "हिन्दी",
    "te": "తెలుగు",
    "ta": "தமிழ்",
    "kn": "ಕನ್ನಡ",
    "ml": "മലയാളം",
    "mr": "मराठी",
    "en": "English",
}


def _check_ffmpeg():
    """Verify that ffmpeg is installed and available in the system PATH."""
    try:
        # Attempt to run ffmpeg with no args or -version
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg utility is not installed or not found in the system PATH. "
            "To use voice features on Windows: "
            "1. Download the ffmpeg builds (e.g., from https://ffmpeg.org/ or gyan.dev)\n"
            "2. Extract the folder and copy the path to the 'bin/' directory\n"
            "3. Add this 'bin/' directory to your Windows System environment variable PATH.\n"
            "After doing this, restart your terminal/IDE for the path to take effect."
        ) from None


# ---------------------------------------------------------------------------
# Audio preprocessing helpers
# ---------------------------------------------------------------------------

def _preprocess_audio(audio_file_path: str) -> Tuple[str, float, int]:
    """Trim silence, validate duration, and log diagnostics.

    Returns
    -------
    tuple[str, float, int]
        ``(processed_path, duration_sec, sample_rate)``
        *processed_path* may differ from *audio_file_path* if silence was
        trimmed (a temp WAV is created).  The caller should clean it up.

    Raises
    ------
    ValueError
        If the audio is shorter than ``_MIN_DURATION_SEC`` after trimming.
    """
    t_start = time.time()
    try:
        audio = AudioSegment.from_file(audio_file_path)
    except Exception as exc:
        logger.warning("pydub could not load audio (%s) — skipping preprocessing: %s", audio_file_path, exc)
        print(f"[TIMING] Silence trim (failed): {time.time() - t_start:.2f}s")
        return audio_file_path, 0.0, 0

    raw_duration_sec = len(audio) / 1000.0
    sample_rate = audio.frame_rate
    logger.info(
        "Audio pre-processing — raw file: %s | duration: %.2fs | sample_rate: %dHz | channels: %d",
        audio_file_path, raw_duration_sec, sample_rate, audio.channels,
    )

    # ── Silence trimming ──────────────────────────────────────────────
    # detect_leading_silence returns ms of silence at the start;
    # we apply it to both the start and the reversed audio (= trailing).
    silence_thresh_dbfs = audio.dBFS - 16  # 16 dB below average loudness
    leading_ms = detect_leading_silence(audio, silence_threshold=silence_thresh_dbfs, chunk_size=10)
    trailing_ms = detect_leading_silence(audio.reverse(), silence_threshold=silence_thresh_dbfs, chunk_size=10)

    # Keep a small 100 ms pad so Whisper doesn't get a hard cut
    start = max(0, leading_ms - 100)
    end = max(start + 1, len(audio) - trailing_ms + 100)
    trimmed = audio[start:end]

    trimmed_duration_sec = len(trimmed) / 1000.0
    logger.info(
        "Audio pre-processing — trimmed silence: leading=%dms trailing=%dms | "
        "trimmed duration: %.2fs (was %.2fs)",
        leading_ms, trailing_ms, trimmed_duration_sec, raw_duration_sec,
    )

    print(f"[TIMING] Silence trim: {time.time() - t_start:.2f}s")

    # ── Minimum duration check ────────────────────────────────────────
    if trimmed_duration_sec < _MIN_DURATION_SEC:
        raise ValueError(
            f"Audio is too short after removing silence "
            f"({trimmed_duration_sec:.1f}s < {_MIN_DURATION_SEC}s minimum). "
            f"Please speak for at least one second."
        )

    # ── Export trimmed audio to a temp WAV for Whisper ─────────────────
    if leading_ms > 200 or trailing_ms > 200:
        # Only re-export if we actually trimmed a meaningful amount
        tmp_dir = os.path.dirname(audio_file_path)
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".wav", dir=tmp_dir,
        )
        trimmed.export(tmp.name, format="wav")
        tmp.close()
        logger.info("Audio pre-processing — exported trimmed WAV to: %s", tmp.name)
        return tmp.name, trimmed_duration_sec, sample_rate

    return audio_file_path, raw_duration_sec, sample_rate


def _has_consecutive_repetition(text: str, max_repeats: int = 3) -> bool:
    """Detect if the same word or short phrase is repeated consecutively too many times."""
    words = text.strip().split()
    n = len(words)
    if n < (max_repeats + 1):
        return False

    # Check for consecutive repetition of patterns of length k (1 to 10 words)
    for k in range(1, min(10, n // (max_repeats + 1) + 1)):
        for i in range(n - k * (max_repeats + 1) + 1):
            pattern = words[i : i + k]
            is_repeating = True
            for r in range(1, max_repeats + 1):
                compare = words[i + r * k : i + (r + 1) * k]
                if compare != pattern:
                    is_repeating = False
                    break
            if is_repeating:
                return True
    return False


def speech_to_text(audio_file_path: str, language: str = None) -> dict:
    """Transcribe an audio file using local OpenAI Whisper (small model).

    Pipeline:
    1. **Preprocess** — trim leading/trailing silence, reject clips < 1 s,
       log duration & sample rate for debugging.
    2. **Transcribe** — pass the cleaned audio to Whisper.
    3. **Cross-verify** (auto-detect only) — compare Whisper's language
       guess against GoogleTranslator and re-transcribe if they disagree.
    4. **Confidence check** — score transcription quality from segment data.

    If 'language' is explicitly provided, skips detection entirely — this
    significantly improves accuracy for ALL supported languages since Whisper
    doesn't have to guess.

    Returns
    -------
    dict
        ``text``              – transcribed string
        ``detected_language`` – ISO 639-1 code
        ``low_confidence``    – True when transcription quality is suspect
        ``confidence_score``  – float 0-1, higher is better
    """
    _check_ffmpeg()

    if not os.path.exists(audio_file_path):
        raise FileNotFoundError(f"Audio file not found at: {audio_file_path}")

    # ── Preprocess: trim silence, check duration, log diagnostics ─────
    processed_path, duration_sec, sample_rate = _preprocess_audio(audio_file_path)
    # Track whether we created a temp file that needs cleanup
    _temp_processed = processed_path != audio_file_path

    try:
        # ── Attempt 1: Groq-hosted Whisper large-v3 (fast, strong Indic support) ──
        groq_result = None
        try:
            t0 = time.time()
            groq_result = _transcribe_with_groq(processed_path, language)
            print(f"[TIMING] Groq Whisper transcription: {time.time() - t0:.2f}s")
        except Exception as exc:
            print(f"[STT] Groq transcription unavailable ({exc}) — falling back to local Whisper.")

        if groq_result is not None:
            gtext = groq_result["text"]
            if gtext and len(gtext) >= 2 and not _has_consecutive_repetition(gtext, max_repeats=3):
                return groq_result
            print("[STT] Groq returned empty/repetitive text — trying local Whisper.")

        # ── Attempt 2: local Whisper (offline fallback) ──
        model = get_whisper_model()
        t_trans_start = time.time()
        if language:
            # User explicitly specified language — transcribe directly (no guessing)
            forced_lang = language.strip().lower()
            result = model.transcribe(processed_path, language=forced_lang)
            text = result.get("text", "").strip()
            detected_lang = forced_lang
            print(f"[TIMING] Whisper transcription: {time.time() - t_trans_start:.2f}s")
        else:
            # Step 1: Let Whisper auto-detect and transcribe
            result = model.transcribe(processed_path)
            text = result.get("text", "").strip()
            whisper_lang = result.get("language", "en")
            print(f"[TIMING] Whisper transcription (detecting): {time.time() - t_trans_start:.2f}s")

            # Step 2: Cross-verify with GoogleTranslator's auto-detect
            # This catches cases where Whisper confuses similar languages
            # (e.g., Telugu detected as Hindi)
            if text and len(text) > 5:
                try:
                    t_cross_start = time.time()
                    detected_obj = GoogleTranslator(source="auto", target="en")
                    detected_obj.translate(text)  # triggers detection
                    translator_lang = detected_obj.source  # detected source lang
                    print(f"[TIMING] Cross-verify auto-detect: {time.time() - t_cross_start:.2f}s")
                    if translator_lang and translator_lang != whisper_lang:
                        # Translator disagrees — re-transcribe with corrected language
                        t_retrans_start = time.time()
                        result2 = model.transcribe(processed_path, language=translator_lang)
                        text2 = result2.get("text", "").strip()
                        print(f"[TIMING] Whisper re-transcription: {time.time() - t_retrans_start:.2f}s")
                        if text2 and len(text2) >= len(text) // 2:
                            text = text2
                            whisper_lang = translator_lang
                            result = result2  # use updated segments for confidence
                except Exception:
                    pass  # If cross-check fails, stick with Whisper's detection

            detected_lang = whisper_lang

        if not text or len(text) < 2:
            raise ValueError(
                "Whisper returned empty or unreadable transcription. "
                "Please speak more clearly or check your microphone input."
            )

        if _has_consecutive_repetition(text, max_repeats=3):
            logger.warning("Repetition loop hallucination detected in Whisper output: %r", text)
            raise ValueError(
                "Transcription failed: repetition loop detected. "
                "Please try speaking again in a quieter environment."
            )

        # ------------------------------------------------------------------
        # Confidence / quality check using Whisper's segment data
        # ------------------------------------------------------------------
        low_confidence, confidence_score = _compute_confidence(result)

        return {
            "text": text,
            "detected_language": detected_lang,
            "low_confidence": low_confidence,
            "confidence_score": round(confidence_score, 3),
        }
    finally:
        # Clean up the preprocessed audio file if it is a temporary one
        if _temp_processed and os.path.exists(processed_path):
            try:
                os.unlink(processed_path)
                logger.info("Audio pre-processing — cleaned up temporary trimmed WAV: %s", processed_path)
            except OSError as exc:
                logger.warning("Could not delete temporary WAV %s: %s", processed_path, exc)


# Thresholds for confidence scoring
_AVG_LOGPROB_THRESHOLD = -1.0   # segments worse than this are suspect
_NO_SPEECH_PROB_THRESHOLD = 0.6  # segments above this are likely silence/noise


def _compute_confidence(whisper_result: dict) -> tuple:
    """Analyse Whisper segment data and return (low_confidence, score).

    ``score`` is a float in [0, 1] where 1 = very confident.
    ``low_confidence`` is True when the score falls below 0.45.
    """
    segments = whisper_result.get("segments", [])
    if not segments:
        return True, 0.0

    total_logprob = 0.0
    total_no_speech = 0.0
    count = 0

    for seg in segments:
        avg_lp = seg.get("avg_logprob", 0.0)
        nsp = seg.get("no_speech_prob", 0.0)
        total_logprob += avg_lp
        total_no_speech += nsp
        count += 1

    mean_logprob = total_logprob / count
    mean_no_speech = total_no_speech / count

    # Convert avg_logprob to a 0-1 scale.
    # Typical good values are -0.2 to -0.5; terrible values are < -1.5.
    # We map: 0.0 -> 1.0, -1.0 -> 0.5, -2.0 -> 0.0  (clamped)
    logprob_score = max(0.0, min(1.0, 1.0 + mean_logprob / 2.0))

    # no_speech_prob: 0 = definitely speech, 1 = definitely not speech
    speech_score = 1.0 - mean_no_speech

    # Weighted combination (logprob is more informative)
    confidence_score = 0.7 * logprob_score + 0.3 * speech_score

    low_confidence = (
        confidence_score < 0.45
        or mean_logprob < _AVG_LOGPROB_THRESHOLD
        or mean_no_speech > _NO_SPEECH_PROB_THRESHOLD
    )

    return low_confidence, confidence_score


def translate_text(text: str, source_language: str, target_language: str) -> str:
    """Translate text between two languages using GoogleTranslator."""
    if not text.strip():
        return ""

    src = source_language.strip().lower()
    tgt = target_language.strip().lower()

    if src == tgt:
        return text

    t_start = time.time()
    try:
        translator = GoogleTranslator(source=src, target=tgt)
        res = translator.translate(text)
        print(f"[TIMING] Translation ({src} -> {tgt}): {time.time() - t_start:.2f}s")
        return res
    except Exception as exc:
        print(f"[TIMING] Translation ({src} -> {tgt}) failed: {time.time() - t_start:.2f}s")
        raise RuntimeError(
            f"Failed to translate text from '{source_language}' to '{target_language}': {exc}"
        ) from exc


def text_to_speech(text: str, target_language: str, output_path: str) -> str:
    """Convert text to speech audio in target language using gTTS and save as MP3."""
    if not text.strip():
        raise ValueError("Cannot convert empty text to speech.")

    lang_code = target_language.strip().lower()

    t_start = time.time()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        tts = gTTS(text=text, lang=lang_code, slow=False)
        tts.save(output_path)
        print(f"[TIMING] Text-to-speech generation ({lang_code}): {time.time() - t_start:.2f}s")
    except Exception as exc:
        print(f"[TIMING] Text-to-speech generation ({lang_code}) failed: {time.time() - t_start:.2f}s")
        raise RuntimeError(
            f"gTTS failed to generate audio for language '{target_language}': {exc}"
        ) from exc

    return output_path