from __future__ import annotations

import json
from typing import Any

from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.modules.vlm import VLMEngine
from weld_assistant.services.progress import dedupe_preserve_order, normalize_manual_weld_id


ALLOWED_REVIEW_ACTIONS = {
    "register_welds",
    "keep_review_open",
    "mark_resolved",
    "inspect_manually",
    "rerun_vlm",
}


class ReviewService:
    def __init__(self, repository: SQLiteRepository, vlm_engine: VLMEngine):
        self.repository = repository
        self.vlm_engine = vlm_engine

    def suggest_review_item(
        self,
        review_id: str,
        use_llm: bool = False,
        timeout_override_sec: int | None = None,
    ) -> dict[str, Any]:
        context = self.build_review_context(review_id)
        heuristic = build_heuristic_review_suggestion(context)
        result: dict[str, Any] = {
            "context": context,
            "heuristic": heuristic,
            "final": heuristic,
            "llm": None,
        }

        if not use_llm:
            return result

        try:
            if timeout_override_sec is None:
                llm_task = self.vlm_engine.assist_review(context)
            else:
                llm_task = self.vlm_engine.assist_review_with_timeout(context, timeout_override_sec)
        except Exception as exc:
            result["llm"] = {"error": str(exc)}
            return result

        llm_output = normalize_review_assist_output(
            llm_task.output_json,
            allowed_candidate_weld_ids=heuristic["candidate_weld_ids"],
        )
        llm_output["latency_ms"] = llm_task.latency_ms
        result["llm"] = llm_output
        result["final"] = {
            **heuristic,
            "model_summary": llm_output["summary"],
            "model_recommended_action": llm_output["recommended_action"],
            "model_candidate_weld_ids": llm_output["candidate_weld_ids"],
            "model_notes": llm_output.get("notes"),
            "model_confidence": llm_output["confidence"],
            "model_latency_ms": llm_output["latency_ms"],
        }
        return result

    def build_review_context(self, review_id: str) -> dict[str, Any]:
        review_row = self.repository.get_review_item(review_id)
        if not review_row:
            raise ValueError(f"Review item not found: {review_id}")

        payload = json.loads(review_row["payload_json"])
        drawing_number = review_row["drawing_number"]
        drawing = dict(self.repository.get_drawing(drawing_number)) if drawing_number and self.repository.get_drawing(drawing_number) else None
        existing_weld_ids = [row["weld_id"] for row in self.repository.list_welds(drawing_number)] if drawing_number else []
        candidate_weld_ids = extract_review_candidate_weld_ids(review_row, payload)

        return {
            "review_id": review_row["review_id"],
            "document_id": review_row["document_id"],
            "drawing_number": drawing_number,
            "weld_id": review_row["weld_id"],
            "item_type": review_row["item_type"],
            "field": payload.get("field"),
            "message": payload.get("message"),
            "ocr_value": payload.get("ocr_value"),
            "vlm_value": payload.get("vlm_value"),
            "evidence": compact_evidence(payload.get("evidence") or {}),
            "existing_weld_ids": existing_weld_ids[:24],
            "candidate_weld_ids": candidate_weld_ids,
            "drawing_context": compact_drawing_context(drawing),
            "resolved_at": review_row["resolved_at"],
        }


