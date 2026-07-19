import asyncio
import httpx
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketException, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)

from pipecat.pipeline.runner import WorkerRunner
# frame serializer according to the right telephony provider
from pipecat.serializers.protobuf import ProtobufFrameSerializer

from backend.core.config import BACKEND_API_KEY, WEBHOOK_ENDPOINT
from backend.pipecat.pipeline import build_pipeline, build_kb_search_mixer
from backend.pipecat.serializers.ozonetel import OzonetelFrameSerializer
from backend.utils.lead_context import condition_lead_context
from backend.utils.call_store import get_call_insights, list_calls, record_ozonetel_cdr
from backend.utils import ozonetel as ozonetel_client
from backend.server.models import PreCallContextRequest
from backend.agents.tools.retrieval_tool import retrieve_colca_faq

logger = logging.getLogger("uvicorn.error")

# Pending pre-call context, keyed by call_id, awaiting the voice module to
# pick it up when the outbound call connects. Single-process in-memory store;
# move to Redis/DB if the server runs with multiple workers.
_pending_call_context: dict[str, dict] = {}

# Ozonetel call metadata (its own call `sid` + the dialed phone number),
# keyed by our call_id. Populated once /ozonetel/hook's NewCall event
# arrives, since Ozonetel's own SID is only known after it answers — needed
# later to disconnect the call via the CallControl API, which takes
# Ozonetel's sid, not our call_id. Same single-process caveat as
# _pending_call_context above.
_active_ozonetel_calls: dict[str, dict] = {}


def require_api_key(x_api_key: str = Header(default="")):
    if not BACKEND_API_KEY or x_api_key != BACKEND_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@asynccontextmanager
async def lifespan(app:FastAPI): 
    logger.info("Server started") 
    yield
    logger.info("Server stopped") 

app = FastAPI(title="Colca Sales agent",lifespan=lifespan) 

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def health():
    return {
        "server" : "running fine" ,
    }


# Pre-call data capture layer
@app.post("/calls/context", dependencies=[Depends(require_api_key)])
async def create_call_context(payload: PreCallContextRequest):
    """
    Ingest and condition lead context from an upstream application ahead of
    an outbound call. Returns a call_id that the voice module (the /ws
    connection that places/answers the call) uses to fetch this context.
    """
    call_id = str(uuid.uuid4())
    lead_context = condition_lead_context(payload.model_dump(exclude_none=True))
    _pending_call_context[call_id] = lead_context

    logger.info(f"Prepared call context for call_id={call_id}")
    return {"call_id": call_id}


# Ozonetel outbound dial trigger
@app.post("/ozonetel/calls", dependencies=[Depends(require_api_key)])
async def create_ozonetel_call(payload: PreCallContextRequest):
    """
    Place an outbound call via Ozonetel. Conditions the lead context the
    same way /calls/context does, stashes it under a fresh call_id, then
    triggers the dial — Ozonetel will hit /ozonetel/hook once the callee
    answers, which hands this call_id to the pipeline via the /ws stream URL.
    """
    if not WEBHOOK_ENDPOINT:
        raise HTTPException(
            status_code=500, detail="WEBHOOK_ENDPOINT is not configured on this server"
        )

    call_id = str(uuid.uuid4())
    lead_context = condition_lead_context(payload.model_dump(exclude_none=True))
    # phone_number covers our own brief shape; LeadForge's response payload
    # carries it as `phone` instead — condition_lead_context already folds
    # whichever one was sent into lead_context["phone_number"].
    phone_number = lead_context.get("phone_number")
    if not phone_number:
        raise HTTPException(status_code=400, detail="phone_number (or phone) is required")
    _pending_call_context[call_id] = lead_context

    response = await asyncio.to_thread(
        ozonetel_client.trigger_outbound_call, phone_number, call_id, WEBHOOK_ENDPOINT
    )
    if response.status_code != 200:
        _pending_call_context.pop(call_id, None)
        logger.error(f"Ozonetel dial trigger failed for call_id={call_id}: {response.text}")
        raise HTTPException(status_code=502, detail="Failed to place outbound call via Ozonetel")

    logger.info(f"Triggered Ozonetel outbound call, call_id={call_id}")
    return {"call_id": call_id}


