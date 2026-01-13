# query_rag.py
#
# RAG query functions:
# - retrieve_context: get top-k chunks from Chroma
# - answer_query: LLM answer using those chunks
# - answer_query_with_context: returns both answer AND the chunks (for proof-reading)

from typing import List, Dict, Tuple

from dotenv import load_dotenv
from openai import OpenAI
import chromadb

load_dotenv()
client = OpenAI()

RAG_EMBED_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4.1-mini"  # adjust if you prefer another model


# -----------------------------
# Embedding + retrieval
# -----------------------------

def embed_query(query: str) -> List[float]:
    response = client.embeddings.create(
        model=RAG_EMBED_MODEL,
        input=[query],
    )
    return response.data[0].embedding


def get_collection(persist_dir: str = "./rag_db", collection_name: str = "papers"):
    client_chroma = chromadb.PersistentClient(path=persist_dir)
    return client_chroma.get_collection(name=collection_name)


def retrieve_context(
    query: str,
    persist_dir: str = "./rag_db",
    collection_name: str = "papers",
    k: int = 5,
) -> List[Dict]:
    """
    Retrieve top-k relevant chunks from the vector store.

    Returns a list of dicts with:
        {
            "id": str,
            "text": str,
            "metadata": { ... }  # paper_id, title, section, etc.
        }
    """
    collection = get_collection(persist_dir, collection_name)
    query_embedding = embed_query(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
    )

    contexts: List[Dict] = []
    for doc_id, doc_text, metadata in zip(
        results["ids"][0], results["documents"][0], results["metadatas"][0]
    ):
        contexts.append(
            {
                "id": doc_id,
                "text": doc_text,
                "metadata": metadata,
            }
        )
    return contexts


# -----------------------------
# Prompt building
# -----------------------------

def build_prompt(query: str, contexts: List[Dict]) -> List[Dict]:
    """
    Construct the chat messages for the LLM.

    We pre-label each context chunk as [S1], [S2], ... so we
    can directly link answer statements to *our* known chunks.

    Note: we do NOT ask the LLM to generate a "Sources" section.
    That part can be done programmatically outside the model.
    """

    context_blocks = []
    for i, ctx in enumerate(contexts, start=1):
        m = ctx["metadata"]
        label = f"[S{i}]"
        title = m.get("title", "").strip()
        section = m.get("section", "")
        section_info = f" (section: {section})" if section else ""
        header = f"{label} {m.get('paper_id', 'unknown')} – {title}{section_info}"

        context_blocks.append(
            f"{header}\n"
            f"Chunk text:\n{ctx['text']}\n"
        )

    system_prompt = (
        "You are a rigorous scientific assistant.\n"
        "You must answer ONLY using the provided context chunks from scientific articles.\n"
        "If the answer is not contained in the context, say you do not know.\n\n"
        "When you make a factual statement that is supported by a chunk, "
        "cite it inline using [S1], [S2], etc., corresponding to the chunk labels.\n"
        "Do not fabricate new sources, DO NOT invent citation labels, and do not mention any documents "
        "that are not labeled [S1], [S2], etc.\n"
        "You do NOT need to list a separate 'Sources' section; the caller will handle that.\n"
    )

    user_prompt = (
        "User question:\n"
        f"{query}\n\n"
        "Context from scientific articles:\n"
        + "\n".join(context_blocks)
        + "\n\n"
        "Answer the question as precisely and concisely as possible. "
        "If you are unsure or the information is incomplete, clearly say so."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return messages


# -----------------------------
# Answer functions
# -----------------------------

def llm_answer_from_contexts(query: str, contexts: List[Dict]) -> str:
    """
    Low-level function: given a query and a set of context chunks,
    ask the LLM to produce an answer.

    Returns answer text only.
    """
    if not contexts:
        return "No relevant documents found in the RAG index."

    messages = build_prompt(query, contexts)
    completion = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        temperature=0.3,
    )
    return completion.choices[0].message.content


def answer_query(
    query: str,
    persist_dir: str = "./rag_db",
    collection_name: str = "papers",
    k: int = 5,
) -> str:
    """
    Original-style function: return ONLY the answer text.

    Keeps backwards compatibility with existing code.
    """
    contexts = retrieve_context(
        query=query,
        persist_dir=persist_dir,
        collection_name=collection_name,
        k=k,
    )
    return llm_answer_from_contexts(query, contexts)


def answer_query_with_context(
    query: str,
    persist_dir: str = "./rag_db",
    collection_name: str = "papers",
    k: int = 5,
) -> Tuple[str, List[Dict]]:
    """
    New function: returns BOTH answer text and the actual context chunks used.

    This is ideal for:
      - proof-reading,
      - UI display,
      - debugging hallucinations.
    """
    contexts = retrieve_context(
        query=query,
        persist_dir=persist_dir,
        collection_name=collection_name,
        k=k,
    )
    answer = llm_answer_from_contexts(query, contexts)
    return answer, contexts


# -----------------------------
# Optional: simple CLI for debugging
# -----------------------------

def pretty_print_contexts(contexts: List[Dict]) -> None:
    """
    Utility function to print retrieved chunks with labels matching [S1], [S2], ...
    """
    for i, ctx in enumerate(contexts, start=1):
        m = ctx["metadata"]
        print("=" * 80)
        print(f"[S{i}] {m.get('paper_id', 'unknown')} – {m.get('title', '').strip()}")
        if "section" in m:
            print(f"Section: {m['section']}")
        print(f"Chunk ID: {ctx['id']}")
        print("\nChunk text (truncated):\n")
        print(ctx["text"][:800], "...")
        print()


if __name__ == "__main__":
    # Simple interactive loop for manual debugging / proof-reading
    while True:
        try:
            q = input("\nAsk a question (or 'exit'): ").strip()
            if not q or q.lower() == "exit":
                break

            ans, ctxs = answer_query_with_context(q)
            print("\n=== Answer ===\n")
            print(ans)

            print("\n=== Retrieved Context Chunks ===\n")
            pretty_print_contexts(ctxs)

        except KeyboardInterrupt:
            break
