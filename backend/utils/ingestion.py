import boto3
from backend.core.config import *
from langchain_postgres import PGEngine, PGVectorStore
from langchain_aws import BedrockEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader

PDF_PATH = "/home/pranav/Downloads/colca_faq.pdf"

loader = PyPDFLoader(PDF_PATH)
raw_docs = loader.load()  # one Document per page, with page_content + metadata

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=120,
    separators=["\n\n", "\n", ". ", " ", ""],
)
docs = text_splitter.split_documents(raw_docs)

for i, doc in enumerate(docs):
    doc.metadata["source"] = "colca_ai_faq"
    doc.metadata["chunk_id"] = i

print(f"Loaded {len(raw_docs)} pages -> split into {len(docs)} chunks")

embeddings = BedrockEmbeddings(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_session_token=AWS_SESSION_TOKEN,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    model_id="amazon.titan-embed-text-v2:0",
)

pg_engine = PGEngine.from_connection_string(url=POSTGRES_URL)

TABLE_NAME = "colca_faq"

try:
    pg_engine.init_vectorstore_table(
        table_name=TABLE_NAME,
        vector_size=1024,
    )
except Exception as e:
    print(f"Table init skipped (likely already exists): {e}")

vector_store = PGVectorStore.create_sync(
    engine=pg_engine,
    table_name=TABLE_NAME,
    embedding_service=embeddings,
)

ids = vector_store.add_documents(docs)
print(f"Ingested {len(ids)} chunks into '{TABLE_NAME}'")