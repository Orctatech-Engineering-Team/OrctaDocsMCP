import os
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv

from ingestion.chunker import chunk_markdown
from ingestion.embedder import ensure_table, embed_and_store

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DOCS_REPO_URL = os.getenv("DOCS_REPO_URL")
DOCS_BASE_URL = os.getenv("DOCS_BASE_URL")
DOC_VERSION = os.getenv("DOC_VERSION", "v1")
PRODUCT_AREA = os.getenv("PRODUCT_AREA", "general")

CLONE_DIR = Path(os.getenv("TEMP", "C:/Temp")) / "docs-repo"
DOCS_SUBDIR = CLONE_DIR / "org-docs"


def clone_repo():
    # inject token into the URL for private repo auth
    # https://github.com/org/repo.git -> https://<token>@github.com/org/repo.git
    auth_url = DOCS_REPO_URL.replace("https://", f"https://x-access-token:{GITHUB_TOKEN}@")

    if CLONE_DIR.exists():
        print("Repo already cloned, pulling latest...")
        subprocess.run(["git", "-C", str(CLONE_DIR), "pull"], check=True)
    else:
        print("Cloning repo...")
        subprocess.run(["git", "clone", "--depth=1", auth_url, str(CLONE_DIR)], check=True)


def ingest():
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not set in .env")
    if not DOCS_REPO_URL:
        raise ValueError("DOCS_REPO_URL is not set in .env")

    clone_repo()

    if not DOCS_SUBDIR.exists():
        raise FileNotFoundError(f"No /docs subfolder found in repo at {DOCS_SUBDIR}")

    md_files = list(DOCS_SUBDIR.rglob("*.md"))
    print(f"Found {len(md_files)} markdown files")

    ensure_table()

    total_chunks = 0

    for filepath in md_files:
        content = filepath.read_text(encoding="utf-8")
        relative = filepath.relative_to(CLONE_DIR)

        # map file path to the github.io URL
        source_url = f"{DOCS_BASE_URL}/{str(relative).replace('.md', '')}"

        chunks = chunk_markdown(
            markdown=content,
            source_url=source_url,
            doc_version=DOC_VERSION,
            product_area=PRODUCT_AREA,
        )

        if not chunks:
            continue

        embed_and_store(chunks)
        total_chunks += len(chunks)
        print(f"✓ {relative} → {len(chunks)} chunks")

    print(f"\nDone. {total_chunks} total chunks indexed.")


if __name__ == "__main__":
    ingest()