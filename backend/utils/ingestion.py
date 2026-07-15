import boto3
from backend.core.config import *
from langchain_postgres import PGEngine, PGVectorStore
from langchain_aws import BedrockEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader

# ---- 1. Load the source PDF ----
PDF_PATH = "/home/pranav/Downloads/colca_faq.pdf"

loader = PyPDFLoader(PDF_PATH)
raw_docs = loader.load()  # one Document per page, with page_content + metadata

# ---- 2. Split into chunks ----
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=120,
    separators=["\n\n", "\n", ". ", " ", ""],
)
docs = text_splitter.split_documents(raw_docs)

# tag each chunk with source metadata (useful for citing back to the FAQ later)
for i, doc in enumerate(docs):
    doc.metadata["source"] = "colca_ai_faq"
    doc.metadata["chunk_id"] = i

print(f"Loaded {len(raw_docs)} pages -> split into {len(docs)} chunks")

# ---- 3. Embeddings ----
embeddings = BedrockEmbeddings(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_session_token=AWS_SESSION_TOKEN,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    model_id="amazon.titan-embed-text-v2:0",
)

# ---- 4. PGEngine + table setup ----
pg_engine = PGEngine.from_connection_string(url=POSTGRES_URL)

TABLE_NAME = "colca_faq"

# Only needs to run once - creates the table with the right vector dimension.
# Titan Embed Text v2 defaults to 1024 dims. Safe to leave this in; it will
# raise if the table already exists, so wrap in try/except for reruns.
try:
    pg_engine.init_vectorstore_table(
        table_name=TABLE_NAME,
        vector_size=1024,
    )
except Exception as e:
    print(f"Table init skipped (likely already exists): {e}")

# ---- 5. Vector store ----
vector_store = PGVectorStore.create_sync(
    engine=pg_engine,
    table_name=TABLE_NAME,
    embedding_service=embeddings,
)

# ---- 6. Ingest documents ----
ids = vector_store.add_documents(docs)
print(f"Ingested {len(ids)} chunks into '{TABLE_NAME}'")