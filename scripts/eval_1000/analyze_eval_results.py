# -*- coding: utf-8 -*-
"""
Analyze the 1,000-question CampusRAG evaluation results and generate detailed statistics.
"""
import sys
import json
from collections import defaultdict, Counter
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

RUN_PATH = Path(r"C:\server01\.codex-work\campusrag-gemini-20261109\results\eval_run_retrieval_1000.json")
REPORT_PATH = Path(r"C:\server01\.codex-work\campusrag-gemini-20261109\results\evaluation_report_1000.json")

def analyze():
    with open(RUN_PATH, "r", encoding="utf-8") as f:
        run_data = json.load(f)

    results = run_data["results"]
    assert len(results) == 1000, f"Expected 1000 results, got {len(results)}"

    # Metrics containers
    total_cases = len(results)
    
    # Category, Split, Case Type breakdown
    by_category = defaultdict(lambda: {"total": 0, "hits_top1": 0, "hits_top3": 0, "hits_top5": 0, "partial_hits": 0, "abstain_count": 0})
    by_split = defaultdict(lambda: {"total": 0, "hits_top1": 0, "hits_top3": 0, "hits_top5": 0, "partial_hits": 0, "abstain_count": 0})
    by_case_type = defaultdict(lambda: {"total": 0, "hits_top1": 0, "hits_top3": 0, "hits_top5": 0, "partial_hits": 0})
    slice_stats = defaultdict(lambda: {"total": 0, "hits_top5": 0})

    missed_cases = []

    for r in results:
        case = r["case"]
        qid = case["id"]
        cat = case["category"]
        sp = case["split"]
        ct = case["case_type"]
        expected_urls = set(case.get("reference_urls", []))
        
        retrieved_docs = r.get("retrieved", [])
        retrieved_urls = [d.get("metadata", {}).get("url") for d in retrieved_docs]

        # Update totals
        by_category[cat]["total"] += 1
        by_split[sp]["total"] += 1
        by_case_type[ct]["total"] += 1
        slice_stats[(cat, sp, ct)]["total"] += 1

        if ct == "abstain":
            # For abstain, expected_urls is empty
            by_category[cat]["abstain_count"] += 1
            by_split[sp]["abstain_count"] += 1
            # In abstain, we measure retrieval relevance scores or treat as abstain pool
            continue

        # For single
        if ct == "single":
            target_url = list(expected_urls)[0]
            top1_urls = set(retrieved_urls[:1])
            top3_urls = set(retrieved_urls[:3])
            top5_urls = set(retrieved_urls[:5])

            hit1 = target_url in top1_urls
            hit3 = target_url in top3_urls
            hit5 = target_url in top5_urls

            if hit1:
                by_category[cat]["hits_top1"] += 1
                by_split[sp]["hits_top1"] += 1
                by_case_type[ct]["hits_top1"] += 1
            if hit3:
                by_category[cat]["hits_top3"] += 1
                by_split[sp]["hits_top3"] += 1
                by_case_type[ct]["hits_top3"] += 1
            if hit5:
                by_category[cat]["hits_top5"] += 1
                by_split[sp]["hits_top5"] += 1
                by_case_type[ct]["hits_top5"] += 1
                slice_stats[(cat, sp, ct)]["hits_top5"] += 1
            else:
                missed_cases.append({
                    "id": qid,
                    "category": cat,
                    "split": sp,
                    "case_type": ct,
                    "question": case["question"],
                    "expected": list(expected_urls),
                    "retrieved_top5": retrieved_urls[:5]
                })

        # For multi
        elif ct == "multi":
            top1_urls = set(retrieved_urls[:1])
            top3_urls = set(retrieved_urls[:3])
            top5_urls = set(retrieved_urls[:5])

            # Full hit: ALL expected URLs in top5
            full_hit1 = expected_urls.issubset(top1_urls) # impossible if len > 1
            full_hit3 = expected_urls.issubset(top3_urls)
            full_hit5 = expected_urls.issubset(top5_urls)

            # Partial hit: at least one expected URL in top5
            partial_hit5 = bool(expected_urls & top5_urls)

            if full_hit1:
                by_category[cat]["hits_top1"] += 1
                by_split[sp]["hits_top1"] += 1
                by_case_type[ct]["hits_top1"] += 1
            if full_hit3:
                by_category[cat]["hits_top3"] += 1
                by_split[sp]["hits_top3"] += 1
                by_case_type[ct]["hits_top3"] += 1
            if full_hit5:
                by_category[cat]["hits_top5"] += 1
                by_split[sp]["hits_top5"] += 1
                by_case_type[ct]["hits_top5"] += 1
                slice_stats[(cat, sp, ct)]["hits_top5"] += 1
            else:
                missed_cases.append({
                    "id": qid,
                    "category": cat,
                    "split": sp,
                    "case_type": ct,
                    "question": case["question"],
                    "expected": list(expected_urls),
                    "retrieved_top5": retrieved_urls[:5]
                })

            if partial_hit5:
                by_category[cat]["partial_hits"] += 1
                by_split[sp]["partial_hits"] += 1
                by_case_type[ct]["partial_hits"] += 1

    # Single overall stats
    single_total = by_case_type["single"]["total"]
    single_hit1 = by_case_type["single"]["hits_top1"]
    single_hit3 = by_case_type["single"]["hits_top3"]
    single_hit5 = by_case_type["single"]["hits_top5"]

    # Multi overall stats
    multi_total = by_case_type["multi"]["total"]
    multi_hit3 = by_case_type["multi"]["hits_top3"]
    multi_hit5 = by_case_type["multi"]["hits_top5"]
    multi_partial = by_case_type["multi"]["partial_hits"]

    # Applicable (single + multi = 850)
    applicable_total = single_total + multi_total
    applicable_hit5 = single_hit5 + multi_hit5

    summary_report = {
        "benchmark_metadata": {
            "total_questions": 1000,
            "evaluated_questions": 1000,
            "applicable_retrieval_cases": applicable_total,
            "abstain_cases": by_case_type["abstain"]["total"],
            "model_config": run_data.get("config", {})
        },
        "overall_metrics": {
            "single_top1_accuracy": round(100.0 * single_hit1 / single_total, 2),
            "single_top3_accuracy": round(100.0 * single_hit3 / single_total, 2),
            "single_top5_accuracy": round(100.0 * single_hit5 / single_total, 2),
            "multi_top5_full_hit_accuracy": round(100.0 * multi_hit5 / multi_total, 2),
            "multi_top5_partial_hit_accuracy": round(100.0 * multi_partial / multi_total, 2),
            "overall_top5_retrieval_accuracy": round(100.0 * applicable_hit5 / applicable_total, 2)
        },
        "by_category": {},
        "by_split": {},
        "missed_cases_count": len(missed_cases),
        "missed_sample": missed_cases[:15]
    }

    for cat, data in by_category.items():
        cat_single_multi = data["total"] - data["abstain_count"]
        summary_report["by_category"][cat] = {
            "total_items": data["total"],
            "applicable_items": cat_single_multi,
            "abstain_items": data["abstain_count"],
            "top1_hits": data["hits_top1"],
            "top3_hits": data["hits_top3"],
            "top5_hits": data["hits_top5"],
            "top5_recall_percent": round(100.0 * data["hits_top5"] / cat_single_multi, 2) if cat_single_multi else 0.0,
            "multi_partial_hits": data["partial_hits"]
        }

    for sp, data in by_split.items():
        sp_single_multi = data["total"] - data["abstain_count"]
        summary_report["by_split"][sp] = {
            "total_items": data["total"],
            "applicable_items": sp_single_multi,
            "abstain_items": data["abstain_count"],
            "top1_hits": data["hits_top1"],
            "top3_hits": data["hits_top3"],
            "top5_hits": data["hits_top5"],
            "top5_recall_percent": round(100.0 * data["hits_top5"] / sp_single_multi, 2) if sp_single_multi else 0.0
        }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary_report, f, ensure_ascii=False, indent=2)

    print("=== CAMPUSRAG 1,000-QUESTION BENCHMARK RESULTS ===")
    print(f"Total Evaluated Questions: {total_cases}")
    print(f"  - Single (단일 원문): {single_total}건 | Top-1: {single_hit1} ({summary_report['overall_metrics']['single_top1_accuracy']}%), Top-3: {single_hit3} ({summary_report['overall_metrics']['single_top3_accuracy']}%), Top-5: {single_hit5} ({summary_report['overall_metrics']['single_top5_accuracy']}%)")
    print(f"  - Multi (복수 원문): {multi_total}건 | Top-5 Full Hit: {multi_hit5} ({summary_report['overall_metrics']['multi_top5_full_hit_accuracy']}%), Partial Hit: {multi_partial} ({summary_report['overall_metrics']['multi_top5_partial_hit_accuracy']}%)")
    print(f"  - Abstain (답변 유보): {by_case_type['abstain']['total']}건")
    print(f"Overall Top-5 Retrieval Accuracy (Single + Multi Full Hit): {summary_report['overall_metrics']['overall_top5_retrieval_accuracy']}% ({applicable_hit5}/{applicable_total})")
    print("\n--- By Category ---")
    for cat, stats in summary_report["by_category"].items():
        print(f"  [{cat}]: Top-5 Recall = {stats['top5_recall_percent']}% ({stats['top5_hits']}/{stats['applicable_items']}) | Top-1: {stats['top1_hits']}건")
    print("\n--- By Split ---")
    for sp, stats in summary_report["by_split"].items():
        print(f"  [{sp}]: Top-5 Recall = {stats['top5_recall_percent']}% ({stats['top5_hits']}/{stats['applicable_items']}) | Top-1: {stats['top1_hits']}건")

if __name__ == "__main__":
    analyze()
