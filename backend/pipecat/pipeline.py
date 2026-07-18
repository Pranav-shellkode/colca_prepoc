import asyncio
import logging 
import uuid 
import boto3
from datetime import datetime,timezone 

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams , VADAnalyzer
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.transcriptions.language import Language
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams , PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair , LLMAssistantAggregatorParams , LLMUserAggregatorParams
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.turns.user_start import VADUserTurnStartStrategy
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.services.aws.llm import AWSBedrockLLMService , AWSBedrockLLMSettings
from pipecat.turns.user_mute import AlwaysUserMuteStrategy
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService,CommitStrategy,ElevenLabsRealtimeSTTSettings
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService,ElevenLabsTTSSettings  
from pipecat.frames.frames import LLMMessagesAppendFrame
from backend.core.config import *
from backend.agents.prompt import colca_sales_agent_prompt
from backend.utils.call_summary import summarize_call
from backend.utils.call_store import save_call_summary
from backend.agents.tools.retrieval_tool import retrieve_colca_faq

logger = logging.getLogger(__name__) 

async def build_pipeline(transport, call_id: str | None = None, lead_context: dict | None = None):
    """
    returns a pipeline and a worker to be run

    call_id: pre-call identifier issued by the pre-call data capture layer;
        falls back to a fresh id for ad-hoc/inbound sessions.
    lead_context: conditioned pre-call context payload (see
        backend.utils.lead_context.condition_lead_context), used to
        personalize the system prompt and open the call by name.
    """
    session_id = str(uuid.uuid4())
    call_id = call_id or session_id
    started_at = datetime.now(timezone.utc).isoformat()
    phone_number = (lead_context or {}).get("phone_number")


    elevenlabs_stt = ElevenLabsRealtimeSTTService(
        api_key=ELEVENLABS_API_KEY,
        commit_strategy=CommitStrategy.VAD,
        settings=ElevenLabsRealtimeSTTSettings(
            language=Language.EN,
            vad_silence_threshold_secs=1.0 , 
            vad_threshold=0.3, 
        )
    )

    elevenlabs_tts = ElevenLabsTTSService(
        api_key=ELEVENLABS_API_KEY, 
        settings=ElevenLabsTTSSettings(
            voice=ELEVENLABS_VOICE_ID, 
            speed=1.0, 

        )
    )

    system_prompt = colca_sales_agent_prompt(lead_context)

    aws_llm = AWSBedrockLLMService(
        model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        aws_access_key=AWS_ACCESS_KEY_ID,
        aws_secret_key=AWS_SECRET_ACCESS_KEY,
        aws_session_token=AWS_SESSION_TOKEN,
        aws_region=AWS_REGION,
        settings=AWSBedrockLLMSettings(
            system_instruction=system_prompt,
            enable_prompt_caching=True,
        )
    )

    # VAD detection 
    vad_analyzer = SileroVADAnalyzer(
    params=VADParams(
        confidence=0.7,      
        start_secs=0.2,      
        stop_secs=0.2,       
        min_volume=0.6,      
    )
    )

    context = LLMContext(
        tools=[retrieve_colca_faq] ,
    )

    # AWS Bedrock (Claude) is a cascade (text-based) LLM, not a realtime one,
    # so the user message it sees comes from the aggregated transcript —
    # turn-stop must keep wait_for_transcript=True or a turn could finalize
    # before any transcript arrives, pushing an empty user message. What we
    # tighten instead is the turn analyzer's own silence fallback (defaults
    # to 3s) and restrict turn-start to VAD only, since a stray transcript
    # (e.g. echo bleed) starting a turn with no real VAD signal behind it is
    # what stalls things — that phantom turn then has to time out.
    turn_analyzer = LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=0.8))

    user_aggregator , assistant_aggregator = LLMContextAggregatorPair(
        context=context,
    )


    # main pipeline 
    pipeline = Pipeline([
        transport.input() , 
        elevenlabs_stt, 
        user_aggregator , 
        aws_llm, 
        elevenlabs_tts, 
        transport.output() , 
        assistant_aggregator, 
    ]
    )

    worker = PipelineWorker(pipeline=pipeline) 

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport,client):
        logger.info("Client connected")
        if lead_context:
            # Outbound call: the agent speaks first, opening with the
            # personalized identity-confirmation greeting from the prompt.
            await worker.queue_frames([
                LLMMessagesAppendFrame(
                    messages=[{
                        "role": "user",
                        "content": "The call has connected. Open with your identity-confirmation greeting now.",
                    }],
                    run_llm=True,
                )
            ])

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
                    save_call_summary,
                    call_id,
                    session_id,
                    started_at,
                    ended_at,
                    transcript,
                    summary,
                    phone_number,
                    lead_context,
                )
                logger.info(f"Saved call summary for call {call_id}")
            except Exception:
                logger.exception(f"Failed to save call summary for call {call_id}")
    
    return pipeline , worker 

                                                                

