from fastapi import FastAPI, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os
import sqlite3
import tempfile
import re
import unicodedata
from pathlib import Path
from fastapi import HTTPException
from app.database import DB_FILE, init_db, log_transaction, get_customer_balance, get_daily_total
from app.gnani_client import get_transcript

app = FastAPI(title="Dukaan Saathi API")
init_db()
AUDIO_DIR = Path(__file__).resolve().parent / "static" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

def _clean_customer_name(value: str) -> str:
    """Remove ledger grammar/action words while preserving the customer's name."""
    stopwords = {
        # Hindi / Hinglish particles and transaction vocabulary
        "ne", "ko", "ka", "ki", "ke", "hain", "hai", "ho", "tha", "thi",
        "rupaya", "rupaye", "rupay", "rs", "rupee", "rupees",
        "udhaar", "udhar", "jama", "diya", "diye", "di", "liye", "liya",
        "lia", "kar", "karo", "karna", "kiya", "kiye", "bheja", "bheje",
        "wapas", "vaapas", "lautaya", "lautaye", "paid", "received",
        "payment", "credit", "balance", "baaki", "kitna", "kitne",
        "batao", "batana", "account", "mein", "me", "par", "se",
        # Devanagari
        "ने", "को", "का", "की", "के", "हैं", "है", "हो", "था", "थी",
        "रुपया", "रुपये", "रुपए", "उधार", "जमा", "दिया", "दिए", "दी",
        "लिए", "लिया", "किया", "किये", "कर", "करो", "वापस", "भेजा",
        "भेजे", "भुगतान", "बाकी", "कितना", "कितने", "बताओ", "में", "से",
        # Kannada
        "ಗೆ", "ನಲ್ಲಿ", "ಇಂದ", "ರೂಪಾಯಿ", "ರೂಪಾಯಿ", "ಕೊಟ್ಟ", "ಕೊಟ್ಟರು",
        "ಪಾವತಿ", "ಜಮಾ", "ಬಾಕಿ", "ಎಷ್ಟು", "ಮಾಡಿ", "ಮಾಡಿದ",
    }
    value = "".join(ch if unicodedata.category(ch)[0] in "LMN" or ch.isspace() else " " for ch in value.lower())
    words = [word for word in re.split(r"\s+", value.strip()) if word and word not in stopwords]
    # Latin-script names look cleaner in the ledger with conventional capitalization.
    cleaned = " ".join(words)
    if cleaned and all(re.fullmatch(r"[a-z]+", word) for word in words):
        cleaned = cleaned.title()
    return cleaned


