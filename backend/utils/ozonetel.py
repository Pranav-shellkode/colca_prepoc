"""Ozonetel CPaaS REST helpers for outbound calling.

Ozonetel has no SDK — every operation is a plain GET request with query
params. This module covers the three call-control operations the app needs:
triggering an outbound dial, disconnecting an active call, and mapping the
final CDR's `telco_code` to an internal call outcome.
"""

import logging

import requests

from backend.core.config import (
    OZONETEL_API_KEY,
    OZONETEL_DID,
    OZONETEL_HANGUP_URL,
    OZONETEL_SIP_NUMBER,
    OZONETEL_URL,
)

logger = logging.getLogger(__name__)

# Maps Ozonetel's `telco_code` (from the /ozonetel/callback CDR) to an
# internal call outcome. Codes not present here fall back to "COMPLETED" if
# the call was picked up (pick_time set) or "NOT_ANSWERED" otherwise.
TELCO_STATUS_MAP = {
    "16": "COMPLETED",
    "17": "BUSY",
    "18": "NOT_ANSWERED",
    "19": "NOT_ANSWERED",
    "20": "NOT_ANSWERED",
    "31": "NOT_ANSWERED",
    "34": "NOT_ANSWERED",
    "41": "NOT_ANSWERED",
    "42": "NOT_ANSWERED",
    "44": "NOT_ANSWERED",
    "47": "NOT_ANSWERED",
    "38": "NETWORK_OUT_OF_ORDER",
    "39": "CONNECTION_OUT_OF_SERVICE",
    "205": "USER_DISCONNECTED",
    "1": "INVALID_NUMBER",
    "21": "FAILED",
    "22": "FAILED",
    "52": "FAILED",
    "54": "FAILED",
    "200": "FAILED",
    "201": "FAILED",
    "203": "FAILED",
    "9995": "FAILED",
    "9999": "FAILED",
    "28": "INVALID_NUMBER_FORMAT",
}


def resolve_telco_status(telco_code: str | None, pick_time: str | None) -> str:
    """Map a callback's telco_code (+ whether the call was picked up) to an outcome."""
    if telco_code in TELCO_STATUS_MAP:
        return TELCO_STATUS_MAP[telco_code]
    return "COMPLETED" if pick_time else "NOT_ANSWERED"


def trigger_outbound_call(phone_no: str, call_id: str, webhook_host: str) -> requests.Response:
    """Place an outbound call via Ozonetel, routing lifecycle events back to this app.

    Args:
        phone_no: Destination number to dial.
        call_id: This app's call correlation id — echoed back by Ozonetel as
            `extra_data` on the /ozonetel/hook NewCall event, so the hook
            handler can look up the right lead_context/pipeline session.
        webhook_host: Public host:port this server is reachable at (e.g.
            "1.2.3.4:8000"), used to build the hook/callback URLs handed to
            Ozonetel.
    """
    params = {
        "phone_no": phone_no,
        "api_key": OZONETEL_API_KEY,
        "outbound_version": 2,
        "extra_data": call_id,
        "record": "true",
        "url": f"http://{webhook_host}/ozonetel/hook",
        "callback_url": f"http://{webhook_host}/ozonetel/callback",
    }
    response = requests.get(OZONETEL_URL, params=params, timeout=10)
    logger.info(f"Ozonetel outbound dial for call_id={call_id}: HTTP {response.status_code}")
    return response


def disconnect_call(sid: str, phone_no: str, did: str | None = None) -> requests.Response:
    """Disconnect an active call by Ozonetel's own call SID (not our call_id)."""
    params = {
        "ucid": sid,
        "api_key": OZONETEL_API_KEY,
        "did": did or OZONETEL_DID,
        "phoneno": phone_no,
    }
    response = requests.get(OZONETEL_HANGUP_URL, params=params, timeout=10)
    logger.info(f"Ozonetel disconnect for sid={sid}: HTTP {response.status_code}")
    return response


def build_stream_xml(webhook_host: str, call_id: str) -> str:
    """Build the NewCall hook response XML that tells Ozonetel to open the media websocket."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<response><start-record/><stream is_sip="true" '
        f'url="ws://{webhook_host}/ws?provider=ozonetel&amp;call_id={call_id}">'
        f"{OZONETEL_SIP_NUMBER}</stream></response>"
    )
