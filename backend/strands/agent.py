import boto3
from strands import Agent 
from strands.models import BedrockModel 
from backend.strands.prompt import colca_sales_agent_prompt 
from backend.core.config import * 
from backend.strands.tools.retrieval_tool import retrieve_colca_faq

def build_agent(lead_context: dict | None = None) -> Agent:

    bedrock_session = boto3.Session(
        aws_access_key_id=AWS_ACCESS_KEY_ID ,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        aws_session_token=AWS_SESSION_TOKEN
    )

    bedrock_model = BedrockModel(
        boto_session=bedrock_session,
        model_id="us.anthropic.claude-sonnet-4-6",
        temperature=0.3,
    )

    return Agent(
        model=bedrock_model,
        system_prompt=colca_sales_agent_prompt(lead_context) ,
        tools = [retrieve_colca_faq],
    )