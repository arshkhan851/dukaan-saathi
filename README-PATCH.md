# Dukaan Saathi: transaction review patch

This patch changes transaction entry from **save immediately** to **review, edit, then confirm**.

## Files
- `app/main.py`: transaction parsing now returns a draft and does not write it to SQLite. A new `/api/confirm-transaction` endpoint validates and saves only confirmed transactions.
- `app/static/index.html`: adds the review panel with editable customer, amount, and transaction type.
- `app/static/app.js`: displays the review panel for both typed and spoken commands; confirms or cancels the draft.

## Install
1. Stop the FastAPI server (`Ctrl+C` in the terminal running Uvicorn).
2. Extract this ZIP.
3. Copy the included `app` folder into your existing project folder and choose **replace/overwrite** when prompted.
4. Do not replace `.env` or `ledger.db`. This patch ZIP does not include either file.
5. Restart using your normal command, for example: `uvicorn app.main:app --reload`.
6. Hard-refresh the browser with `Ctrl+Shift+R`.

## New behavior
- A voice or typed transaction creates a draft, not a database row.
- The customer name, amount, and Credit/Payment direction can be edited.
- `Confirm & Save` writes the transaction to SQLite.
- `Cancel` discards the draft without changing the ledger.
- Balance and daily-summary queries continue to run without a transaction confirmation.

## Important speech-recognition limitation
This patch does not change or retrain Faster-Whisper. If it hears `Prince` as `Prinsne`, the application cannot reliably infer the intended spelling. The review panel lets the shopkeeper correct `Prinsne` to `Prince` before saving. Names are not restricted to a predefined list; Latin-script and Devanagari names can be entered.

## Validation performed
- Python compilation: passed.
- JavaScript syntax check: passed.
- Parser checks: Prince, Suresh, Amit Sharma, and राहुल examples produced drafts with the expected amount and transaction type.
- Database safety: parsing a command did not write a transaction.
- API integration: `/api/process-text` returned a draft without saving; `/api/confirm-transaction` saved exactly one confirmed row.
