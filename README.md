# 🏛️ Government Scheme & Financial Inclusion Navigator

An intelligent, conversational AI assistant that helps Indian citizens discover government welfare schemes they are eligible for. By describing their situation in plain language (via text or voice), the system progressively constructs a structured profile, performs deterministic eligibility checks against a database of 29 schemes, and presents matching results complete with required documents, benefits, and direct application links.

---

## 🚀 Tech Stack

### Backend
*   **FastAPI**: Modern, high-performance web framework for APIs.
*   **Groq SDK**: Orchestrates the multi-turn agentic loop using the lightning-fast `llama-3.3-70b-versatile` model.
*   **FAISS & SentenceTransformers**: Vector index (`all-MiniLM-L6-v2`) for retrieval-augmented generation (RAG) over official scheme manuals.
*   **OpenAI Whisper**: Local Speech-to-Text transcription.
*   **gTTS (Google Text-to-Speech)**: Conversational audio generation in regional languages.
*   **deep-translator**: Seamless translation between English and Indian regional languages (Hindi, Telugu, Tamil, Kannada, Malayalam, Marathi).

### Frontend
*   **Vanilla JS (ES6 Modules)**: Modular, clean client architecture with no heavy compiler/bundler dependencies.
*   **HTML5 / CSS3**: Custom modern dashboard UI with responsive styles, sliding panels, and tabbed view navigation (Chat vs. Dashboard).

---

## 📐 Architecture Summary

```
  ┌──────────────────────────────────────────────────────────┐
  │                        FRONTEND                          │
  │              Plain HTML5 + CSS3 + ES6 JS                 │
  └────────────────────────────┬─────────────────────────────┘
                               │
                      HTTP / JSON / Multi-part
                               │
  ┌────────────────────────────▼─────────────────────────────┐
  │                     FASTAPI BACKEND                      │
  │                  (Python API Server)                     │
  └──────┬─────────────────────┬──────────────────────┬──────┘
         │                     │                      │
         ▼                     ▼                      ▼
  ┌─────────────┐       ┌─────────────┐        ┌─────────────┐
  │  GROQ LLM   │       │ RULE ENGINE │        │  RAG INDEX  │
  │ Agent Loop  │       │ (rules.json)│        │ (FAISS/S-T) │
  └─────────────┘       └─────────────┘        └─────────────┘
```

*   **Frontend Layer**: Manages user onboarding (language & occupation selection), chat logs, real-time profile rendering (the "Passbook" panel), custom audio playback, and a responsive tabbed interface.
*   **Backend Layer**: Coordinates the Groq function-calling loop. When users send queries, the agent queries tools to search matched schemes, checks eligibility, retrieves details, or consults unstructured documentation.
*   **Data Layer**:
    *   `schemes.json`: Structured rules specifying constraints for age ranges, states, gender, occupation, land holding limits, and income caps.
    *   `scheme_docs/`: Unstructured official guidelines indexed into a local FAISS vector store.

---

## 🛠️ Setup & Installation

### 1. Prerequisites & System Dependencies
This project requires **FFmpeg** for audio decoding and transcription.

