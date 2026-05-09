import os
import json
import psycopg2
import valkey
from dotenv import load_dotenv
from fastmcp import FastMCP
from search.search import search
from ingestion.embedder import get_conn

load_dotenv()

VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", 6379))

vk = valkey.Valkey(host=VALKEY_HOST, port=VALKEY_PORT)
mcp = FastMCP("orcta-docs")


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def search_docs(
    query: str,
    doc_version: str | None = None,
    product_area: str | None = None,
) -> list[dict]:
    """
    Search Orcta Tech internal documentation.
    Always call this before implementing anything that touches internal APIs,
    services, or patterns. Do not use external libraries if an internal
    equivalent exists in the docs.
    """
    results = search(query, doc_version=doc_version, product_area=product_area)
    return [
        {
            "heading": r.heading,
            "text": r.text,
            "source_url": r.source_url,
            "doc_version": r.doc_version,
            "product_area": r.product_area,
            "score": round(r.score, 4),
        }
        for r in results
    ]


@mcp.tool()
def get_page(source_url: str) -> dict:
    """
    Retrieve all chunks from a specific documentation page by its URL.
    Use this when you need the full context of a page rather than search snippets.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT heading, text, doc_version, product_area
            FROM doc_chunks
            WHERE source_url = %s
            ORDER BY indexed_at ASC;
            """,
            (source_url,),
        )
        rows = cur.fetchall()

    if not rows:
        return {"error": f"No chunks found for URL: {source_url}"}

    return {
        "source_url": source_url,
        "chunks": [
            {
                "heading": r[0],
                "text": r[1],
                "doc_version": r[2],
                "product_area": r[3],
            }
            for r in rows
        ],
    }


@mcp.tool()
def get_coding_guidelines() -> str:
    """
    Returns the Orcta Tech coding enforcement prompt.
    Paste this into your agent's system prompt to enforce internal standards.
    """
    return """
## Orcta Tech Coding Guidelines

You are an AI coding assistant working within the Orcta Tech engineering team.
You have access to an MCP server connected to Orcta Tech's internal documentation.

### Mandatory Rules

1. **Always call `search_docs` before implementing any feature, function, or
   integration that involves internal APIs, services, data models, or patterns.**

2. **Never use an external library if an internal Orcta Tech equivalent is
   documented.** If `search_docs` returns an internal SDK or utility for a task,
   use that instead.

3. **If `search_docs` returns no results**, explicitly state this and ask for
   clarification before proceeding with assumptions.

4. **Always cite the source URL** from the search result when referencing
   internal documentation in your response.

5. **When in doubt, search again** with a more specific query rather than
   guessing at internal conventions.

### Workflow

For every implementation task:
1. Call `search_docs` with a relevant query
2. Read the returned chunks carefully
3. Implement strictly according to what the docs say
4. Cite the source in your response
""".strip()


@mcp.tool()
def list_versions() -> list[str]:
    """List all indexed documentation versions."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT doc_version FROM doc_chunks ORDER BY doc_version;")
        return [row[0] for row in cur.fetchall()]


@mcp.tool()
def flag_answer(query: str, answer: str, issue: str) -> dict:
    """
    Flag a bad or incorrect search result or answer.
    Employees use this to report inaccurate documentation responses.
    """
    flag = {
        "query": query,
        "answer": answer,
        "issue": issue,
    }

    # push to a valkey list — reviewed async by a human
    vk.lpush("flags:answers", json.dumps(flag))

    return {"status": "flagged", "message": "Thank you — this has been logged for review."}




if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp")