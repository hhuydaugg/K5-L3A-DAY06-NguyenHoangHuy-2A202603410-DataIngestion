"""Read Python "What's New" HTML pages and turn them into traceable page units.

The corpus is HTML without physical pages, so (per GUIDE.md) a "page" is a unit made
of whole leaf sections, in document order, with at least MIN_UNIT_CHARS normalized chars.
"""
import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from .models import DocumentPage

MIN_UNIT_CHARS = 1500
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
LEAF_BLOCKS = {"p", "pre", "dt", "tr", "caption"}
CONTAINERS_WITH_TEXT = {"li", "dd", "blockquote"}
BLOCK_DESCENDANTS = ["p", "pre", "ul", "ol", "dl", "table", "div", "blockquote"]


def normalize_text(text: str) -> str:
    """NFKC (nbsp -> space, ligatures), drop zero-width chars, collapse spaces per line."""
    text = unicodedata.normalize("NFKC", text).replace("​", "").replace("﻿", "")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _inline(tag: Tag) -> str:
    return normalize_text(re.sub(r"\s+", " ", tag.get_text()))


def _walk(node: Tag, out: list[tuple[int, str]]) -> None:
    """Emit (heading_level or 0, text) in document order without double-counting nesting."""
    for child in node.children:
        if not isinstance(child, Tag):
            continue
        name = child.name
        if name in HEADINGS:
            out.append((HEADINGS[name], _inline(child)))
        elif name == "pre":
            out.append((0, normalize_text(child.get_text())))
        elif name == "tr":
            cells = [_inline(c) for c in child.find_all(["th", "td"])]
            out.append((0, " | ".join(c for c in cells if c)))
        elif name in LEAF_BLOCKS:
            out.append((0, _inline(child)))
        elif name in CONTAINERS_WITH_TEXT and not child.find(BLOCK_DESCENDANTS):
            out.append((0, ("- " if name == "li" else "") + _inline(child)))
        else:
            _walk(child, out)


def load_html(path: Path, document_id: str, source: str) -> tuple[list[DocumentPage], dict]:
    """Return page units plus an ingestion log (title, version, skipped/empty blocks)."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    for link in soup.select("a.headerlink"):
        link.decompose()
    body = soup.select_one("div.body")
    if body is None:
        raise ValueError(f"{path}: no div.body, page layout changed")
    og_title = soup.find("meta", property="og:title")["content"]
    match = re.search(r"Python (\d+\.\d+)$", normalize_text(og_title))
    if not match:
        raise ValueError(f"{path}: cannot read version from og:title {og_title!r}")
    version = match.group(1)

    blocks: list[tuple[int, str]] = []
    _walk(body, blocks)
    empty_blocks = sum(1 for _, text in blocks if not text)

    # Group into leaf sections: each heading starts one; keep heading path for chunk metadata.
    leaves: list[dict] = []
    path_titles: dict[int, str] = {}
    for level, text in blocks:
        if not text:
            continue
        if level:
            path_titles = {k: v for k, v in path_titles.items() if k < level}
            path_titles[level] = text
            leaves.append({"path": dict(path_titles), "parts": ["#" * level + " " + text]})
        elif leaves:
            leaves[-1]["parts"].append(text)
        else:
            raise ValueError(f"{path}: text before first heading")

    # Pack whole leaves in order into units of >= MIN_UNIT_CHARS; leftover joins the last unit.
    units: list[list[dict]] = [[]]
    for leaf in leaves:
        units[-1].append(leaf)
        if sum(len(p) + 2 for lf in units[-1] for p in lf["parts"]) >= MIN_UNIT_CHARS:
            units.append([])
    if not units[-1]:
        units.pop()
    elif len(units) > 1:
        units[-2].extend(units.pop())

    pages = []
    for number, unit in enumerate(units, start=1):
        text = "\n\n".join(p for leaf in unit for p in leaf["parts"])
        start_path = unit[0]["path"]
        pages.append(DocumentPage(
            document_id=document_id, source=source, page=number, text=text,
            metadata={
                "version": version,
                "start_heading_path": {str(k): v for k, v in start_path.items() if k < max(start_path)},
                "sections": list(dict.fromkeys(leaf["path"].get(2, leaf["path"][1]) for leaf in unit)),
                "first_heading": unit[0]["parts"][0],
                "chars": len(text),
            }))
    log = {"document_id": document_id, "title": normalize_text(og_title), "version": version,
           "html_title": normalize_text(soup.title.get_text()), "blocks": len(blocks),
           "empty_blocks_skipped": empty_blocks, "leaf_sections": len(leaves), "units": len(pages),
           "short_units": [p.page for p in pages if p.metadata["chars"] < MIN_UNIT_CHARS]}
    return pages, log
