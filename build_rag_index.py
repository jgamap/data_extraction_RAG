# build_rag_index.py
import os
from typing import List, Dict

from dotenv import load_dotenv
from openai import OpenAI
import chromadb

from tei_to_chunks import tei_dir_to_chunks

load_dotenv()
client = OpenAI()  # uses OPENAI_API_KEY from env

EMBEDDING_MODEL = "text-embedding-3-small"  # good & cheap; adjust as needed


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Get embeddings from OpenAI.
    """
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def build_chroma_collection(chunks: List[Dict], persist_dir: str = "./rag_db", collection_name: str = "papers"):
    client_chroma = chromadb.PersistentClient(path=persist_dir)
    collection = client_chroma.get_or_create_collection(name=collection_name)

    # Insert in manageable batches
    batch_size = 128
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        ids = [c["id"] for c in batch]
        texts = [c["text"] for c in batch]
        metadatas = [c["metadata"] for c in batch]
        embeddings = embed_texts(texts)

        collection.upsert(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)

    print(f"Stored {len(chunks)} chunks in Chroma collection '{collection_name}' at {persist_dir}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build RAG index from TEI files")
    parser.add_argument("--tei_dir", type=str, required=True, help="Directory with TEI XML files")
    parser.add_argument("--persist_dir", type=str, default="./rag_db", help="Directory for Chroma persistence")
    parser.add_argument("--collection", type=str, default="papers", help="Collection name")
    args = parser.parse_args()

    chunks = tei_dir_to_chunks(args.tei_dir)
    print(f"Loaded {len(chunks)} text chunks from TEI")
    build_chroma_collection(chunks, persist_dir=args.persist_dir, collection_name=args.collection)


# Usage
# python build_rag_index.py --tei_dir ./tei --persist_dir ./rag_db --collection papers