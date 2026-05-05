from fastapi import FastAPI
from qdrant_client import QdrantClient
import httpx
import os
import time

app = FastAPI()

START_TIME = time.time()
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "docs")


@app.get("/health")
async def health():
    checks = {}

    # qdrant connectivity + collection check
    try:
        client = QdrantClient(url=QDRANT_URL)
        info = client.get_collection(COLLECTION)
        checks["qdrant"] = {
            "status": "ok",
            "vectors_count": info.vectors_count,
            "indexed_vectors": info.indexed_vectors_count,
        }
    except Exception as e:
        checks["qdrant"] = {"status": "error", "detail": str(e)}

    # openai reachability
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.openai.com")
            checks["openai"] = {"status": "ok" if r.status_code < 500 else "degraded"}
    except Exception as e:
        checks["openai"] = {"status": "error", "detail": str(e)}

    # cohere reachability
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
    uvicorn.run(app, host="0.0.0.0", port=8001)