from strands import Agent 
from strands.models import BedrockModel 

bedrock_model = BedrockModel( 
    model_id="us.anthropic.claude-sonnet-4.6",
    temperature=0.3,
    region_name="us-east-1", 
)

agent = Agent(
    model=bedrock_model, 
    system_prompt=
)