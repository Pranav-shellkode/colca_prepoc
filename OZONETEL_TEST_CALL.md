# How to make your first real Ozonetel test call

This walks through placing one real outbound call through Ozonetel to verify
the integration end to end. Follow the steps in order.

## 1. Get your Ozonetel credentials

You'll need these from your Ozonetel account:

- **API key** — for the outbound-dial and disconnect APIs
- **SIP number** — the SIP streaming extension assigned to your account
- **DID** — the default caller-ID number used when disconnecting a call

## 2. Make your server publicly reachable

Ozonetel's cloud needs to reach your server over the internet — `localhost`
will not work. If you're testing from your laptop, use a tunnel:

```
ngrok http 8000
```

Note the public URL it gives you (e.g. `https://abcd1234.ngrok-free.app`).
You only need the **host**, not the `https://` — e.g. `abcd1234.ngrok-free.app`.

If your server is already deployed somewhere with a public IP/domain and
port 8000 open, use that host instead.

## 3. Set the required environment variables

Add these to your `.env` file (all currently unset):

```
OZONETEL_API_KEY=<your api key>
OZONETEL_SIP_NUMBER=<your sip number>
OZONETEL_DID=<your did>
WEBHOOK_ENDPOINT=<your public host, e.g. abcd1234.ngrok-free.app:8000>
```

`WEBHOOK_ENDPOINT` must include the port if it's not a standard 80/443 (e.g.
ngrok's free tier serves on 443 externally but check what your tunnel gives
you — match exactly what `curl` in step 4 succeeds against).

## 4. Start the server and confirm the webhook routes respond

Start the backend:

```
uv run python -m backend.server.app
```

From another terminal, hit the health check:

```
curl http://localhost:8000/
```

You should get `{"server": "running fine"}`. Now simulate what Ozonetel will
send when a call connects, through your public tunnel URL (not localhost):

```
curl "http://<your-public-host>/ozonetel/hook?event=NewCall&extra_data=test-123&sid=SID-TEST&phone_no=911234567890"
```

You should get back an XML response containing a `<stream ... url="ws://...">`
tag. If this fails or times out, fix connectivity before moving on — nothing
past this point will work otherwise.

## 5. Place the test call

Send a request to your own phone number (use a real number you can answer):

```
curl -X POST "http://localhost:8000/ozonetel/calls" \
  -H "X-API-Key: <your BACKEND_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
        "phone_number": "+91XXXXXXXXXX",
        "lead_name": "Test User",
        "company_name": "Test Co"
      }'
```

You should get back `{"call_id": "<some uuid>"}`. Note this `call_id` — you'll
need it later.

## 6. Answer the call and watch the server logs

Your phone should ring within a few seconds. Answer it, and watch the
server's terminal output. You should see, in order:

1. `Ozonetel hook event=NewCall ...` — Ozonetel telling your server the call
   connected
2. `Websocket new connection created (provider=ozonetel)` — the media
   connection opening
3. The bot should start speaking almost immediately (it opens with the
   greeting since lead context was provided)

## 7. Check these things while on the call

- **Can you hear the bot clearly?** Listen for garbled audio, wrong pitch, or
  static — this would point to a resampling issue.
- **Does the bot hear you?** Speak normally and confirm it responds
  relevantly, not randomly or not at all.
- **Does interrupting the bot work?** Start talking while the bot is mid
  -sentence — it should stop speaking almost immediately instead of talking
  over you.
- **Is there a knowledge-base question you can ask?** Ask something the bot
  would need to look up (e.g. about pricing or a feature) — you should hear
  the "let me check on that" phrase and a soft typing sound while it searches.

## 8. Hang up and check what got saved

After the call ends naturally, wait about 15–30 seconds (the AI summary takes
a little time to generate), then check:

```
curl "http://localhost:8000/calls/<call_id>/insights" \
  -H "X-API-Key: <your BACKEND_API_KEY>"
```

Confirm the response has a `transcript` that matches what was actually said,
and an `ai_summary` with a sensible outcome.

## 9. (Optional) Test hanging up from your side instead

If you want to test the disconnect API instead of hanging up your phone,
place another call and, while it's still ringing or connected, run:

```
curl -X POST "http://localhost:8000/ozonetel/calls/<call_id>/hangup" \
  -H "X-API-Key: <your BACKEND_API_KEY>"
```

The call should disconnect within a few seconds.

## 10. Test the "never answered" case

Place a call to a number you can decline or ignore. After it stops ringing,
check the call history:

```
curl "http://localhost:8000/calls" -H "X-API-Key: <your BACKEND_API_KEY>"
```

The call should show up with an outcome like `NOT_ANSWERED` or `BUSY` instead
of being missing entirely.

## If something goes wrong

- **No XML back from `/ozonetel/hook` in step 4** — check `WEBHOOK_ENDPOINT`
  is reachable from the public internet, not just your machine.
- **Phone never rings** — check the server logs right after step 5's curl
  call for an error from `trigger_outbound_call`; also confirm
  `OZONETEL_API_KEY` is correct.
- **Call connects but no audio either direction** — check for errors in the
  server log mentioning `OzonetelFrameSerializer`; also confirm the websocket
  actually opened (step 6, log line 2).
- **Audio choppy or garbled** — likely a resampling/audio-rate issue; note the
  exact symptom (too fast, robotic, cutting in and out) so it can be narrowed
  down.
