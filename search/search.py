import os
import hashlib
import json
import httpx
import psycopg2
import cohere
import valkey
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/docs")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", 6379))

EMBEDDING_MODEL = "nomic-embed-text"
VECTOR_DIM = 512
CACHE_TTL = 3600  # 1 hour

co = cohere.Client(COHERE_API_KEY)
vk = valkey.Valkey(host=VALKEY_HOST, port=VALKEY_PORT)


@dataclass
class SearchResult:
    text: str
    source_url: str
    heading: str
    doc_version: str
    product_area: str
    score: float


def get_conn():
    return psycopg2.connect(POSTGRES_URL)


def embed_query(query: str) -> list[float]:
    resp = httpx.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBEDDING_MODEL, "prompt": query},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embedding"][:VECTOR_DIM]


def dense_search(embedding: list[float], filters: dict, limit: int = 20) -> list[dict]:
    """pgvector cosine similarity search."""
    where, params = build_filters(filters)
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"

    query = f"""
        SELECT id, text, source_url, heading, doc_version, product_area,
               1 - (embedding <=> %s::vector) AS score
        FROM doc_chunks
        {where}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(query, (vec_str, vec_str, *params, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def sparse_search(query: str, filters: dict, limit: int = 20) -> list[dict]:
    """Postgres tsvector full-text search."""
    where, params = build_filters(filters)
    where = ("WHERE " if not where else where + " AND ") + "fts_vector @@ plainto_tsquery('english', %s)"

    sql = f"""
        SELECT id, text, source_url, heading, doc_version, product_area,
               ts_rank(fts_vector, plainto_tsquery('english', %s)) AS score
        FROM doc_chunks
        {where}
        ORDER BY score DESC
        LIMIT %s;
    """

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (query, *params, query, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def reciprocal_rank_fusion(
    dense: list[dict], sparse: list[dict], k: int = 60
) -> list[dict]:
    """Merge two ranked lists into one using RRF."""
    scores: dict[str, dict] = {}

    for rank, row in enumerate(dense):
        id_ = row["id"]
        scores[id_] = {"row": row, "score": scores.get(id_, {}).get("score", 0) + 1 / (k + rank + 1)}

    for rank, row in enumerate(sparse):
        id_ = row["id"]
        scores[id_] = {"row": row, "score": scores.get(id_, {}).get("score", 0) + 1 / (k + rank + 1)}

    return [v["row"] for v in sorted(scores.values(), key=lambda x: x["score"], reverse=True)]


def rerank(query: str, candidates: list[dict], top_n: int = 5) -> list[SearchResult]:
    """Cohere rerank over fused candidates."""
    texts = [c["text"] for c in candidates]
    results = co.rerank(
        model="rerank-english-v3.0",
        query=query,
        documents=texts,
        top_n=top_n,
    )
    return [
        SearchResult(
            text=texts[r.index],
            source_url=candidates[r.index]["source_url"],
            heading=candidates[r.index]["heading"],
            doc_version=candidates[r.index]["doc_version"],
            product_area=candidates[r.index]["product_area"],
            score=r.relevance_score,
        )
        for r in results.results
    ]


def search(
    query: str,
    doc_version: str | None = None,
    product_area: str | None = None,
    top_n: int = 5,
) -> list[SearchResult]:
    # check cache first
    cache_key = f"search:{hashlib.md5(f'{query}{doc_version}{product_area}'.encode()).hexdigest()}"
    cached = vk.get(cache_key)
    if cached:
        data = json.loads(cached)
        return [SearchResult(**r) for r in data]

    filters = {}
    if doc_version:
        filters["doc_version"] = doc_version
    if product_area:
        filters["product_area"] = product_area

    # 1. embed query
    embedding = embed_query(query)

    # 2. run both searches
    dense = dense_search(embedding, filters)
    sparse = sparse_search(query, filters)

    # 3. fuse
    fused = reciprocal_rank_fusion(dense, sparse)[:15]

    if not fused:
        return []

    # 4. rerank
    results = rerank(query, fused, top_n=top_n)

    # 5. cache results
    vk.setex(cache_key, CACHE_TTL, json.dumps([r.__dict__ for r in results]))

    return results


def build_filters(filters: dict) -> tuple[str, list]:
    """Build a WHERE clause from a filters dict."""
    if not filters:
        return "", []
    clauses = [f"{k} = %s" for k in filters]
    return "WHERE " + " AND ".join(clauses), list(filters.values())