def build_heuristic_review_suggestion(context: dict[str, Any]) -> dict[str, Any]:
    candidate_weld_ids = context["candidate_weld_ids"]
    item_type = context["item_type"] or ""
    field = context.get("field") or ""
    drawing_number = context.get("drawing_number") or context.get("document_id")

    if candidate_weld_ids and field == "weld_id":
        return {
            "summary": (
                f"Review weld identifiers for {drawing_number}. "
                f"Candidate IDs extracted from OCR/VLM evidence: {', '.join(candidate_weld_ids)}."
            ),
            "recommended_action": "register_welds",
            "candidate_weld_ids": candidate_weld_ids,
            "confidence": 0.86,
            "notes": "Register the missing weld rows only if the identifiers visually match the drawing.",
            "source": "heuristic",
        }

    if item_type == "ocr_vlm_conflict":
        return {
            "summary": f"OCR and VLM disagree for {drawing_number}; keep this item open until the title block is checked manually.",
            "recommended_action": "keep_review_open",
            "candidate_weld_ids": [],
            "confidence": 0.78,
            "notes": "OCR remains primary in this pipeline, so do not overwrite data automatically.",
            "source": "heuristic",
        }

    if item_type in {"drawing_number_missing", "drawing_number_from_vlm"}:
        return {
            "summary": f"The drawing number for {drawing_number} still needs human confirmation from the title block.",
            "recommended_action": "inspect_manually",
            "candidate_weld_ids": [],
            "confidence": 0.74,
            "notes": "Use manual inspection or rerun with a stronger local model if the title block is clearer in the source file.",
            "source": "heuristic",
        }

    if item_type in {"bom_item_needs_review", "bom_column_mismatch"}:
        return {
            "summary": f"The BOM data for {drawing_number} needs manual verification before export.",
            "recommended_action": "inspect_manually",
            "candidate_weld_ids": [],
            "confidence": 0.72,
            "notes": "Review the BOM ROI because column mapping or normalization was uncertain.",
            "source": "heuristic",
        }

    return {
        "summary": f"Review item {context['review_id']} for {drawing_number} needs manual confirmation.",
        "recommended_action": "inspect_manually",
        "candidate_weld_ids": candidate_weld_ids,
        "confidence": 0.6,
        "notes": "Keep the item open unless the evidence is obviously sufficient.",
        "source": "heuristic",
    }


def normalize_review_assist_output(output_json: dict[str, Any], allowed_candidate_weld_ids: list[str]) -> dict[str, Any]:
    summary = str(output_json.get("summary") or "").strip() or "No model summary provided."
    recommended_action = str(output_json.get("recommended_action") or "").strip().lower()
    if recommended_action not in ALLOWED_REVIEW_ACTIONS:
        recommended_action = "inspect_manually"
    llm_candidates = extract_candidate_weld_ids_from_values(output_json.get("candidate_weld_ids", []))
    allowed = set(allowed_candidate_weld_ids)
    filtered_candidates = [candidate for candidate in llm_candidates if candidate in allowed]
    confidence = output_json.get("confidence")
    try:
        normalized_confidence = max(0.0, min(float(confidence), 1.0))
    except (TypeError, ValueError):
        normalized_confidence = 0.0
    return {
        "summary": summary,
        "recommended_action": recommended_action,
        "candidate_weld_ids": filtered_candidates,
        "notes": str(output_json.get("notes") or "").strip() or None,
        "confidence": normalized_confidence,
    }


def extract_review_candidate_weld_ids(review_row, payload: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    direct_values = [
        review_row["weld_id"],
        payload.get("ocr_value"),
        payload.get("vlm_value"),
    ]
    for value in direct_values:
        candidates.extend(extract_candidate_weld_ids_from_values(value))

    evidence = payload.get("evidence") or {}
    for value in evidence.get("vlm_weld_ids", []):
        candidates.extend(extract_candidate_weld_ids_from_values(value))
    for value in evidence.get("candidate_weld_ids", []):
        candidates.extend(extract_candidate_weld_ids_from_values(value))
    return dedupe_preserve_order(candidates)


def extract_candidate_weld_ids_from_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = value
    else:
        values = [value]

    candidates: list[str] = []
    for raw_value in values:
        text = str(raw_value).replace(",", " ").replace(";", " ")
        for token in text.split():
            normalized = normalize_manual_weld_id(token)
            if normalized:
                candidates.append(normalized)
    return dedupe_preserve_order(candidates)


def compact_drawing_context(drawing: dict[str, Any] | None) -> dict[str, Any]:
    if not drawing:
        return {}
    return {
        "drawing_number": drawing.get("drawing_number"),
        "spool_name": drawing.get("spool_name"),
        "pipe_size": drawing.get("pipe_size"),
        "material_spec": drawing.get("material_spec"),
        "project_number": drawing.get("project_number"),
    }


def compact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in evidence.items():
        if isinstance(value, list):
            compact[key] = value[:12]
        elif isinstance(value, dict):
            compact[key] = {inner_key: inner_value for inner_key, inner_value in list(value.items())[:8]}
        else:
            compact[key] = value
    return compact