# Call history — lightweight list for the frontend sidebar
@app.get("/calls", dependencies=[Depends(require_api_key)])
async def list_recent_calls(limit: int = 50):
    try:
        records = await asyncio.to_thread(list_calls, limit)
    except Exception:
        logger.exception("Failed to list calls")
        raise HTTPException(status_code=502, detail="Failed to query call history")

    return [
        {
            "call_id": r["call_id"],
            "phone_number": r["phone_number"],
            "lead_context": r["lead_context"],
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
            "outcome": r["outcome"],
            "created_at": r["created_at"],
        }
        for r in records
    ]


# ---------------------------------------------------------------------------
# Results getter — AI insights and outcomes for downstream applications
# ---------------------------------------------------------------------------
@app.get("/calls/{call_id}/insights", dependencies=[Depends(require_api_key)])
async def get_insights(call_id: str):
    try:
        record = await asyncio.to_thread(get_call_insights, call_id)
    except Exception:
        logger.exception(f"Failed to fetch insights for call_id={call_id}")
        raise HTTPException(status_code=502, detail="Failed to query insights store")

    if record is None:
        raise HTTPException(status_code=404, detail=f"No insights found for call_id={call_id}")

    summary = record["summary"]
    return {
        "call_id": record["call_id"],
        "session_id": record["session_id"],
        "phone_number": record["phone_number"],
        "started_at": record["started_at"],
        "ended_at": record["ended_at"],
        "transcript": record["transcript"],
        "outcome": record["outcome"],
        "ai_summary": summary,
        "lead_context": record["lead_context"],
    }


# ---------------------------------------------------------------------------
# Ozonetel webhooks — no API-key dependency, since Ozonetel's own servers
# call these directly and won't send our X-API-Key header.
# ---------------------------------------------------------------------------
@app.api_route("/ozonetel/hook", methods=["GET", "POST"])
async def ozonetel_hook(request: Request):
    """
    Ozonetel calls this on call-lifecycle events. On NewCall (callee
    answered), respond with XML instructing Ozonetel to open the media
    websocket at /ws?provider=ozonetel&call_id=<our call_id>, where our own
    call_id is round-tripped back to us via the `extra_data` param we passed
    at dial time.
    """
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            params.update(dict(await request.form()))
        except Exception:
            pass

    event = params.get("event")
    logger.info(f"Ozonetel hook event={event} params={params}")

    if event == "NewCall":
        call_id = params.get("extra_data") or params.get("customData") or params.get("custom_data")
        if not call_id:
            logger.warning("Ozonetel NewCall hook missing extra_data/call_id")
            return Response(content="<response></response>", media_type="application/xml")

        # Ozonetel's own call sid is only known now that it has answered —
        # stash it (+ the dialed number) so /ozonetel/calls/{call_id}/hangup
        # can disconnect this call later via the CallControl API, which
        # takes Ozonetel's sid, not our call_id.
        _active_ozonetel_calls[call_id] = {
            "sid": params.get("sid"),
            "phone_no": params.get("phone_no") or params.get("cid") or params.get("called_number"),
        }

        xml = ozonetel_client.build_stream_xml(WEBHOOK_ENDPOINT, call_id)
        return Response(content=xml, media_type="application/xml")

    # Stream/Hangup/anything else — acknowledge with an empty response.
    return Response(content="<response></response>", media_type="application/xml")


