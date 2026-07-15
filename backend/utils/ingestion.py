import boto3 
from backend.core.config import * 
from langchain_postgres import PGEngine , PGVectorStore
from langchain_aws import BedrockEmbeddings 
from langchain_text_splitters import RecursiveCharacterTextSplitter 

text_splitter = RecursiveCharacterTextSplitter(
    
)


embeddings = BedrockEmbeddings(
    aws_access_key_id=AWS_ACCESS_KEY_ID, 
    aws_session_token=AWS_SESSION_TOKEN, 
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    model_id="amazon.titan-embed-text-v2:0",
)

pg_engine = PGEngine.from_connection_string(
    url=POSTGRES_URL, 
)

vector_store=PGVectorStore.create_sync(
    engine=pg_engine, 
    table_name="colca_faq", 
    embedding_service=embeddings
)


