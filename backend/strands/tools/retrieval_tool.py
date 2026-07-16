from strands import tool
from langchain_postgres import PGEngine, PGVectorStore
from langchain_aws import BedrockEmbeddings
from backend.core.config import *
from pipecat.services.llm_service import FunctionCallParams

TABLE_NAME = "colca_faq"

# Initialize once at module load, reused across tool calls
_embeddings = BedrockEmbeddings(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_session_token=AWS_SESSION_TOKEN,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    model_id="amazon.titan-embed-text-v2:0",
)

_pg_engine = PGEngine.from_connection_string(url=POSTGRES_URL)

_vector_store = PGVectorStore.create_sync(
    engine=_pg_engine,
    table_name=TABLE_NAME,
    embedding_service=_embeddings,
)


@tool
def retrieve_colca_faq(query: str, k: int = 4) -> str:
    """
    Retrieve relevant Colca AI FAQ context to answer a lead's question about
    Colca AI's products (Compose, Converse, Connect), pricing, security,
    onboarding, or objections raised during a sales conversation.

    Args:
        query: The lead's question or the topic to search for.
        k: Number of relevant chunks to retrieve (default 4).

    Returns:
        A formatted string of the most relevant FAQ chunks, or a message
        indicating nothing relevant was found.
    """
    results = _vector_store.similarity_search(query, k=k)

    if not results:
        return "No relevant information found in the Colca AI FAQ knowledge base."

    formatted = []
    for i, doc in enumerate(results, start=1):
        formatted.append(f"[{i}] {doc.page_content.strip()}")

    return "\n\n".join(formatted)