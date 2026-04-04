from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import ollama

from weld_assistant.config import AppConfig
from weld_assistant.contracts import LayoutPlan, VLMResult, VLMTaskResult
from weld_assistant.utils.files import ensure_dir, write_json


TASK_SCHEMAS: dict[str, dict[str, Any]] = {
    "weld_location_describe": {
        "type": "object",
        "properties": {
            "weld_id": {"type": "string"},
            "location_description": {"type": "string"},
        },
        "required": ["weld_id", "location_description"],
    },
    "roi_classify": {
        "type": "object",
        "properties": {"roi_type": {"type": "string"}, "confidence": {"type": "number"}},
        "required": ["roi_type", "confidence"],
    },
    "token_disambiguate": {
        "type": "object",
        "properties": {"selected": {"type": "string"}, "reasoning": {"type": "string"}},
        "required": ["selected", "reasoning"],
    },
}


class VLMEngine:
    def __init__(self, config: AppConfig):
        self.config = config
        self.output_dir = ensure_dir(Path(config.pipeline.data_root) / "vlm")

    def analyze(self, roi_path: str, task_type: str, schema: dict[str, Any], options: dict[str, Any]) -> VLMTaskResult:
        prompt = build_prompt(task_type, options)
        started = time.perf_counter()
        response = ollama.chat(
            model=self.config.vlm.model,
            messages=[{"role": "user", "content": prompt, "images": [roi_path]}],
            options={"temperature": self.config.vlm.temperature, "num_ctx": self.config.vlm.num_ctx},
            format=schema,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        output_json = json.loads(response["message"]["content"])
        return VLMTaskResult(
            task_type=task_type,
            roi_id=options["roi_id"],
            weld_hint_from_ocr=options.get("weld_hint"),
            output_json=output_json,
            schema_valid=True,
            retry_count=0,
            latency_ms=latency_ms,
        )

    def analyze_layout(self, layout: LayoutPlan) -> VLMResult:
        if not self.config.vlm.enabled:
            return VLMResult(document_id=layout.document_id, model=self.config.vlm.model, tasks=[])

        tasks: list[VLMTaskResult] = []
        for roi in layout.rois:
            if roi.type != "roi_weld_label" or not roi.image_path:
                continue
            tasks.append(
                self.analyze(
                    roi.image_path,
                    "weld_location_describe",
                    TASK_SCHEMAS["weld_location_describe"],
                    {"roi_id": roi.roi_id, "weld_hint": roi.weld_hint or ""},
                )
            )

        result = VLMResult(document_id=layout.document_id, model=self.config.vlm.model, tasks=tasks)
        write_json(self.output_dir / f"{layout.document_id}.json", result.model_dump(mode="json"))
        return result


def build_prompt(task_type: str, options: dict[str, Any]) -> str:
    if task_type == "weld_location_describe":
        weld_hint = options.get("weld_hint", "")
        return (
            "You are a technical drawing assistant.\n"
            f"The weld ID detected by OCR is: {weld_hint}\n"
            "Describe where this weld is located in the piping system.\n"
            "Return JSON only with keys weld_id and location_description.\n"
            "Do not invent weld IDs not visible in the image."
        )
    if task_type == "roi_classify":
        return "Classify this ROI as one of: roi_titleblock, roi_bom_table, roi_isometric, other. Return JSON only."
    if task_type == "token_disambiguate":
        return (
            "Choose the most likely OCR token from the given candidates and explain briefly.\n"
            f"Candidates: {options.get('candidates', [])}"
        )
    raise ValueError(f"Unsupported task_type: {task_type}")

