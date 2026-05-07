import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    text: str
    source_url: str
    heading: str
    doc_version: str
    product_area: str
    has_code: bool


MAX_CHARS = 2400  # ~600 tokens


def chunk_markdown(
    markdown: str,
    source_url: str,
    doc_version: str,
    product_area: str,
) -> list[Chunk]:
    sections = split_by_heading(markdown)
    chunks = []

    for heading, body in sections:
        if len(body.strip()) < 50:
            continue

        has_code = "```" in body
        sub_chunks = split_if_too_long(body, has_code)

        for text in sub_chunks:
            chunks.append(
                Chunk(
                    text=text.strip(),
                    source_url=source_url,
                    heading=heading,
                    doc_version=doc_version,
                    product_area=product_area,
                    has_code=has_code,
                )
            )

    return chunks


def split_by_heading(markdown: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs on H1/H2 boundaries."""
    # match lines starting with one or two #
    pattern = re.compile(r"^(#{1,2})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(markdown))

    if not matches:
        # no headings — treat whole file as one section
        return [("Introduction", markdown)]

    sections = []

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        sections.append((heading, body))

    return sections


def split_if_too_long(text: str, has_code: bool) -> list[str]:
    """If a section is too long, split by paragraph — but never split code blocks."""
    if len(text) <= MAX_CHARS:
        return [text]

    # keep code blocks intact — don't split them regardless of length
    if has_code:
        return [text]

    paragraphs = re.split(r"\n\n+", text)
    results = []
    current = ""

    for para in paragraphs:
        if current and len(current) + len(para) > MAX_CHARS:
            results.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        results.append(current.strip())

    return results