# Aria – Alexa+-style web assistant (Gemini + agentic web search)

## Run
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # add your GEMINI_API_KEY
cd backend && uvicorn server:app --reload --port 8000
```
Open http://localhost:8000 (microphone needs localhost or HTTPS; use Chrome/Edge/Safari).

## How it works
- `backend/agent.py` – Gemini function-calling loop with tools `search_web` (DuckDuckGo), `read_page`, `final_answer`.
  Cards are only kept if their URL appeared in tool output, so links are never invented.
- `backend/server.py` – FastAPI: `/api/chat` streams live agent steps (NDJSON), `/api/tts` returns Gemini speech as WAV.
- `frontend/` – Voice/Text toggle, animated orb, live transcript, streamed "Searching…" trail, clickable result cards.
- Voice in: browser speech recognition. Voice out: Gemini TTS (falls back to browser voice).

## Tweak
`.env`: `GEMINI_MODEL`, `GEMINI_VOICE` (Kore, Puck, Zephyr…), `SEARCH_REGION`.