*   **Windows**:
    1.  Download the build from [ffmpeg.org](https://ffmpeg.org/) or [gyan.dev](https://www.gyan.dev/ffmpeg/builds/).
    2.  Extract the package and copy the path to the `bin/` directory.
    3.  Add the `bin/` directory path to your system's Environment Variables **PATH**.
    4.  Restart your terminal/IDE.
*   **macOS**:
    ```bash
    brew install ffmpeg
    ```
*   **Linux (Debian/Ubuntu)**:
    ```bash
    sudo apt update && sudo apt install ffmpeg
    ```

### 2. Configure Environment Variables
Create a file named `.env` in the `backend/` directory:
```env
GROQ_API_KEY=your_groq_api_key_here
```

### 3. Backend Setup
Navigate to the backend directory and install Python dependencies:
```bash
cd backend
pip install -r requirements.txt
```

### 4. Frontend Setup
The frontend runs as a static application and has no bundler dependencies. You can serve it using any simple HTTP server (e.g., Python's built-in HTTP server or VS Code's Live Server).

---

## 🏃 How to Run

### Start the Backend
From the `backend/` directory:
```bash
python main.py
```
*The server will start reloading automatically at `http://localhost:8000`. Swagger API documentation is available at `http://localhost:8000/docs`.*

### Start the Frontend
From the `frontend/` directory, spin up a local server:
```bash
# Python 3
python -m http.server 3000

# OR Node.js
npx serve -p 3000
```
Open `http://localhost:3000` in your web browser.

---

## 📡 API Endpoints

### 1. `/chat` (POST)
Send a plain text user message.

**Request Payload:**
```json
{
  "session_id": "optional-uuid-here",
  "message": "I am a farmer in Karnataka, age 65, owning 2 acres."
}
```

**Response Payload:**
```json
{
  "session_id": "b16a52bbc69d45fa88f89188cb678758",
  "response": "Great news! You qualify for PM-KISAN and the Karnataka Farmer Old Age Pension...",
  "profile": {
    "occupation": "Farmer",
    "state": "Karnataka",
    "income": null,
    "land_acres": 2.0,
    "age": 65,
    "category": null,
    "gender": null
  },
  "tools_used": [
    {
      "tool": "check_eligibility",
      "args": { "scheme_id": "pm-kisan", "user_profile": { "occupation": "Farmer", "land_acres": 2.0 } },
      "result": { "eligible": true, "reason": "You appear to be eligible!" }
    }
  ],
  "eligible_schemes": [
    {
      "name": "PM-KISAN (Pradhan Mantri Kisan Samman Nidhi)",
      "benefit_amount": "₹6,000 per year",
      "reason": "You appear to be eligible for PM-KISAN!",
      "documents_needed": ["Aadhar Card", "Land ownership documents", "Bank Details"],
      "apply_link": "https://pmkisan.gov.in/"
    }
  ]
}
```

### 2. `/voice-query` (POST)
Upload a raw webm/wav audio recording for speech-to-text translation and spoken responses.

**Request (Form Data):**
*   `audio`: [Binary Audio File]
*   `session_id`: "session-uuid" (Optional)
*   `language`: "te" (Optional forced language tag. If omitted, language is auto-detected)

**Response Payload:**
```json
{
  "session_id": "session-uuid",
  "detected_language": "te",
  "transcribed_text": "నేను రైతును",
  "translated_query": "I am a farmer",
  "agent_response_english": "Welcome! I can search schemes for you...",
  "translated_response": "స్వాగతం! నేను మీ కోసం పథకాలను శోధించగలను...",
  "audio_url": "/static/audio/a1b2c3d4.mp3",
  "profile": { "occupation": "Farmer" },
  "tools_used": [],
  "eligible_schemes": []
}
```

### 3. `/session/{session_id}/summary` (GET)
Retrieve real-time dashboard analytics for the current chat session.

**Response Payload:**
```json
{
  "total_checked": 29,
  "eligible_count": 2,
  "needs_more_info_count": 27,
  "eligible_schemes": [ ... ],
  "missing_fields": ["income", "category", "gender"],
  "category_breakdown": {
    "Income Support": 1,
    "Pension": 1
  }
}
```

---

## ⚡ Performance Optimizations

1.  **Lazy-Loaded Model Singletons**: ML models (Whisper and SentenceTransformer) are instantiated as module-level singletons on first use. This eliminates multi-second cold-start latency, cutting response generation down to milliseconds.
2.  **In-Memory Rule Caching**: The rules in `schemes.json` are loaded once and cached in memory, eliminating redundant disk I/O operations on hot loops like the session summary aggregator.
3.  **Detailed Eligibility Explanations**: When verification fails, the backend returns clear, structured reasons with actual thresholds rather than generic failure messages (e.g. *"Your income of ₹3,00,000 exceeds this scheme's limit of ₹2,50,000"*).
