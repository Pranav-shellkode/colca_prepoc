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

#POSTGRES 
POSTGRES_URL=os.getenv("POSTGRES_URL")
print(POSTGRES_URL) 

#DEEPGRAM FALLBACK
DEEPGRAM_API_KEY=os.getenv("DEEPGRAM_API_KEY")

# API key required by downstream applications calling the pre-call context
# and insights-getter endpoints (sent as `X-API-Key` header)
BACKEND_API_KEY=os.getenv("BACKEND_API_KEY","")


