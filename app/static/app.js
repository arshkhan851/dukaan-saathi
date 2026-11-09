let recorder;
let micStream;
let audioChunks = [];
let isProcessing = false;
let pendingTransaction = null;
const recordBtn = document.getElementById('recordBtn');
const transcriptDiv = document.getElementById('transcript');
const ledgerTable = document.querySelector('#ledgerTable tbody');
const commandInput = document.getElementById('command');
const commandForm = document.getElementById('commandForm');
const languageSelect = document.getElementById('language');
const reviewCard = document.getElementById('reviewCard');
const reviewCustomer = document.getElementById('reviewCustomer');
const reviewAmount = document.getElementById('reviewAmount');
const reviewType = document.getElementById('reviewType');
const confirmBtn = document.getElementById('confirmBtn');
const cancelBtn = document.getElementById('cancelBtn');

async function loadLedger() {
    const res = await fetch('/api/ledger');
    if (!res.ok) throw new Error('Could not load the ledger.');
    const data = await res.json();
    ledgerTable.replaceChildren();

    data.forEach(tx => {
        const row = document.createElement('tr');
        const timeCell = document.createElement('td');
        const customerCell = document.createElement('td');
        const amountCell = document.createElement('td');
        const typeCell = document.createElement('td');
        const timestamp = new Date(String(tx.timestamp).replace(' ', 'T'));
        timeCell.textContent = Number.isNaN(timestamp.getTime())
            ? tx.timestamp
            : timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        customerCell.textContent = tx.customer_name;
        amountCell.textContent = `₹${tx.amount}`;
        typeCell.textContent = String(tx.transaction_type).toUpperCase();
        typeCell.className = tx.transaction_type;
        row.append(timeCell, customerCell, amountCell, typeCell);
        ledgerTable.appendChild(row);
    });
}

recordBtn.addEventListener('pointerdown', startRecording);
recordBtn.addEventListener('pointerup', stopRecording);
recordBtn.addEventListener('pointercancel', stopRecording);
recordBtn.addEventListener('contextmenu', e => e.preventDefault());

async function startRecording(e) {
    e.preventDefault();
    if (recorder || isProcessing || pendingTransaction) return;
    try {
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Microphone recording is unavailable in this browser.');
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '';
        recorder = new MediaRecorder(micStream, mimeType ? { mimeType } : undefined);
        recorder.addEventListener('dataavailable', event => { if (event.data.size) audioChunks.push(event.data); });
        recorder.start();
        recordBtn.classList.add('recording');
        recordBtn.innerText = 'Listening...';
    } catch (error) {
        if (micStream) micStream.getTracks().forEach(track => track.stop());
        micStream = null;
        recorder = null;
        recordBtn.classList.remove('recording');
        recordBtn.innerText = 'Hold to Speak';
        transcriptDiv.innerText = `Microphone error: ${error.message}`;
    }
}

async function stopRecording(e) {
    e.preventDefault();
    if (!recorder) return;
    const activeRecorder = recorder;
    recorder = null;
    activeRecorder.addEventListener('stop', () => {
        const audioBlob = new Blob(audioChunks, { type: activeRecorder.mimeType || 'audio/webm' });
        audioChunks = [];
        if (micStream) micStream.getTracks().forEach(track => track.stop());
        micStream = null;
        recordBtn.classList.remove('recording');
        if (!audioBlob?.size) {
            transcriptDiv.innerText = 'No audio was captured. Hold the button while speaking, then try again.';
            recordBtn.innerText = 'Hold to Speak';
            return;
        }
        recordBtn.innerText = 'Processing...';
        isProcessing = true;
        sendAudioToServer(audioBlob);
    });
    activeRecorder.stop();
}

async function sendAudioToServer(audioBlob) {
    const formData = new FormData();
    const extension = audioBlob.type.includes('wav') ? 'wav' : 'webm';
    formData.append('audio', audioBlob, `recording.${extension}`);
    formData.append('language_code', languageSelect.value);
    try {
        const response = await fetch('/api/process-audio', { method: 'POST', body: formData });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || `Server returned ${response.status}`);
        handleCommandResult(result);
    } catch (error) {
        transcriptDiv.innerText = `Error: ${error.message}`;
    }
    recordBtn.innerText = 'Hold to Speak';
    isProcessing = false;
}

commandForm.addEventListener('submit', async event => {
    event.preventDefault();
    const text = commandInput.value.trim();
    if (!text || pendingTransaction) return;
    setCommandBusy(true);
    try {
        const response = await fetch('/api/process-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || `Server returned ${response.status}`);
        handleCommandResult(result);
        commandInput.value = '';
    } catch (error) {
        transcriptDiv.innerText = `Error: ${error.message}`;
    } finally {
        setCommandBusy(false);
    }
});

function handleCommandResult(result) {
    const transcript = (result.transcript || '').trim();
    transcriptDiv.innerText = transcript
        ? `Heard: ${transcript}\n${result.reply_text || ''}`
        : (result.reply_text || 'Done.');

    if (result.intent === 'log_transaction' && result.needs_confirmation) {
        pendingTransaction = result;
        reviewCustomer.value = result.customer || '';
        reviewAmount.value = result.amount ?? '';
        reviewType.value = result.type || 'credit';
        reviewCard.style.display = 'block';
        reviewCustomer.focus();
        recordBtn.disabled = true;
        commandInput.disabled = true;
        commandForm.querySelector('button[type="submit"]').disabled = true;
        return;
    }

    // Balance and summary queries do not create ledger records.
    if (result.reply_text && 'speechSynthesis' in window) {
        const utterance = new SpeechSynthesisUtterance(result.reply_text);
        utterance.lang = 'hi-IN';
        window.speechSynthesis.speak(utterance);
    }
}

confirmBtn.addEventListener('click', async () => {
    if (!pendingTransaction) return;
    confirmBtn.disabled = true;
    cancelBtn.disabled = true;
    try {
        const response = await fetch('/api/confirm-transaction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                customer: reviewCustomer.value.trim(),
                amount: reviewAmount.value,
                type: reviewType.value
            })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || `Server returned ${response.status}`);
        pendingTransaction = null;
        reviewCard.style.display = 'none';
        transcriptDiv.innerText = result.reply_text;
        await loadLedger();
        if ('speechSynthesis' in window) {
            const utterance = new SpeechSynthesisUtterance(result.reply_text);
            utterance.lang = 'hi-IN';
            window.speechSynthesis.speak(utterance);
        }
    } catch (error) {
        transcriptDiv.innerText = `Could not save transaction: ${error.message}`;
    } finally {
        confirmBtn.disabled = false;
        cancelBtn.disabled = false;
        updateControls();
    }
});

cancelBtn.addEventListener('click', () => {
    pendingTransaction = null;
    reviewCard.style.display = 'none';
    transcriptDiv.innerText = 'Transaction cancelled. Nothing was saved.';
    updateControls();
});

function updateControls() {
    const blocked = Boolean(pendingTransaction);
    recordBtn.disabled = blocked;
    commandInput.disabled = blocked;
    commandForm.querySelector('button[type="submit"]').disabled = blocked;
}

function setCommandBusy(busy) {
    commandInput.disabled = busy;
    commandForm.querySelector('button[type="submit"]').disabled = busy;
}

loadLedger().catch(error => { transcriptDiv.innerText = error.message; });
