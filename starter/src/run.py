"""Day 06 pipeline: ingest -> manifest -> verify benchmark -> chunk A/B -> embed -> pgvector -> top-3 traces -> metrics.

Run from starter/:  python -m src.run            (full run)
                    python -m src.run --ingest-only
"""
import argparse
import csv
import json
import os
import platform
import re
import statistics
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

from dotenv import load_dotenv

from .chunking import _heading_path_at, by_paragraph, fixed_size
from .evaluation import evaluate_query, follows_filter, gold_options, norm, summarize
from .ingestion import MIN_UNIT_CHARS, load_html
from .models import Chunk, DocumentPage

STARTER = Path(__file__).resolve().parents[1]
REPO = STARTER.parent
RAW = STARTER / "data" / "raw"
DATA, BENCH, RESULTS = REPO / "data", REPO / "benchmark", REPO / "results"
LICENSE = ("Python Software Foundation License Version 2 (documentation text); code examples additionally "
           "Zero Clause BSD. Source: footer of each page and https://docs.python.org/3/license.html")
CORPUS = [{"source_id": f"whatsnew-{v}", "file": f"whatsnew-{v}.html"} for v in ("3.11", "3.12", "3.13")]
MODEL = "BAAI/bge-small-en-v1.5"
STRATEGIES = {
    "A": {"chunking": "fixed_size", "size": 800, "overlap": 100, "index": "A", "use_filter": False},
    "B": {"chunking": "by_paragraph (heading-bounded, breadcrumb prefix)", "max_size": 1200, "overlap": 0,
          "index": "B", "use_filter": False},
    "C": {"chunking": "same chunks as B (reuses index B)", "max_size": 1200, "overlap": 0, "index": "B",
          "use_filter": True},
}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def ingest() -> tuple[list[DocumentPage], dict]:
    t0 = time.perf_counter()
    accessed_at = (RAW / "ACCESSED_AT").read_text().strip()
    pages, logs, manifest = [], [], []
    for doc in CORPUS:
        path = RAW / doc["file"]
        html = path.read_text(encoding="utf-8")
        source = re.search(r'property="og:url" content="([^"]+)"', html).group(1)
        updated = re.search(r"Last updated on ([^.<]+)", html)
        doc_pages, log = load_html(path, doc["source_id"], source)
        pages += doc_pages
        logs.append(log)
        manifest.append({
            "source_id": doc["source_id"], "title": log["title"], "source_path_or_url": source,
            "local_path": f"starter/data/raw/{doc['file']}", "license_or_permission": LICENSE,
            "accessed_at": accessed_at, "snapshot_version": log["html_title"],
            "page_last_updated": updated.group(1).strip() if updated else None,
            "version_filter_value": log["version"],
            "page_rule": f"No physical pages (HTML). Unit = whole leaf sections (h1-h4) packed in document order "
                         f"until >= {MIN_UNIT_CHARS} normalized chars; a short tail joins the previous unit.",
            "pages_counted": len(doc_pages),
            "pages": [{"page": p.page, "page_id": f"{p.document_id}#p{p.page:03d}", "chars": p.metadata["chars"],
                       "first_heading": p.metadata["first_heading"], "sections": p.metadata["sections"]}
                      for p in doc_pages],
            "total_chars": sum(p.metadata["chars"] for p in doc_pages)})
    seconds = time.perf_counter() - t0
    if len(pages) < 30:
        raise SystemExit(f"only {len(pages)} content units, need >= 30")
    write_json(DATA / "manifest.json", {"generated_at": now(), "content_units_total": len(pages),
                                        "documents": manifest})
    with (DATA / "pages.jsonl").open("w", encoding="utf-8") as f:
        for p in pages:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    write_json(RESULTS / "ingestion_log.json", {"seconds": round(seconds, 3), "documents": logs,
                                                "errors": [l for l in logs if l["short_units"] or l["empty_blocks_skipped"]]})
    print(f"ingested {len(pages)} units from {len(CORPUS)} documents in {seconds:.2f}s")
    return pages, {"seconds": seconds}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_benchmark(pages: list[DocumentPage]) -> list[dict]:
    """Fail loudly unless split sizes, filters and every gold quote check out against normalized pages."""
    questions = json.loads((BENCH / "questions.json").read_text(encoding="utf-8"))["questions"]
    by_key = {(p.document_id, p.page): p for p in pages}
    versions = {p.metadata["version"] for p in pages}
    errors = []
    for q in questions:
        for g in gold_options(q):
            page = by_key.get((g["gold_source_id"], g["gold_page"]))
            if page is None or norm(g["evidence_quote"]) not in norm(page.text):
                errors.append(f"{q['id']}: evidence not found in {g['gold_source_id']} p{g['gold_page']}")
        given = q.get("filter") or {}
        if given and (set(given) != {"version"} or given["version"] not in versions):
            errors.append(f"{q['id']}: bad filter {q['filter']}")
    splits = [q["split"] for q in questions]
    filtered_test = sum(1 for q in questions if q.get("filter") and q["split"] == "test")
    if splits.count("dev") < 15 or splits.count("test") < 5 or len(set(q["id"] for q in questions)) != len(questions):
        errors.append("need >= 15 dev, >= 5 test, unique ids")
    if sum(1 for q in questions if q.get("filter")) < 3 or filtered_test < 1:
        errors.append("need >= 3 filter questions, >= 1 in test")
    if errors:
        raise SystemExit("benchmark invalid:\n" + "\n".join(errors))
    write_json(RESULTS / "benchmark_verification.json", {
        "checked_at": now(), "questions": len(questions), "dev": splits.count("dev"), "test": splits.count("test"),
        "with_filter": sum(1 for q in questions if q.get("filter")), "filter_in_test": filtered_test,
        "gold_options_checked": sum(len(gold_options(q)) for q in questions), "all_evidence_found": True})
    return questions


