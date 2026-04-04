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
    drawing_type_match = structured.drawing.drawing_type == sample_truth.get("drawing_type")
    expected_supported = bool(sample_truth.get("supported", True))
    rejected_predicted = not structured.drawing.drawing_type_supported
    rejected_expected = not expected_supported
    expected_rejection_reason = sample_truth.get("rejection_reason")
    rejected_correctly = (
        (rejected_expected and rejected_predicted and structured.drawing.classification_reason == expected_rejection_reason)
        or (not rejected_expected and not rejected_predicted)
    )
    bom_report = evaluate_bom_items(structured, sample_truth)

    return {
        "input_file": input_file,
        "drawing_number_ground_truth": sample_truth.get("drawing_number"),
        "drawing_number_predicted": structured.drawing.drawing_number,
        "drawing_number_match": drawing_number_match,
        "drawing_type_ground_truth": sample_truth.get("drawing_type"),
        "drawing_type_predicted": structured.drawing.drawing_type,
        "drawing_type_match": drawing_type_match,
        "supported_ground_truth": expected_supported,
        "supported_predicted": structured.drawing.drawing_type_supported,
        "rejection_reason_ground_truth": expected_rejection_reason,
        "rejection_reason_predicted": structured.drawing.classification_reason,
        "rejected_correctly": rejected_correctly,
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
        "bom_field_accuracy": bom_report["bom_field_accuracy"],
        "bom_row_recall": bom_report["bom_row_recall"],
        "bom_truth_row_count": bom_report["truth_row_count"],
        "bom_predicted_match_count": bom_report["predicted_match_count"],
        "bom_field_matches": bom_report["field_matches"],
        "bom_field_total": bom_report["field_total"],
        "bom_rows": bom_report["rows"],
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
            "drawing_type_accuracy": None,
            "rejected_correctly_accuracy": None,
            "weld_precision_micro": None,
            "weld_recall_micro": None,
        }

    drawing_matches = sum(1 for report in included if report["drawing_number_match"])
    drawing_type_matches = sum(1 for report in included if report.get("drawing_type_match"))
    tp = sum(len(report["weld_true_positive_ids"]) for report in included)
    fp = sum(len(report["weld_false_positive_ids"]) for report in included)
    fn = sum(len(report["weld_false_negative_ids"]) for report in included)
    bom_reports = [report for report in included if report.get("bom_field_total", 0)]
    bom_field_matches = sum(int(report["bom_field_matches"]) for report in bom_reports)
    bom_field_total = sum(int(report["bom_field_total"]) for report in bom_reports)
    rejected_reports = [report for report in included if report.get("supported_ground_truth") is False]
    rejected_correct = sum(1 for report in rejected_reports if report.get("rejected_correctly"))

    return {
        "sample_count": len(sample_reports),
        "included_sample_count": len(included),
        "drawing_number_accuracy": round(drawing_matches / len(included), 4),
        "drawing_type_accuracy": round(drawing_type_matches / len(included), 4),
        "rejected_correctly_accuracy": round(rejected_correct / len(rejected_reports), 4) if rejected_reports else None,
        "weld_precision_micro": round(tp / (tp + fp), 4) if (tp + fp) else 0.0,
        "weld_recall_micro": round(tp / (tp + fn), 4) if (tp + fn) else 0.0,
        "bom_field_accuracy_micro": round(bom_field_matches / bom_field_total, 4) if bom_field_total else None,
        "limitations": [
            "This report covers only the curated local regression samples.",
            "BOM field accuracy is measured only for samples that already have a field-level BOM truth set.",
            "Rejected-correctly accuracy is reported only for samples that explicitly expect rejection.",
            "Low-resolution samples can be excluded from metrics until a reliable human-labeled truth set is available.",
        ],
    }


def evaluate_bom_items(structured: StructuredDrawing, sample_truth: dict[str, Any]) -> dict[str, Any]:
    truth_rows = sample_truth.get("bom_items", [])
    if not truth_rows:
        return {
            "bom_field_accuracy": None,
            "bom_row_recall": None,
            "truth_row_count": 0,
            "predicted_match_count": 0,
            "field_matches": 0,
            "field_total": 0,
            "rows": [],
        }

    predicted_by_tag = {
        normalize_eval_tag(item.tag): item
        for item in structured.bom
        if normalize_eval_tag(item.tag)
    }
    field_matches = 0
    field_total = 0
    matched_rows = 0
    rows: list[dict[str, Any]] = []

    for truth_row in truth_rows:
        truth_tag = normalize_eval_tag(truth_row.get("tag"))
        predicted = predicted_by_tag.get(truth_tag)
        row_result = {
            "tag_truth": truth_row.get("tag"),
            "tag_predicted": predicted.tag if predicted else None,
            "field_matches": {},
        }
        if predicted:
            matched_rows += 1
        for field in ("tag", "qty", "description", "material", "uom"):
            truth_value = truth_row.get(field)
            if truth_value is None:
                continue
            field_total += 1
            predicted_value = getattr(predicted, field) if predicted else None
            is_match = normalize_eval_field(field, predicted_value) == normalize_eval_field(field, truth_value)
            if is_match:
                field_matches += 1
            row_result["field_matches"][field] = {
                "truth": truth_value,
                "predicted": predicted_value,
                "match": is_match,
            }
        rows.append(row_result)

    return {
        "bom_field_accuracy": round(field_matches / field_total, 4) if field_total else None,
        "bom_row_recall": round(matched_rows / len(truth_rows), 4) if truth_rows else None,
        "truth_row_count": len(truth_rows),
        "predicted_match_count": matched_rows,
        "field_matches": field_matches,
        "field_total": field_total,
        "rows": rows,
    }


def normalize_eval_tag(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).upper().replace(" ", "")
    text = text.replace("NAMEPLATE-SO", "NAMEPLATE-30").replace("NAMEPLATESO", "NAMEPLATE30")
    normalized = "".join(char for char in text if char.isalnum())
    return normalized or None


def normalize_eval_field(field: str, value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if field == "tag":
        return normalize_eval_tag(text)
    if field == "qty":
        digits = "".join(char for char in text if char.isdigit())
        return digits or None
    if field == "description":
        compact = "".join(char for char in text if char.isalnum())
        canonical_map = {
            "PIPE": "PIPE",
            "ENDPLATE": "ENDPLATE",
            "FLANGEPLATE": "FLANGEPLATE",
            "INFORMATIONTAGPLATE": "INFORMATIONTAGPLATE",
            "BASEPLATE": "BASEPLATE",
            "SHEARKEY": "SHEARKEY",
            "GUSSET": "GUSSET",
            "RINGSUPPORT": "RINGSUPPORT",
            "GROUNDLUG": "GROUNDLUG",
        }
        for token, normalized in canonical_map.items():
            if token in compact:
                return normalized
        return compact or None
    if field in {"material", "uom"}:
        return "".join(char for char in text if char.isalnum()) or None
    return text or None
