import os
import uuid
import httpx
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
from dotenv import load_dotenv
from ingestion.chunker import Chunk

load_dotenv()

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/docs")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = "nomic-embed-text"
VECTOR_DIM = 512  # matryoshka truncation


def get_conn():
    return psycopg2.connect(POSTGRES_URL)


def ensure_table():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS doc_chunks (
                id UUID PRIMARY KEY,
                text TEXT NOT NULL,
                source_url TEXT,
                heading TEXT,
                doc_version TEXT,
                product_area TEXT,
                has_code BOOLEAN,
                embedding vector({VECTOR_DIM}),
                fts_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
                indexed_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        # HNSW index for fast cosine similarity
        cur.execute("""
            CREATE INDEX IF NOT EXISTS doc_chunks_embedding_idx
            ON doc_chunks
            USING hnsw (embedding vector_cosine_ops);
        """)
        # GIN index for full-text search
        cur.execute("""
            CREATE INDEX IF NOT EXISTS doc_chunks_fts_idx
            ON doc_chunks
            USING gin(fts_vector);
        """)
        conn.commit()
    print("Table and indexes ready.")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Call Ollama to embed a batch of texts."""
    embeddings = []
    for text in texts:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        full_vec = resp.json()["embedding"]
        embeddings.append(full_vec[:VECTOR_DIM])  # truncate to 512
    return embeddings


def embed_and_store(chunks: list[Chunk]):
    texts = [c.text for c in chunks]
    embeddings = embed_texts(texts)

    rows = [
        (
            str(uuid.uuid4()),
            chunk.text,
            chunk.source_url,
            chunk.heading,
            chunk.doc_version,
            chunk.product_area,
            chunk.has_code,
            embedding,
        )
        for chunk, embedding in zip(chunks, embeddings)
    ]

    with get_conn() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO doc_chunks
                (id, text, source_url, heading, doc_version, product_area, has_code, embedding)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
            """,
            rows,
        )
        conn.commit()