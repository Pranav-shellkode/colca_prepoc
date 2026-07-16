import json

import boto3

from backend.core.config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN

MODEL_ID = "us.anthropic.claude-sonnet-4-6"

SUMMARY_TOOL = {
    "toolSpec": {
        "name": "record_call_summary",
        "description": "Record a structured summary of the sales call.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "A concise free-text summary of the call.",
                    },
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The key points discussed during the call.",
                    },
                    "meeting_booked": {
                        "type": "boolean",
                        "description": "Whether a discovery meeting was booked.",
                    },
                    "meeting_time": {
                        "type": ["string", "null"],
                        "description": "The agreed meeting time, or null if none was booked.",
                    },
                    "lead_sentiment": {
                        "type": "string",
                        "enum": ["positive", "neutral", "negative"],
                        "description": "The prospect's overall sentiment during the call.",
                    },
                    "next_steps": {
                        "type": "string",
                        "description": "The agreed next steps following the call.",
                    },
                },
                "required": [
                    "summary",
                    "key_points",
                    "meeting_booked",
                    "meeting_time",
                    "lead_sentiment",
                    "next_steps",
                ],
            }
        },
    }
}


def _bedrock_client():
    session = boto3.Session(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        aws_session_token=AWS_SESSION_TOKEN,
    )
    return session.client("bedrock-runtime")


def summarize_call(transcript: str) -> dict:
    """
    Summarize a sales call transcript into a structured dict via a plain
    Bedrock converse call (independent of the sales agent).
    """
    client = _bedrock_client()

    response = client.converse(
        modelId=MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "Summarize the following sales call transcript by "
                            "calling the record_call_summary tool.\n\n"
                            f"Transcript:\n{transcript}"
                        )
                    }
                ],
            }
        ],
        toolConfig={
            "tools": [SUMMARY_TOOL],
            "toolChoice": {"tool": {"name": "record_call_summary"}},
        },
    )

    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]

    raise ValueError(f"Model did not return a record_call_summary tool call: {json.dumps(response)}")
