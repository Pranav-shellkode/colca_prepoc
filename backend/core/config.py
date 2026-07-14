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



