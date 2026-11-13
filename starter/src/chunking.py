"""Fixed-size (strategy A) and heading/paragraph-aware (strategy B) chunking."""
import re

from .models import Chunk, DocumentPage

HEADING_RE = re.compile(r"^(#{1,4}) (.+)$", re.MULTILINE)


def _heading_path_at(page: DocumentPage, offset: int) -> dict[int, str]:
    """Heading path in effect at `offset` (page start path + headings seen before offset)."""
    path = {int(k): v for k, v in page.metadata["start_heading_path"].items()}
    for match in HEADING_RE.finditer(page.text):
        if match.start() > offset:
            break
        level = len(match.group(1))
        path = {k: v for k, v in path.items() if k < level}
        path[level] = match.group(2)
    return path


def _chunk(page: DocumentPage, strategy: str, index: int, start: int, end: int, text: str) -> Chunk:
    path = _heading_path_at(page, start)
    return Chunk(
        chunk_id=f"{strategy}:{page.document_id}:p{page.page:03d}:c{index:03d}",
        document_id=page.document_id, source=page.source, page=page.page, text=text,
        metadata={"version": page.metadata["version"], "section": path.get(2, path.get(1, "")),
                  "subsection": path.get(3, ""), "char_start": start, "char_end": end})


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Character windows of `size` with `overlap`; ignores structure on purpose (baseline)."""
    if not 0 <= overlap < size:
        raise ValueError("need 0 <= overlap < size")
    text = page.text
    starts = range(0, max(len(text) - overlap, 1), size - overlap)
    return [_chunk(page, "A", i, s, min(s + size, len(text)), text[s:s + size]) for i, s in enumerate(starts)]


def _pieces(start: int, para: str, max_size: int) -> list[tuple[int, int]]:
    """Split an oversized paragraph at sentence/line ends; hard cut only if none fits."""
    spans, pos = [], 0
    while len(para) - pos > max_size:
        window = para[pos:pos + max_size]
        cut = max(window.rfind(". "), window.rfind("\n"))
        cut = cut + 1 if cut > max_size // 3 else max_size
        spans.append((start + pos, start + pos + cut))
        pos += cut
        while pos < len(para) and para[pos] in " \n":
            pos += 1
    return spans + [(start + pos, start + len(para))]


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group paragraphs inside one heading section up to `max_size` chars.

    A chunk never crosses a heading; its text starts with a breadcrumb
    ("Python 3.12 > Improved Modules > sqlite3") so the subject survives the split.
    """
    spans: list[tuple[int, int]] = []          # body spans in page.text, in order
    current: tuple[int, int] | None = None
    for match in re.finditer(r"[^\n](?:.|\n(?!\n))*", page.text):
        start, end, para = match.start(), match.end(), match.group()
        if HEADING_RE.fullmatch(para):
            if current:
                spans.append(current)
            current = None
            continue
        for p_start, p_end in _pieces(start, para, max_size):
            if current and p_end - current[0] <= max_size:
                current = (current[0], p_end)
            else:
                if current:
                    spans.append(current)
                current = (p_start, p_end)
    if current:
        spans.append(current)

    chunks = []
    for i, (start, end) in enumerate(spans):
        chunk = _chunk(page, "B", i, start, end, "")
        meta = chunk.metadata
        crumb = " > ".join(x for x in (f"Python {meta['version']}", meta["section"], meta["subsection"]) if x)
        chunk.text = f"{crumb}\n{page.text[start:end]}"
        chunks.append(chunk)
    return chunks
