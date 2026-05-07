from fastapi import FastAPI
from dotenv import load_dotenv
import psycopg2
import valkey
import httpx
import os
import time

load_dotenv()

app = FastAPI()
START_TIME = time.time()

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/docs")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", 6379))


@app.get("/health")
async def health():
    checks = {}

    # postgres
    try:
        conn = psycopg2.connect(POSTGRES_URL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM doc_chunks;")
        count = cur.fetchone()[0]
        conn.close()
        checks["postgres"] = {"status": "ok", "chunk_count": count}
    except Exception as e:
        checks["postgres"] = {"status": "error", "detail": str(e)}

    # valkey
    try:
        vk = valkey.Valkey(host=VALKEY_HOST, port=VALKEY_PORT)
        vk.ping()
        checks["valkey"] = {"status": "ok"}
    except Exception as e:
        checks["valkey"] = {"status": "error", "detail": str(e)}

    # ollama
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            has_model = any("nomic-embed-text" in m for m in models)
            checks["ollama"] = {
                "status": "ok" if has_model else "degraded",
                "nomic_embed_text": has_model,
            }
    except Exception as e:
        checks["ollama"] = {"status": "error", "detail": str(e)}

    # cohere
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.cohere.com")
            checks["cohere"] = {"status": "ok" if r.status_code < 500 else "degraded"}
    except Exception as e:
        checks["cohere"] = {"status": "error", "detail": str(e)}

    all_ok = all(v["status"] == "ok" for v in checks.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "uptime_seconds": round(time.time() - START_TIME),
        "checks": checks,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=18001)