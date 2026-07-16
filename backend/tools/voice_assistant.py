"""Voice assistant utilities: speech-to-text, translation, and text-to-speech.

Uses openai-whisper for local STT, deep-translator for translation, and gTTS
for local TTS. Requires ffmpeg to be installed on the host system.
"""

import os
import subprocess
from pathlib import Path
from typing import Dict

from deep_translator import GoogleTranslator
from gtts import gTTS
import whisper

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


def speech_to_text(audio_file_path: str, language: str = None) -> dict:
    """Transcribe an audio file using local OpenAI Whisper (base model).

    Uses a two-step language detection strategy:
    1. Whisper auto-detects the language from audio
    2. GoogleTranslator auto-detect cross-verifies from the transcribed text
    If they disagree, re-transcribes with the corrected language.

    If 'language' is explicitly provided, skips detection entirely.
    """
    _check_ffmpeg()

    if not os.path.exists(audio_file_path):
        raise FileNotFoundError(f"Audio file not found at: {audio_file_path}")

    # Use 'base' model — fast on CPU (~1-3 seconds for short clips)
    model = whisper.load_model("base")

    if language:
        # User explicitly specified language — transcribe directly
        forced_lang = language.strip().lower()
        result = model.transcribe(audio_file_path, language=forced_lang)
        text = result.get("text", "").strip()
        detected_lang = forced_lang
    else:
        # Step 1: Let Whisper auto-detect and transcribe
        result = model.transcribe(audio_file_path)
        text = result.get("text", "").strip()
        whisper_lang = result.get("language", "en")

        # Step 2: Cross-verify with GoogleTranslator's auto-detect
        # This catches cases where Whisper confuses similar languages
        # (e.g., Telugu detected as Hindi)
        if text and len(text) > 5:
            try:
                detected_obj = GoogleTranslator(source="auto", target="en")
                detected_obj.translate(text)  # triggers detection
                translator_lang = detected_obj.source  # detected source lang
                if translator_lang and translator_lang != whisper_lang:
                    # Translator disagrees — re-transcribe with corrected language
                    result2 = model.transcribe(audio_file_path, language=translator_lang)
                    text2 = result2.get("text", "").strip()
                    if text2 and len(text2) >= len(text) // 2:
                        text = text2
                        whisper_lang = translator_lang
            except Exception:
                pass  # If cross-check fails, stick with Whisper's detection

        detected_lang = whisper_lang

    if not text or len(text) < 2:
        raise ValueError(
            "Whisper returned empty or unreadable transcription. "
            "Please speak more clearly or check your microphone input."
        )

    return {
        "text": text,
        "detected_language": detected_lang,
    }


def translate_text(text: str, source_language: str, target_language: str) -> str:
    """Translate text between two languages using GoogleTranslator."""
    if not text.strip():
        return ""

    src = source_language.strip().lower()
    tgt = target_language.strip().lower()

    if src == tgt:
        return text

    try:
        translator = GoogleTranslator(source=src, target=tgt)
        return translator.translate(text)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to translate text from '{source_language}' to '{target_language}': {exc}"
        ) from exc


def text_to_speech(text: str, target_language: str, output_path: str) -> str:
    """Convert text to speech audio in target language using gTTS and save as MP3."""
    if not text.strip():
        raise ValueError("Cannot convert empty text to speech.")

    lang_code = target_language.strip().lower()

    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        tts = gTTS(text=text, lang=lang_code, slow=False)
        tts.save(output_path)
    except Exception as exc:
        raise RuntimeError(
            f"gTTS failed to generate audio for language '{target_language}': {exc}"
        ) from exc

    return output_path