def length_stats(chunks: list[Chunk], tokens: list[int], max_seq: int) -> dict:
    lengths = sorted(len(c.text) for c in chunks)
    q = statistics.quantiles(lengths, n=4)
    return {"chunks": len(chunks), "chars_min": lengths[0], "chars_p25": q[0], "chars_median": q[1],
            "chars_p75": q[2], "chars_max": lengths[-1], "chars_mean": round(statistics.mean(lengths), 1),
            "chars_total": sum(lengths), "tokens_total": sum(tokens),
            "tokens_max": max(tokens), "chunks_over_model_max_seq": sum(t > max_seq for t in tokens),
            "chunks_under_200_chars": sum(n < 200 for n in lengths)}


def reingest_check(store, index_chunks: dict, index_vectors: dict) -> dict:
    """Same content twice -> same row count; dropped chunk of a changed document -> deleted."""
    report = {}
    for name, chunks in index_chunks.items():
        before = store.count(name)
        again = store.upsert(name, chunks, index_vectors[name])
        report[name] = {"rows_before": before, "rows_after_second_upsert": again["rows_now"],
                        "obsolete_deleted": again["obsolete_deleted"], "no_duplicates": before == again["rows_now"] == len(chunks)}
    sample, vecs = index_chunks["B"][:3], index_vectors["B"][:3]
    store.upsert("_selftest", sample, vecs)
    shrunk = store.upsert("_selftest", sample[:2], vecs[:2])  # simulates a document edit that removed one chunk
    store.delete_strategy("_selftest")
    report["changed_document_simulation"] = {"first_upsert_rows": 3, **shrunk, "ok": shrunk["rows_now"] == 2
                                             and shrunk["obsolete_deleted"] == 1}
    if not all(v.get("no_duplicates", v.get("ok")) for v in report.values()):
        raise SystemExit(f"re-ingest check failed: {report}")
    return report


def chunk_body(hit: dict) -> str:
    return hit["text"].split("\n", 1)[1] if hit["chunk_id"].startswith("B:") else hit["text"]


