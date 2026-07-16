import asyncio
import logging 
import uuid 
from datetime import datetime,timezone 

from pipecat.audio.vad.silero import SileroVADAnalyzer 
from pipecat.audio.vad.vad_analyzer import VADParams , VADAnalyzer  
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams , PipelineWorker 
from pipecat.processors.aggregators.llm_context import LLMContext 
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair , LLMAssistantAggregatorParams , LLMUserAggregatorParams
)
from pipecat.turns.user_mute import AlwaysUserMuteStrategy
from pipecat.processors.frameworks.strands_agents import StrandsAgentsProcessor 
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService,CommitStrategy
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService,ElevenLabsTTSSettings 
from pipecat.frames.frames import LLMMessagesAppendFrame 
from pipecat.services.deepgram.stt import DeepgramSTTService,DeepgramSTTSettings
from pipecat.services.deepgram.tts import DeepgramTTSService,DeepgramTTSSettings 

from backend.core.config import * 
from backend.strands.agent import build_agent 
from backend.strands.prompt import colca_sales_agent_prompt
from backend.utils.call_summary import summarize_call
from backend.utils.call_store import save_call_summary

logger = logging.getLogger(__name__) 

async def build_pipeline(transport):
    """
    returns a pipeline and a worker to be run 
    """ 
    session_id = str(uuid.uuid4()) 
    started_at = datetime.now(timezone.utc).isoformat() 


    # stt service 
    # deepgram_stt = DeepgramSTTService(
    #     api_key=DEEPGRAM_API_KEY
    # )

    elevenlabs_stt = ElevenLabsRealtimeSTTService(
        api_key=ELEVENLABS_API_KEY,
        commit_strategy=CommitStrategy.MANUAL,
    )

    # tts service 
    # deepgram_tts = DeepgramTTSService(
    #     api_key=DEEPGRAM_API_KEY,
    # )

    elevenlabs_tts = ElevenLabsTTSService(
        api_key=ELEVENLABS_API_KEY, 
        settings=ElevenLabsTTSSettings(
            voice=ELEVENLABS_VOICE_ID, 
            speed=1.0, 

        )
    )

    # Agent service 
    agent = build_agent() 
    sales_agent = StrandsAgentsProcessor(agent=agent) 

    # VAD detection 
    vad_analyzer = SileroVADAnalyzer(
    params=VADParams(
        confidence=0.7,      # Minimum confidence for voice detection
        start_secs=0.2,      # Time to wait before confirming speech start
        stop_secs=0.2,       # Time to wait before confirming speech stop
        min_volume=0.6,      # Minimum volume threshold
    )
    )

    system_prompt = colca_sales_agent_prompt() 

    context = LLMContext(
        messages=[{
            "role" : "system" ,
            "content" : system_prompt, 
        }]
    )

    # try it out later replace with the other format
    context_aggregator = LLMContextAggregatorPair(
        context=context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=vad_analyzer,
            user_mute_strategies=[AlwaysUserMuteStrategy()],
        ),
    )

    # main pipeline 
    pipeline = Pipeline([
        transport.input() , 
        elevenlabs_stt, 
        context_aggregator.user() ,
        sales_agent , 
        elevenlabs_tts , 
        transport.output() , 
        context_aggregator.assistant(), 
    ]
    )

    worker = PipelineWorker(pipeline=pipeline) 

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport,client):
        logger.info("Client connected") 
        # await worker.queue_frames([
        #     LLMMessagesAppendFrame(
        #         messages=[{
        #             "role": "user",
        #             "content": "Please greet me briefly and let me know you're ready to help.",
        #         }],
        #         run_llm=True,
        #     )
        # ])

    @ transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport,client):
        logger.info("client disconnected")
        msgs = context.get_messages()

        transcript = "\n".join(
            f"{m.get('role')}: {m.get('content')}" for m in msgs if m.get("role") != "system"
        )
        ended_at = datetime.now(timezone.utc).isoformat()

        if transcript.strip():
            try:
                summary = await asyncio.to_thread(summarize_call, transcript)
                await asyncio.to_thread(
                    save_call_summary, session_id, started_at, ended_at, transcript, summary
                )
                logger.info(f"Saved call summary for session {session_id}")
            except Exception:
                logger.exception(f"Failed to save call summary for session {session_id}")
    
    return pipeline , worker 

                                                                

