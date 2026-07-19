import asyncio
import logging 
import uuid 
import boto3
from datetime import datetime,timezone 

from pipecat.transcriptions.language import Language
from pipecat.audio.mixers.soundfile_mixer import SoundfileMixer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams , PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair , LLMAssistantAggregatorParams , LLMUserAggregatorParams
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.services.aws.llm import AWSBedrockLLMService , AWSBedrockLLMSettings
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService,CommitStrategy,ElevenLabsRealtimeSTTSettings
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService,ElevenLabsTTSSettings
from pipecat.frames.frames import LLMMessagesAppendFrame, TTSSpeakFrame, MixerEnableFrame
from pipecat.processors.aggregators import async_tool_messages


from backend.core.config import *
from backend.agents.prompt import colca_sales_agent_prompt
from backend.utils.call_summary import summarize_call
from backend.utils.call_store import save_call_summary
from backend.agents.tools.retrieval_tool import retrieve_colca_faq

logger = logging.getLogger(__name__) 

def build_kb_search_mixer() -> SoundfileMixer:
    """A fresh mixer per call — SoundfileMixer holds live per-call playback
    state (whether it's mixing, its position in the sound file), so sharing
    one instance across concurrent calls would leak one call's KB-search
    sound into every other call using the same mixer."""
    return SoundfileMixer(
        sound_files={
            "typing": "backend/assets/kb_search_audio.wav",
        },
        default_sound="typing",
        volume=0.4,
        mixing=False,
    )

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


    # ElevenLabs' own server-side VAD drives speech segmentation end to end —
    # no local Pipecat VAD analyzer runs alongside it, so there's only one
    # noise-sensitivity knob to tune instead of two fighting each other.
    # vad_threshold is *inverted* (lower = more sensitive), so it's raised
    # well above the ElevenLabs default to reject background noise; longer
    # min_speech/min_silence durations reject brief noise blips and require
    # a real pause before committing a segment.
    elevenlabs_stt = ElevenLabsRealtimeSTTService(
        api_key=ELEVENLABS_API_KEY,
        commit_strategy=CommitStrategy.VAD,
        settings=ElevenLabsRealtimeSTTSettings(
            language=Language.EN,
            vad_threshold=0.7,
            vad_silence_threshold_secs=0.4,
            min_speech_duration_ms=250,
            min_silence_duration_ms=400,
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

    context = LLMContext(
        tools=[retrieve_colca_faq] ,
    )

    # No local Pipecat VAD analyzer is used — turn detection is driven purely
    # by ElevenLabs' committed transcripts. MinWordsUserTurnStartStrategy
    # requires several words to interrupt the bot mid-speech (a stray noise
    # blip or "mm-hmm" backchannel won't cut the bot off) but still lets a
    # real interruption ("stop", "wait", a full sentence) through — unlike
    # AlwaysUserMuteStrategy, which was tried here first but blocks ALL mic
    # input while the bot talks, including genuine "stop" commands. Only a
    # single word is needed to start a turn when the bot is silent, so normal
    # replies aren't delayed. SpeechTimeoutUserTurnStopStrategy's fallback
    # path (no VAD frames arrive here) treats a quiet period after the last
    # transcript as end-of-turn.
    user_aggregator , assistant_aggregator = LLMContextAggregatorPair(
        context=context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                start=[MinWordsUserTurnStartStrategy(min_words=3)],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.8)],
            ),
        ),
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

        # Async tool-call bookkeeping messages (role "tool"/"developer" with a
        # JSON-encoded {"type": "async_tool", ...} payload in `content`) are
        # protocol plumbing for the LLM, not conversation — async_tool_messages
        # is pipecat's own parser for this shape, since `type` lives inside the
        # JSON string, not as a top-level key `m.get("type")` would ever see.
        transcript = "\n".join(
            f"{m['role']}: {m['content']}"
            for m in msgs
            if (
                m.get("role") != "system"
                and async_tool_messages.parse_message(m) is None
                and m.get("content") is not None
            )
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
    
    @aws_llm.event_handler("on_function_calls_started")
    async def on_function_calls_started(service,function_calls):
        await elevenlabs_tts.queue_frame(TTSSpeakFrame("Let me check on that. Please hold",append_to_context=False))
        await aws_llm.queue_frame(MixerEnableFrame(enable=True))

    @user_aggregator.event_handler("on_user_turn_stop_timeout")
    async def on_user_turn_stop_timeout(aggregator):
        msg = {
            "role" : "developer" , 
            "content" : "Sorry I can't hear you , Politely ask if they are still there", 
        } 
        await aggregator.queue_frame(LLMMessagesAppendFrame([msg],run_llm=True))


    return pipeline , worker 

                                                                