@app.api_route("/ozonetel/callback", methods=["GET", "POST"])
async def ozonetel_callback(request: Request):
    """
    Ozonetel calls this once after the call fully ends with the final CDR
    (duration, pick/answer status, telco disposition code).

    Two cases:
    - The callee answered and a /ws pipeline session ran: the pipeline's own
      on_client_disconnected handler already saved a transcript/summary row
      for this call_id, so this only adds the telco columns to it.
    - The callee never answered (busy/no-answer/failed): no /ws session ever
      ran, so no row exists yet — this inserts a CDR-only placeholder row so
      the call still shows up in call history instead of vanishing silently.
    """
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            params.update(dict(await request.form()))
        except Exception:
            pass

    call_id = params.get("extra_data") or params.get("customData") or params.get("custom_data")
    telco_code = params.get("telco_code")
    pick_time = params.get("pick_time")
    duration = params.get("duration")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    logger.info(f"Ozonetel callback for call_id={call_id}: {params}")

    if call_id:
        active = _active_ozonetel_calls.pop(call_id, {})
        # A never-answered call never reached /ws, so its lead context is
        # still sitting unclaimed in _pending_call_context — pop it here so
        # a CDR-only row still carries lead info, and so it doesn't leak.
        lead_context = _pending_call_context.pop(call_id, None)
        status = ozonetel_client.resolve_telco_status(telco_code, pick_time)
        try:
            await asyncio.to_thread(
                record_ozonetel_cdr,
                call_id,
                status,
                telco_code,
                int(duration) if duration else None,
                params.get("phone_no") or active.get("phone_no"),
                lead_context,
                start_time,
                end_time,
            )
        except Exception:
            logger.exception(f"Failed to persist Ozonetel telco status for call_id={call_id}")

    return Response(content="", media_type="text/plain")


@app.post("/ozonetel/calls/{call_id}/hangup", dependencies=[Depends(require_api_key)])
async def hangup_ozonetel_call(call_id: str):
    """Disconnect an active Ozonetel call by our call_id."""
    active = _active_ozonetel_calls.get(call_id)
    if not active or not active.get("sid"):
        raise HTTPException(
            status_code=404,
            detail=f"No active Ozonetel call found for call_id={call_id}",
        )

    response = await asyncio.to_thread(
        ozonetel_client.disconnect_call, active["sid"], active.get("phone_no") or ""
    )
    if response.status_code != 200:
        logger.error(f"Ozonetel disconnect failed for call_id={call_id}: {response.text}")
        raise HTTPException(status_code=502, detail="Failed to disconnect call via Ozonetel")

    logger.info(f"Disconnected Ozonetel call_id={call_id} (sid={active['sid']})")
    return {"call_id": call_id, "status": "disconnect_requested"}


# main websocker connection
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket, call_id: str | None = None, provider: str | None = None
):
    await websocket.accept()

    logger.info(f"Websocket new connection created (provider={provider or 'browser'})")

    lead_context = _pending_call_context.pop(call_id, None) if call_id else None

    # Ozonetel's stream URL (built in /ozonetel/hook) carries provider=ozonetel
    # so this connection speaks Ozonetel's JSON media protocol instead of the
    # browser client's Protobuf frames — the pipeline itself is unaffected,
    # since the internal audio rate (16kHz) stays fixed; the serializer
    # resamples to/from Ozonetel's 8kHz wire rate internally.
    if provider == "ozonetel":
        serializer = OzonetelFrameSerializer(ucid=call_id or "")
    else:
        serializer = ProtobufFrameSerializer()

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            add_wav_header=False,
            serializer=serializer,
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
            audio_in_channels=1,
            audio_out_channels=1 ,
            audio_out_mixer=build_kb_search_mixer(),
        ),
    )

    runner = WorkerRunner(handle_sigint=False)

    try:
        pipeline , worker = await build_pipeline(transport=transport, call_id=call_id, lead_context=lead_context)
        await runner.run(worker)
    except WebSocketDisconnect:
        logger.info("Websocket disconnected")
    except Exception as exc:
        logger.exception(f"Pipeline error : {exc}")
    finally:
        logger.info("Ended the session")

if __name__ == "__main__": 
    import uvicorn 
    uvicorn.run("backend.server.app:app" , 
                host="127.0.0.1",
                port=8000,
                reload=True,
                log_level="info"
    )