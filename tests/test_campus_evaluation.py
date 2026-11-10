from argparse import Namespace
import json

import pytest

from scripts.evaluate_campus import compare, review_template, summarize, write_json


def sample_row(*, urls=(), retrieved=(), cited=(), status="success"):
    return {
        "case": {"id": "q1", "split": "dev", "reference_urls": list(urls)},
        "status": status,
        "retrieved": [{"metadata": {"url": url}} for url in retrieved],
        "sources": [{"url": url} for url in cited],
    }


def test_multi_source_coverage_and_review_are_separate():
    row = sample_row(urls=["a", "b"], retrieved=["a", "b"], cited=["a"])
    summary = summarize([row], {}, "query")
    assert summary["reference_retrieval_coverage"]["percent"] == 100
    assert summary["reference_citation_coverage"]["percent"] == 0
    assert summary["answer_accuracy"] is None
    assert summary["link_accuracy"] is None

    summary = summarize([row], {
        "q1": {"answer": "가", "links": "부", "reasons": ["링크 오류"], "note": "근거 b 누락"},
    }, "query")
    assert summary["answer_accuracy"]["percent"] == 100
    assert summary["link_accuracy"]["percent"] == 0
    assert summary["failures_by_reason"] == {"링크 오류": 1}


def test_abstention_and_missing_runs_keep_distinct_denominators():
    unsupported = sample_row(status="no_context")
    failed = sample_row(urls=["a"], status="not_run")
    failed["case"]["id"] = "q2"
    summary = summarize([unsupported, failed], {"q1": {"answer": "가"}}, "query")
    assert summary["answer_reviewed"] == 1
    assert summary["answer_accuracy"] is None
    assert summary["link_accuracy"] is None
    assert summary["status"] == {"no_context": 1, "not_run": 1}
    with pytest.raises(ValueError, match="incomplete"):
        summarize([failed], {"q2": {"answer": "부"}}, "query")


def test_compare_rejects_unmatched_snapshot_and_review(tmp_path, capsys):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before_review = tmp_path / "before-review.json"
    after_review = tmp_path / "after-review.json"
    run = {
        "dataset_sha256": "dataset",
        "split": "all",
        "snapshot": {"chroma": "same"},
        "config": {"mode": "query"},
        "results": [sample_row(urls=["a"], retrieved=["a"], cited=["a"])],
    }
    write_json(before, run, new=True)
    write_json(after, {**run, "snapshot": {"chroma": "different"}}, new=True)
    args = Namespace(before=before, after=after, before_review=None, after_review=None)
    with pytest.raises(ValueError, match="snapshot"):
        compare(args)

    write_json(after, {**run, "pipeline": {"rag": "changed"}})
    grade = {"reviewer_type": "human", "reviewer": "학사 검토자",
             "judgments": {"q1": {"answer": "가", "links": "가"}}}
    write_json(before_review, {**review_template(before), **grade}, new=True)
    write_json(after_review, {**review_template(after), **grade}, new=True)
    args.before_review, args.after_review = before_review, after_review
    compare(args)
    summary = json.loads(capsys.readouterr().out)
    assert summary["reviewer_type"] == "human"
    assert summary["groups"]["all"]["delta_pp"] == {"answer_accuracy": 0, "link_accuracy": 0}

    args.after_review = before_review
    with pytest.raises(ValueError, match="different run"):
        compare(args)
