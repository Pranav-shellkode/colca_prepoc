# Next steps: running the project

This is the starting point — get the app running and confirm it works over
your browser first. Once that's working, move on to
`OZONETEL_TEST_CALL.md` to test a real phone call through Ozonetel.

## 1. Install dependencies

Backend (from the project root):

```
uv sync
```

Frontend:

```
cd frontend
npm install
cd ..
```

## 2. Check your `.env` file

Most keys already look set. Open `.env` at the project root and confirm you
have real values (not placeholders) for:

- `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
- `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token`
- `POSTGRES_URL`
- `BACKEND_API_KEY`

AWS credentials expire periodically if they're temporary/session-based — if
the bot fails to respond at all once you're on a call, this is the first
thing to check.

You do **not** need the `OZONETEL_*` variables or `WEBHOOK_ENDPOINT` yet —
those are only needed for the real-phone-call test in
`OZONETEL_TEST_CALL.md`. Testing over the browser first doesn't need them.

## 3. Start the backend

```
uv run python -m backend.server.app
```

Confirm it's up:

```
curl http://localhost:8000/
```

Expect: `{"server": "running fine"}`

## 4. Start the frontend

In a separate terminal:

```
cd frontend
npm run dev
```

It should print a local URL, typically `http://localhost:5173`.

## 5. Open the app and place a browser test call

Open the frontend URL in your browser. This connects over your browser's
microphone/speakers, not a real phone — it's the fastest way to check the
voice pipeline (speech-to-text, the AI agent, text-to-speech) works before
touching real telephony at all.

Fill in a test lead (name, company) if the UI asks for it, start the call,
and talk to the bot. Confirm:

- You can hear the bot clearly
- The bot can hear and respond to you
- Interrupting the bot while it's speaking works
- Asking it something that requires a knowledge-base lookup triggers the
  "let me check on that" phrase and a short pause with a soft sound

## 6. Check a saved call afterward

After hanging up, wait ~15–30 seconds for the summary to generate, then:

```
curl "http://localhost:8000/calls" -H "X-API-Key: <your BACKEND_API_KEY>"
```

You should see your test call listed. Then:

```
curl "http://localhost:8000/calls/<call_id>/insights" -H "X-API-Key: <your BACKEND_API_KEY>"
```

Confirm the transcript and AI summary look correct.

## 7. Once the browser call works — move on to Ozonetel

If steps 1–6 all worked, the core voice pipeline is confirmed healthy. Any
issue you hit after this point is specific to the Ozonetel telephony
integration, not the underlying agent. Follow `OZONETEL_TEST_CALL.md` next
to place a real phone call.

## If something goes wrong here

- **Backend won't start / import errors** — re-run `uv sync`, confirm you're
  on the right Python version (`>=3.14`, see `pyproject.toml`).
- **Frontend can't connect to the backend** — check `frontend/.env` has
  `VITE_API_URL`/`VITE_WS_URL` pointing at `localhost:8000`, and that
  `VITE_API_KEY` matches `BACKEND_API_KEY` in the root `.env`.
- **No audio in the browser at all** — check your browser granted microphone
  permission for the page.
- **Bot doesn't respond / errors in the backend log about AWS** — your AWS
  session credentials may have expired; refresh them in `.env`.
