"""Automatic Evidence Hit@k against gold source/page/quote, plus per-query traces.

Coherence and grounding are human labels (results/labels_*.csv); nothing here infers them.
"""
import re
from typing import Any


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def gold_options(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Primary gold plus documented alternatives; any one of them counts."""
    primary = {k: question[k] for k in ("gold_source_id", "gold_page", "evidence_quote")}
    return [primary] + question.get("alternative_gold", [])


def is_hit(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    text = norm(hit["text"])
    return any(hit["document_id"] == g["gold_source_id"] and hit["page"] == g["gold_page"]
               and norm(g["evidence_quote"]) in text for g in gold_options(question))


def follows_filter(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    return all(str(hit[k]) == str(v) for k, v in (question.get("filter") or {}).items())


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    flags = [is_hit(question, h) for h in hits]
    return {
        "hit_flags": flags,
        "hit1": bool(flags[:1] and flags[0]),
        "hit3": any(flags[:3]),
        "first_hit_rank": flags.index(True) + 1 if True in flags else None,
        "gold_doc_page_in_top3": any((h["document_id"], h["page"]) in
                                     {(g["gold_source_id"], g["gold_page"]) for g in gold_options(question)}
                                     for h in hits[:3]),
        "filter_compliant_top3": all(follows_filter(question, h) for h in hits[:3]) if question.get("filter") else None,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts (n/N) per strategy and split; filter compliance only over questions that carry a filter."""
    out: dict[str, Any] = {}
    for t in traces:
        row = out.setdefault(t["strategy"], {}).setdefault(t["split"], {
            "N": 0, "hit1": 0, "hit3": 0, "doc_page_top3": 0, "filter_N": 0, "filter_compliant": 0})
        row["N"] += 1
        row["hit1"] += t["eval"]["hit1"]
        row["hit3"] += t["eval"]["hit3"]
        row["doc_page_top3"] += t["eval"]["gold_doc_page_in_top3"]
        if t["eval"]["filter_compliant_top3"] is not None:
            row["filter_N"] += 1
            row["filter_compliant"] += t["eval"]["filter_compliant_top3"]
    return out


if __name__ == "__main__":  # self-check
    q = {"gold_source_id": "d", "gold_page": 2, "evidence_quote": "Foo  bar", "filter": {"version": "3.12"},
         "alternative_gold": [{"gold_source_id": "e", "gold_page": 1, "evidence_quote": "baz"}]}
    good = {"document_id": "d", "page": 2, "text": "x foo\nbar y", "version": "3.12"}
    alt = {"document_id": "e", "page": 1, "text": "BAZ", "version": "3.11"}
    wrong_page = {"document_id": "d", "page": 3, "text": "foo bar", "version": "3.12"}
    r = evaluate_query(q, [wrong_page, good, alt])
    assert r["hit_flags"] == [False, True, True] and not r["hit1"] and r["hit3"] and r["first_hit_rank"] == 2
    assert r["filter_compliant_top3"] is False
    s = summarize([{"strategy": "A", "split": "dev", "eval": r}])
    assert s["A"]["dev"] == {"N": 1, "hit1": 0, "hit3": 1, "doc_page_top3": 1, "filter_N": 1, "filter_compliant": 0}
    print("evaluation self-check OK")
