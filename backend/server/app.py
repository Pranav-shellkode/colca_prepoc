import asyncio 
import logging 
import os 
from contextlib import asynccontextmanager 

from fastapi import FastAPI , WebSocket , WebSocketException , WebSocketDisconnect 
from fastapi.middleware.cors import CORSMiddleware 

from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)

from pipecat.pipeline.runner import WorkerRunner 
# frame serializer according to the right telephony provider 
from pipecat.serializers.twilio import TwilioFrameSerializer 

from backend.pipecat.pipeline import build_pipeline 

logger = logging.getLogger("uvicorn.error")

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


# main websocker connection 
@app.websocket("/ws") 
async def websocket_endpoint(websocket : WebSocket): 
    await websocket.accept() 

    logger.info("Websocket new connection created") 

    transport = FastAPIWebsocketTransport(
        websocket=websocket, 
        params=FastAPIWebsocketParams(
            add_wav_header=False, 
            serializer=TwilioFrameSerializer(), 
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
        pipeline , worker = build_pipeline(transport=transport) 
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