import io, os, json, wave
from pathlib import Path
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google.genai import types
from agent import run_agent, client

TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
VOICE = os.getenv("GEMINI_VOICE", "Kore")
FRONT = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Aria")

class Turn(BaseModel):
    role: str
    text: str

class ChatIn(BaseModel):
    message: str
    history: list[Turn] = []

class TTSIn(BaseModel):
    text: str

@app.post("/api/chat")
def chat(body: ChatIn):
    def stream():
        try:
            for ev in run_agent(body.message, [t.model_dump() for t in body.history]):
                yield json.dumps(ev) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "text": f"{type(e).__name__}: {e}"}) + "\n"
    return StreamingResponse(stream(), media_type="application/x-ndjson")

@app.post("/api/tts")
def tts(body: TTSIn):
    """Gemini text-to-speech -> WAV. Frontend falls back to the browser voice on failure."""
    try:
        r = client().models.generate_content(
            model=TTS_MODEL, contents=body.text[:800],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)))))
        pcm = r.candidates[0].content.parts[0].inline_data.data
    except Exception as e:
        raise HTTPException(502, str(e))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    return Response(buf.getvalue(), media_type="audio/wav")

@app.get("/")
def index():
    return FileResponse(FRONT / "index.html")

app.mount("/static", StaticFiles(directory=FRONT), name="static")
