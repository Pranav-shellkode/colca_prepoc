import os 
from pathlib import Path 
from dotenv import load_dotenv 


load_dotenv(Path(__file__).resolve().parents[2]/".env")

# eleven labs configs 
ELEVENLABS_API_KEY=os.getenv("ELEVENLABS_API_KEY","")
ELEVENLABS_VOICE_ID=os.getenv("ELEVENLABS_VOICE_ID","")

# aws creds
AWS_ACCESS_KEY_ID=os.getenv("aws_access_key_id","")
AWS_SECRET_ACCESS_KEY=os.getenv("aws_secret_access_key")
AWS_SESSION_TOKEN=os.getenv("aws_session_token","")
AWS_REGION="us-east-1"

#POSTGRES 
POSTGRES_URL=os.getenv("POSTGRES_URL")

#DEEPGRAM FALLBACK
DEEPGRAM_API_KEY=os.getenv("DEEPGRAM_API_KEY")

# API key required by downstream applications calling the pre-call context
# and insights-getter endpoints (sent as `X-API-Key` header)
BACKEND_API_KEY=os.getenv("BACKEND_API_KEY","")


GROQ_API_KEY=os.getenv("GROQ_API_KEY")

# Ozonetel outbound telephony
OZONETEL_URL=os.getenv("OZONETEL_URL","http://in1-cpaas.ozonetel.com/outbound/outbound.php")
OZONETEL_HANGUP_URL=os.getenv("OZONETEL_HANGUP_URL","https://in1-ccaas-api.ozonetel.com/api/v1/CallControl/Disconnect")
OZONETEL_API_KEY=os.getenv("OZONETEL_API_KEY","")
OZONETEL_SIP_NUMBER=os.getenv("OZONETEL_SIP_NUMBER","")
OZONETEL_DID=os.getenv("OZONETEL_DID","")
# Public host:port this server is reachable at, used to build the /ozonetel/hook,
# /ozonetel/callback, and /ws URLs handed to Ozonetel (e.g. "1.2.3.4:8000").
WEBHOOK_ENDPOINT=os.getenv("WEBHOOK_ENDPOINT","")