def metadata_check(hit: dict, by_key: dict, sources: dict) -> tuple[bool, str]:
    """Cross-check stored metadata against the normalized source page."""
    page = by_key.get((hit["document_id"], hit["page"]))
    if page is None:
        return False, "page not in corpus"
    problems = []
    if page.text[hit["char_start"]:hit["char_end"]] != chunk_body(hit):
        problems.append("text != source[char_start:char_end]")
    if hit["source"] != sources[hit["document_id"]]:
        problems.append("source url mismatch")
    if hit["version"] != page.metadata["version"]:
        problems.append("version mismatch")
    path = _heading_path_at(page, hit["char_start"])
    if hit["section"] != path.get(2, path.get(1, "")) or hit["subsection"] != path.get(3, ""):
        problems.append("section/subsection mismatch")
    return not problems, "; ".join(problems) or "ok"


def coherence_positions(pages: list[DocumentPage]) -> list[tuple[DocumentPage, int, str]]:
    """10 pages evenly spaced over the sorted page list; position = paragraph crossing the page middle.

    Fixed by rule before any scores were seen.
    """
    ordered = sorted(pages, key=lambda p: (p.document_id, p.page))
    out = []
    for i in range(10):
        page = ordered[round(i * (len(ordered) - 1) / 9)]
        mid, offset = len(page.text) // 2, 0
        for para in page.text.split("\n\n"):
            end = offset + len(para)
            if end >= mid and not para.startswith("#"):
                out.append((page, offset, para))
                break
            offset = end + 2
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest-only", action="store_true")
    args = parser.parse_args()
    load_dotenv(STARTER / ".env")
    RESULTS.mkdir(exist_ok=True)
    pages, ingest_info = ingest()
    if args.ingest_only:
        return
    questions = load_benchmark(pages)
    print(f"benchmark OK: {len(questions)} questions, all evidence found in source pages")

    from .embeddings import MyEmbedder
    from .store import PgVectorStore
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL missing in starter/.env")
    embedder = MyEmbedder(MODEL)
    store = PgVectorStore(url, embedder.dimensions)
    store.create_schema()

    builders = {"A": lambda p: fixed_size(p, STRATEGIES["A"]["size"], STRATEGIES["A"]["overlap"]),
                "B": lambda p: by_paragraph(p, STRATEGIES["B"]["max_size"])}
    index_chunks, index_vectors, stats = {}, {}, {}
    for name, build in builders.items():
        t0 = time.perf_counter()
        chunks = [c for p in pages for c in build(p)]
        t1 = time.perf_counter()
        vectors = embedder.embed_documents([c.text for c in chunks])
        t2 = time.perf_counter()
        written = store.upsert(name, chunks, vectors)
        t3 = time.perf_counter()
        index_chunks[name], index_vectors[name] = chunks, vectors
        stats[name] = {**length_stats(chunks, embedder.count_tokens([c.text for c in chunks]), embedder.max_seq_length),
                       "chunk_seconds": round(t1 - t0, 3), "embed_seconds": round(t2 - t1, 2),
                       "upsert_seconds": round(t3 - t2, 2), "ingest_total_seconds": round(t3 - t0 + ingest_info["seconds"], 2),
                       "rows_in_store": written["rows_now"], "cost_usd": 0.0}
        print(f"index {name}: {len(chunks)} chunks, embed {t2 - t1:.1f}s, upsert {t3 - t2:.1f}s")
    write_json(RESULTS / "chunk_stats.json", stats)
    write_json(RESULTS / "reingest_check.json", reingest_check(store, index_chunks, index_vectors))

    traces, latencies = [], {s: [] for s in STRATEGIES}
    for q in questions:
        qvec = embedder.embed_query(q["question"])
        for name, cfg in STRATEGIES.items():
            filters = q.get("filter") if cfg["use_filter"] else None
            t0 = time.perf_counter()
            hits = store.search(cfg["index"], qvec, top_k=3, filters=filters)
            latencies[name].append(time.perf_counter() - t0)
            traces.append({"strategy": name, "id": q["id"], "split": q["split"], "type": q.get("type"),
                           "question": q["question"], "filter_given": q.get("filter"), "filter_applied": filters,
                           "gold": gold_options(q), "expected_answer": q["expected_answer"],
                           "top3": [{**h, "rank": i + 1, "score": round(float(h["score"]), 4)} for i, h in enumerate(hits)],
                           "eval": evaluate_query(q, hits)})
    with (RESULTS / "traces.jsonl").open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    metrics = summarize(traces)
    for name in STRATEGIES:
        metrics[name]["query_latency_ms_mean"] = round(1000 * statistics.mean(latencies[name]), 2)
    write_json(RESULTS / "metrics.json", metrics)

    lines = ["| Strategy | Split | Hit@1 | Evidence Hit@3 | Gold page in top-3 | Filter compliant | Chunks |",
             "|---|---|---|---|---|---|---|"]
    for name in STRATEGIES:
        for split in ("dev", "test"):
            m = metrics[name][split]
            filt = f"{m['filter_compliant']}/{m['filter_N']}" if m["filter_N"] else "N/A"
            lines.append(f"| {name} | {split} | {m['hit1']}/{m['N']} | {m['hit3']}/{m['N']} | "
                         f"{m['doc_page_top3']}/{m['N']} | {filt} | {stats[STRATEGIES[name]['index']]['chunks']} |")
    (RESULTS / "metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    # Audit sheets (templates are regenerated; human labels live in results/labels_*.csv and are never overwritten).
    by_key = {(p.document_id, p.page): p for p in pages}
    sources = {p.document_id: p.source for p in pages}
    rows = []
    for t in traces:
        if t["split"] != "test":
            continue
        for h in t["top3"]:
            ok, why = metadata_check(h, by_key, sources)
            rows.append({"strategy": t["strategy"], "id": t["id"], "rank": h["rank"], "chunk_id": h["chunk_id"],
                         "document_id": h["document_id"], "page": h["page"], "version": h["version"],
                         "section": h["section"], "subsection": h["subsection"], "score": h["score"],
                         "auto_evidence_hit": t["eval"]["hit_flags"][h["rank"] - 1],
                         "filter_given": json.dumps(t["filter_given"]) if t["filter_given"] else "",
                         "follows_filter": follows_filter({"filter": t["filter_given"]}, h) if t["filter_given"] else "",
                         "metadata_ok": ok, "metadata_check": why, "text": h["text"]})
    write_csv(RESULTS / "audit_test_top3.csv", rows)

    rows = []
    for n, (page, offset, para) in enumerate(coherence_positions(pages), start=1):
        for name in ("A", "B"):
            chunk = next(c for c in index_chunks[name] if c.document_id == page.document_id and c.page == page.page
                         and c.metadata["char_start"] <= offset < c.metadata["char_end"])
            rows.append({"position": f"pos{n:02d}", "document_id": page.document_id, "page": page.page,
                         "offset": offset, "paragraph_start": para[:120], "strategy": name, "chunk_id": chunk.chunk_id,
                         "chunk_text": chunk.text})
    write_csv(RESULTS / "audit_coherence_template.csv", rows)

    write_json(RESULTS / "run_config.json", {
        "run_at": now(), "python": sys.version.split()[0], "platform": platform.platform(),
        "embedding": {"provider": "local sentence-transformers (CPU)", "model": MODEL, "revision": embedder.revision,
                      "dimensions": embedder.dimensions, "max_seq_length": embedder.max_seq_length,
                      "normalize": True, "query_instruction": embedder.QUERY_INSTRUCTION, "document_prefix": ""},
        "vector_store": {"backend": "PostgreSQL 16 + pgvector 0.8 (docker image pgvector/pgvector:0.8.7-pg16)",
                         "table": "chunks", "metric": "cosine (<=>)", "search": "exact (no ANN index)",
                         "filters": "SQL WHERE on version, applied before ranking"},
        "strategies": STRATEGIES, "libraries": {p: pkg_version(p) for p in (
            "sentence-transformers", "torch", "transformers", "psycopg", "beautifulsoup4", "numpy")},
        "cost_usd": 0.0})
    print(f"done: traces, metrics and audit sheets in {RESULTS}")


if __name__ == "__main__":
    main()
