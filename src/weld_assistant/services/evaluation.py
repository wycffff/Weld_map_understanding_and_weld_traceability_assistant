from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from weld_assistant.contracts import StructuredDrawing


def load_ground_truth(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_structured_drawing(
    input_file: str,
    structured: StructuredDrawing,
    sample_truth: dict[str, Any],
) -> dict[str, Any]:
    predicted_weld_ids = [weld.weld_id for weld in structured.welds]
    truth_weld_ids = sample_truth.get("weld_ids", [])
    predicted_set = set(predicted_weld_ids)
    truth_set = set(truth_weld_ids)
    tp = sorted(predicted_set & truth_set)
    fp = sorted(predicted_set - truth_set)
    fn = sorted(truth_set - predicted_set)

    weld_precision = round(len(tp) / len(predicted_set), 4) if predicted_set else 0.0
    weld_recall = round(len(tp) / len(truth_set), 4) if truth_set else 0.0
    drawing_number_match = structured.drawing.drawing_number == sample_truth.get("drawing_number")

    return {
        "input_file": input_file,
        "drawing_number_ground_truth": sample_truth.get("drawing_number"),
        "drawing_number_predicted": structured.drawing.drawing_number,
        "drawing_number_match": drawing_number_match,
        "weld_ids_ground_truth": truth_weld_ids,
        "weld_ids_predicted": predicted_weld_ids,
        "weld_true_positive_ids": tp,
        "weld_false_positive_ids": fp,
        "weld_false_negative_ids": fn,
        "weld_precision": weld_precision,
        "weld_recall": weld_recall,
        "bom_count_ground_truth": sample_truth.get("bom_count"),
        "bom_count_predicted": len(structured.bom),
        "bom_count_delta": len(structured.bom) - int(sample_truth.get("bom_count", 0)),
        "review_count": len(structured.needs_review_items),
        "excluded_from_metrics": bool(sample_truth.get("exclude_from_metrics", False)),
        "notes": sample_truth.get("notes"),
    }


def summarize_evaluation(sample_reports: list[dict[str, Any]]) -> dict[str, Any]:
    included = [report for report in sample_reports if not report["excluded_from_metrics"]]
    if not included:
        return {
            "sample_count": len(sample_reports),
            "included_sample_count": 0,
            "drawing_number_accuracy": None,
            "weld_precision_micro": None,
            "weld_recall_micro": None,
        }

    drawing_matches = sum(1 for report in included if report["drawing_number_match"])
    tp = sum(len(report["weld_true_positive_ids"]) for report in included)
    fp = sum(len(report["weld_false_positive_ids"]) for report in included)
    fn = sum(len(report["weld_false_negative_ids"]) for report in included)

    return {
        "sample_count": len(sample_reports),
        "included_sample_count": len(included),
        "drawing_number_accuracy": round(drawing_matches / len(included), 4),
        "weld_precision_micro": round(tp / (tp + fp), 4) if (tp + fp) else 0.0,
        "weld_recall_micro": round(tp / (tp + fn), 4) if (tp + fn) else 0.0,
        "limitations": [
            "This report covers only the curated local regression samples.",
            "BOM field accuracy is not yet measured because a field-level BOM truth set has not been completed.",
            "Low-resolution samples can be excluded from metrics until a reliable human-labeled truth set is available.",
        ],
    }
