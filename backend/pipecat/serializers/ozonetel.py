"""Ozonetel CPaaS media-stream serializer for Pipecat.

Ozonetel's outbound-call media bridge speaks JSON text frames both ways over
a single websocket, carrying raw signed 16-bit PCM samples as a plain int
array (never base64, never a codec like mu-law) at a fixed 8kHz mono. See:
http://in1-cpaas.ozonetel.com (CPaaS outbound + streaming docs).

Wire protocol (reverse-engineered from a known-working integration):

Inbound (Ozonetel -> us):
    {"event": "media", "data": {"samples": [int16, ...], "sampleRate": 8000}}
    {"event": "start"}
    {"event": "stop"}

Outbound (us -> Ozonetel):
    {
        "type": "media",
        "ucid": "<call id>",
        "data": {
            "samples": [int16, ...],
            "bitsPerSample": 16,
            "sampleRate": 8000,
            "channelCount": 1,
            "numberOfFrames": <len(samples)>,
            "type": "data",
        },
    }

Barge-in (us -> Ozonetel, on pipeline InterruptionFrame):
    {"command": "clearBuffer"}
"""

import json
import struct

from loguru import logger

from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer


class OzonetelFrameSerializer(FrameSerializer):
    """Serializer for Ozonetel's CPaaS outbound media-stream protocol."""

    class InputParams(FrameSerializer.InputParams):
        """Configuration parameters for OzonetelFrameSerializer.

        Parameters:
            ozonetel_sample_rate: Wire sample rate used by Ozonetel, fixed at 8000 Hz.
            sample_rate: Optional override for the pipeline's input sample rate.
        """

        ozonetel_sample_rate: int = 8000
        sample_rate: int | None = None

    def __init__(self, ucid: str, params: InputParams | None = None):
        """Initialize the OzonetelFrameSerializer.

        Args:
            ucid: The call correlation id Ozonetel echoes back as `extra_data`
                on the outbound-dial trigger; sent back on every outbound
                media message.
            params: Configuration parameters.
        """
        params = params or OzonetelFrameSerializer.InputParams()
        super().__init__(params)
        self._params: OzonetelFrameSerializer.InputParams = params

        self._ucid = ucid
        self._ozonetel_sample_rate = self._params.ozonetel_sample_rate
        self._sample_rate = 0  # Pipeline input rate, resolved in setup()

        self._input_resampler = create_stream_resampler(
            clear_after_secs=self._params.resampler_clear_after_secs
        )
        self._output_resampler = create_stream_resampler(
            clear_after_secs=self._params.resampler_clear_after_secs
        )

    async def setup(self, frame: StartFrame):
        """Sets up the serializer with pipeline configuration.

        Args:
            frame: The StartFrame containing pipeline configuration.
        """
        self._sample_rate = self._params.sample_rate or frame.audio_in_sample_rate

    async def serialize(self, frame: Frame) -> str | bytes | None:
        """Serializes a Pipecat frame to an Ozonetel WebSocket message.

        Args:
            frame: The Pipecat frame to serialize.

        Returns:
            Serialized data as a JSON string, or None if the frame isn't
            handled or didn't produce a complete chunk yet.
        """
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"command": "clearBuffer"})
        elif isinstance(frame, AudioRawFrame):
            resampled = await self._output_resampler.resample(
                frame.audio, frame.sample_rate, self._ozonetel_sample_rate
            )
            if not resampled:
                return None

            # Send whatever the resampler produced for this frame as-is —
            # no fixed-size rechunking. Buffering to a fixed chunk size (e.g.
            # Ozonetel's own 800-sample/100ms convention) would strand the
            # trailing partial chunk of every bot utterance until more audio
            # arrives to top it up, which either delays it into the next
            # utterance or drops it if the call ends first.
            num_samples = len(resampled) // 2
            samples = struct.unpack(f"<{num_samples}h", resampled[: num_samples * 2])
            message = {
                "type": "media",
                "ucid": self._ucid,
                "data": {
                    "samples": list(samples),
                    "bitsPerSample": 16,
                    "sampleRate": self._ozonetel_sample_rate,
                    "channelCount": 1,
                    "numberOfFrames": len(samples),
                    "type": "data",
                },
            }
            return json.dumps(message)
        elif isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            if self.should_ignore_frame(frame):
                return None
            return json.dumps(frame.message)

        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        """Deserializes Ozonetel WebSocket data to a Pipecat frame.

        Args:
            data: The raw WebSocket data from Ozonetel.

        Returns:
            An InputAudioRawFrame for media events, or None for anything
            else (start/stop events, or a message with no audio yet).
        """
        try:
            message = json.loads(data)
        except (TypeError, ValueError):
            logger.warning(f"OzonetelFrameSerializer: could not decode message: {data!r}")
            return None

        event = message.get("event")

        if event == "media":
            samples = message.get("data", {}).get("samples")
            if not samples:
                return None

            payload = struct.pack(f"<{len(samples)}h", *samples)

            resampled = await self._input_resampler.resample(
                payload, self._ozonetel_sample_rate, self._sample_rate
            )
            if not resampled:
                return None

            return InputAudioRawFrame(
                audio=resampled,
                num_channels=1,
                sample_rate=self._sample_rate,
            )
        elif event in ("start", "stop"):
            # No corresponding Pipecat frame is needed for these today —
            # call lifecycle (answer/hangup) is handled by the /ozonetel
            # webhook routes, not the media socket itself.
            return None

        return None