def parse_command(text: str) -> dict:
    """Offline parser for common Hindi/Hinglish/Kannada shop-ledger commands."""
    text = text.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if not normalized:
        return {"intent": "unknown", "reply_text": "Kuch sunai nahi diya. Dobara boliye ya likhiye."}

    if any(phrase in normalized for phrase in (
        "aaj kitna", "aaj ka total", "today total", "kitna udhaar",
        "कितना उधार", "आज का कुल",
    )):
        total = get_daily_total("credit")
        return {"intent": "query_daily_summary", "reply_text": f"Aaj {total:g} rupaye ka udhaar diya hai."}

    if any(word in normalized for word in ("balance", "baaki", "बाकी", "उधार कितना", "कितna")):
        customer = _clean_customer_name(normalized)
        if not customer:
            return {"intent": "unknown", "reply_text": "Kis customer ka balance dekhna hai? Naam ke saath poochhiye."}
        balance = get_customer_balance(customer)
        return {"intent": "query_balance", "reply_text": f"{customer} ka balance {balance:g} rupaye hai."}

    # Accept plain amounts and comma-grouped amounts such as 1,500 or 1,500.50.
    amount_match = re.search(r"(?<!\w)(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)(?!\w)", normalized)
    if not amount_match:
        return {"intent": "unknown", "reply_text": "Rakam samajh nahi aayi. Naam aur rakam, jaise 'Ramesh ko 200 udhaar', likhiye."}
    amount = float(amount_match.group(1).replace(",", ""))
    if amount <= 0:
        return {"intent": "unknown", "reply_text": "Rakam zero se zyada honi chahiye."}

    before_amount = normalized[:amount_match.start()].strip()
    after_amount = normalized[amount_match.end():].strip()
    customer = _clean_customer_name(before_amount)
    if not customer:
        customer = _clean_customer_name(after_amount)
    if not customer:
        return {"intent": "unknown", "reply_text": "Customer ka naam samajh nahi aaya. Naam aur rakam phir se boliye."}

    payment_words = {
        "payment", "jama", "wapas", "vaapas", "bheja", "bheje",
        "paid", "received", "returned", "जमा", "वापस", "भुगतान",
        "ಪಾವತಿ", "ಜಮಾ",
    }
    tokens = set(re.findall(r"[^\W\d_]+", normalized, flags=re.UNICODE))

    # Direction matters for Hindi verbs such as "diya/dिये":
    # "Suresh ne 500 rupaye diye" = Suresh paid the shopkeeper,
    # while "Suresh ko 500 rupaye diye" = the shopkeeper gave Suresh money.
    customer_subject_paid = bool(re.search(
        r"(?:^|\s)(?:ne|ने)\s+.*\d[\d,.]*.*\b(?:diya|diye|di|दिया|दिए|दी)\b",
        normalized,
    ))
    shopkeeper_gave_customer = bool(re.search(
        r"(?:^|\s)(?:ko|को)\s+.*\d[\d,.]*.*\b(?:diya|diye|di|दिया|दिए|दी)\b",
        normalized,
    ))
    kind = "payment" if (tokens.intersection(payment_words) or customer_subject_paid) and not shopkeeper_gave_customer else "credit"
    # Do not write financial records during recognition. Return a reviewable draft;
    # the user must confirm the customer, amount and direction first.
    return {
        "intent": "log_transaction",
        "customer": customer,
        "amount": amount,
        "type": kind,
        "needs_confirmation": True,
        "reply_text": "Kripya details check karke Confirm & Save dabayein.",
    }

async def process_text_command(text: str) -> dict:
    # Keep command handling local so it remains immediate when cloud DNS or APIs fail.
    return parse_command(text)

@app.post("/api/process-text")
async def process_text(payload: dict):
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Please enter or dictate a command.")
    result = await process_text_command(text)
    return {**result, "transcript": text, "audio_url": None}


@app.post("/api/confirm-transaction")
async def confirm_transaction(payload: dict):
    customer = _clean_customer_name(str(payload.get("customer", "")))
    raw_amount = payload.get("amount")
    transaction_type = str(payload.get("type", "")).strip().lower()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer name is required.")
    try:
        amount = float(str(raw_amount).replace(",", ""))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Enter a valid amount.")
    if not (0 < amount <= 10_000_000):
        raise HTTPException(status_code=400, detail="Amount must be greater than zero and within the supported limit.")
    if transaction_type not in {"credit", "payment"}:
        raise HTTPException(status_code=400, detail="Choose Credit or Payment.")

    log_transaction(customer, amount, transaction_type)
    action = "jama kar liya" if transaction_type == "payment" else "udhaar likh diya"
    return {
        "intent": "transaction_saved",
        "customer": customer,
        "amount": amount,
        "type": transaction_type,
        "reply_text": f"{customer} ka {amount:g} rupaye {action}.",
    }

@app.post("/api/process-audio")
async def process_audio(audio: UploadFile = File(...), language_code: str = Form("hi-IN")):
    contents = await audio.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The recording was empty. Hold the button while speaking, then try again.")
    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Recording is too large. Please record a shorter clip.")
    suffix = Path(audio.filename or "recording.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(prefix="dukaan_", suffix=suffix, delete=False) as f:
        f.write(contents)
        in_path = f.name

    try:
        try:
            transcript = await get_transcript(in_path, language_code)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Speech recognition failed: {exc}") from exc
        command_result = await process_text_command(transcript)
        reply_text = command_result["reply_text"]
        
        return JSONResponse(content={
            **command_result,
            "transcript": transcript,
            "reply_text": reply_text,
            "audio_url": None
        })
        
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)

@app.get("/api/ledger")
def ledger_route():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 20")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")
app.mount("/", StaticFiles(directory=str(Path(__file__).resolve().parent / "static"), html=True), name="static")
