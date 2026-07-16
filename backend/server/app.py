import asyncio
import httpx
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketException, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)

from pipecat.pipeline.runner import WorkerRunner
# frame serializer according to the right telephony provider
from pipecat.serializers.protobuf import ProtobufFrameSerializer

from backend.core.config import BACKEND_API_KEY
from backend.pipecat.pipeline import build_pipeline
from backend.utils.lead_context import condition_lead_context
from backend.utils.call_store import get_call_insights, list_calls
from backend.server.models import PreCallContextRequest

logger = logging.getLogger("uvicorn.error")

# Pending pre-call context, keyed by call_id, awaiting the voice module to
# pick it up when the outbound call connects. Single-process in-memory store;
# move to Redis/DB if the server runs with multiple workers.
_pending_call_context: dict[str, dict] = {}


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


# ---------------------------------------------------------------------------
# Pre-call data capture layer
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Call history — lightweight list for the frontend sidebar
# ---------------------------------------------------------------------------
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


# main websocker connection
@app.websocket("/ws")
async def websocket_endpoint(websocket : WebSocket, call_id: str | None = None):
    await websocket.accept()

    logger.info("Websocket new connection created")

    lead_context = _pending_call_context.pop(call_id, None) if call_id else None

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            add_wav_header=False,
            serializer=ProtobufFrameSerializer(),
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
            audio_in_channels=1,
            audio_out_channels=1 ,
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