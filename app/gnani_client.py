import os
import json
import asyncio
import httpx
from dotenv import load_dotenv
from pathlib import Path
from functools import lru_cache

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

GNANI_API_KEY = os.getenv("GNANI_API_KEY")
GNANI_BASE_URL = "https://api.vachana.ai"
EVON_HF_URL = os.getenv("EVON_LLM_URL", "https://api-inference.huggingface.co/models/gnani/gnani-evon-v3.3-30B-A3B")
HF_TOKEN = os.getenv("HF_TOKEN")

@lru_cache(maxsize=1)
def _local_whisper_model():
    """Load the already-cached multilingual Whisper model without network access."""
    from faster_whisper import WhisperModel

    cache_root = Path(os.getenv("HF_HUB_CACHE", Path.home() / ".cache" / "huggingface" / "hub"))
    model_root = cache_root / "models--Systran--faster-whisper-base" / "snapshots"
    snapshots = sorted(
        (path for path in model_root.iterdir() if path.is_dir() and (path / "model.bin").is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if model_root.exists() else []
    model_path = str(snapshots[0]) if snapshots else "Systran/faster-whisper-base"
    # This machine has CTranslate2 but is missing the CUDA cuBLAS runtime, so stay on CPU.
    return WhisperModel(model_path, device="cpu", compute_type="int8", local_files_only=True)

def _transcribe_locally(audio_file_path: str, language: str) -> str:
    model = _local_whisper_model()
    segments, _ = model.transcribe(audio_file_path, language=language, beam_size=5, vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()

# 1. Prisma STT (Speech to Text)
# 1. Prisma STT (Speech to Text)
async def get_transcript(audio_file_path: str, language_code: str = "hi-IN") -> str:
    language = language_code.split("-", 1)[0].lower()
    transcript = await asyncio.to_thread(_transcribe_locally, audio_file_path, language)
    if not transcript:
        raise RuntimeError("Local speech recognition returned no words. Speak louder or try a longer recording.")
    return transcript

    # Retained service implementation below can be enabled manually for environments with cloud access.
    if not GNANI_API_KEY:
        raise RuntimeError("Local speech recognition failed and GNANI_API_KEY is missing.")
    url = f"{GNANI_BASE_URL}/stt/v3"
    headers = {"X-API-Key-ID": GNANI_API_KEY}
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        with open(audio_file_path, "rb") as f:
            # FIX: The key MUST be 'audio_file' as per the 422 error
            files = {"audio_file": (os.path.basename(audio_file_path), f, "audio/wav")}
            data = {
                "model": "prisma-v3.0",
                "language_code": language_code,
                "format": "transcribe"
            }
            
            response = await client.post(url, headers=headers, data=data, files=files)
            
        if response.status_code != 200:
            print("\n" + "="*50)
            print(f"❌ PRISMA STT FAILED - Status Code {response.status_code}")
            print(f"❌ EXACT REASON: {response.text}")
            print("="*50 + "\n")
            response.raise_for_status()
            
        result = response.json()
        transcript = result.get("transcript", "")
        if not transcript:
            raise RuntimeError(f"Speech service returned no transcript: {result}")
        return transcript

# 2. Evon LLM (via Hugging Face)
async def extract_intent(transcript: str, system_prompt: str) -> dict:
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN is missing. Add your Hugging Face token to the .env file.")
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json"
    }
    
    prompt = f"{system_prompt}\n\nUser: {transcript}\nOutput:"
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 150,
            "temperature": 0.1,
            "return_full_text": False
        }
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(EVON_HF_URL, headers=headers, json=payload)
        
        if response.status_code != 200:
            print("\n" + "="*50)
            print(f"❌ EVON LLM FAILED - Status Code {response.status_code}")
            print(f"❌ EXACT REASON: {response.text}")
            print("="*50 + "\n")
            response.raise_for_status()
            
        result = response.json()
        
        try:
            generated_text = result[0]["generated_text"]
            # Clean up potential markdown from the 30B model
            cleaned_text = generated_text.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned_text)
        except Exception as e:
            print(f"Failed to parse Evon output: {e}\nRaw JSON: {result}")
            return {"intent": "unknown", "reply_text": "Main samajh nahi paya."}

# 3. Timbre TTS (Text to Speech)
async def get_audio_reply(text: str, output_path: str, language_code: str = "hi-IN"):
    if not GNANI_API_KEY:
        raise RuntimeError("GNANI_API_KEY is missing. Add your Gnani API key to the .env file.")
    url = f"{GNANI_BASE_URL}/api/v1/tts/inference"
    headers = {
        "X-API-Key-ID": GNANI_API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "text": text,
        "voice": "Nalini", 
        "model": "timbre-v2.5",
        "language": language_code,
        "audio_config": {
            "sample_rate": 48000,
            "encoding": "linear_pcm",
            "container": "wav"
        }
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print("\n" + "="*50)
            print(f"❌ TIMBRE TTS FAILED - Status Code {response.status_code}")
            print(f"❌ EXACT REASON: {response.text}")
            print("="*50 + "\n")
            response.raise_for_status()
            
        with open(output_path, "wb") as f:
            f.write(response.content)
            
        return output_path
