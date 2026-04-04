from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import ollama

from weld_assistant.config import AppConfig
from weld_assistant.contracts import LayoutPlan, OCRResult, VLMResult, VLMTaskResult
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
    "drawing_title_extract": {
        "type": "object",
        "properties": {
            "drawing_number": {"type": "string"},
            "pipe_size": {"type": "string"},
            "material_spec": {"type": "string"},
            "project_number": {"type": "string"},
            "spool_name": {"type": "string"},
        },
        "required": ["drawing_number"],
    },
    "weld_list_extract": {
        "type": "object",
        "properties": {
            "weld_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "notes": {"type": "string"},
        },
        "required": ["weld_ids"],
    },
    "review_assist": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "recommended_action": {"type": "string"},
            "candidate_weld_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "notes": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["summary", "recommended_action", "candidate_weld_ids", "confidence"],
    },
}


class VLMEngine:
    def __init__(self, config: AppConfig):
        self.config = config
        self.output_dir = ensure_dir(Path(config.pipeline.data_root) / "vlm")

    def analyze(self, roi_path: str, task_type: str, schema: dict[str, Any], options: dict[str, Any]) -> VLMTaskResult:
        prompt = build_prompt(task_type, options)
        started = time.perf_counter()
        response = self._chat(
            messages=[{"role": "user", "content": prompt, "images": [roi_path]}],
            schema=schema,
            max_output_tokens=self.config.vlm.max_output_tokens,
            timeout_sec=self.config.vlm.request_timeout_sec,
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

    def assist_review(self, review_context: dict[str, Any]) -> VLMTaskResult:
        return self.assist_review_with_timeout(
            review_context=review_context,
            timeout_sec=self.config.vlm.review_request_timeout_sec,
        )

    def assist_review_with_timeout(self, review_context: dict[str, Any], timeout_sec: int) -> VLMTaskResult:
        prompt = build_prompt("review_assist", {"review_context": review_context})
        started = time.perf_counter()
        response = self._chat(
            messages=[{"role": "user", "content": prompt}],
            schema=TASK_SCHEMAS["review_assist"],
            max_output_tokens=max(self.config.vlm.max_output_tokens, 128),
            timeout_sec=timeout_sec,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        output_json = json.loads(response["message"]["content"])
        return VLMTaskResult(
            task_type="review_assist",
            roi_id=review_context["review_id"],
            output_json=output_json,
            schema_valid=True,
            retry_count=0,
            latency_ms=latency_ms,
        )

    def analyze_layout(
        self,
        layout: LayoutPlan,
        ocr_result: OCRResult | None = None,
        enabled: bool | None = None,
    ) -> VLMResult:
        use_vlm = self.config.vlm.enabled if enabled is None else enabled
        if not use_vlm:
            return VLMResult(document_id=layout.document_id, model=self.config.vlm.model, tasks=[])

        tasks: list[VLMTaskResult] = []
        queued = 0
        for task_type, roi, options in self._build_task_plan(layout, ocr_result):
            if queued >= self.config.vlm.max_tasks_per_document:
                break
            if not roi.image_path:
                continue
            try:
                tasks.append(self.analyze(roi.image_path, task_type, TASK_SCHEMAS[task_type], options))
                queued += 1
            except Exception:
                continue

        result = VLMResult(document_id=layout.document_id, model=self.config.vlm.model, tasks=tasks)
        write_json(self.output_dir / f"{layout.document_id}.json", result.model_dump(mode="json"))
        return result

    def _chat(self, messages: list[dict[str, Any]], schema: dict[str, Any], max_output_tokens: int, timeout_sec: int):
        kwargs = {
            "model": self.config.vlm.model,
            "messages": messages,
            "options": {
                "temperature": self.config.vlm.temperature,
                "num_ctx": self.config.vlm.num_ctx,
                "num_predict": max_output_tokens,
            },
            "format": schema,
        }
        runner = (
            "import json, sys, ollama\n"
            "kwargs = json.loads(sys.stdin.read())\n"
            "try:\n"
            "    response = ollama.chat(**kwargs)\n"
            "    sys.stdout.write(json.dumps({'ok': True, 'response': response}))\n"
            "except Exception as exc:\n"
            "    sys.stdout.write(json.dumps({'ok': False, 'error': f'{type(exc).__name__}: {exc}'}))\n"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-c", runner],
                input=json.dumps(kwargs, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"Ollama request timed out after {timeout_sec}s for model {self.config.vlm.model}"
            ) from exc
        if completed.returncode != 0:
            raise RuntimeError(
                f"Ollama request failed for model {self.config.vlm.model} "
                f"(exit_code={completed.returncode}): {completed.stderr.strip()}"
            )
        stdout = completed.stdout.strip()
        if not stdout:
            raise RuntimeError(f"Ollama request exited without a response for model {self.config.vlm.model}")
        payload = json.loads(stdout)
        if not payload["ok"]:
            raise RuntimeError(payload["error"])
        return payload["response"]

    def _build_task_plan(self, layout: LayoutPlan, ocr_result: OCRResult | None) -> list[tuple[str, Any, dict[str, Any]]]:
        mode = self.config.vlm.mode
        profile = str(layout.layout_log.get("document_profile", ""))
        task_plan: list[tuple[str, Any, dict[str, Any]]] = []

        title_tokens = [token for token in (ocr_result.tokens if ocr_result else []) if token.roi_id.startswith("titleblock")]
        has_low_conf_titleblock = any(token.confidence < 0.72 for token in title_tokens)
        if mode == "always" or has_low_conf_titleblock or not title_tokens:
            titleblock_roi = next((roi for roi in layout.rois if roi.type == "roi_titleblock" and roi.image_path), None)
            if titleblock_roi:
                task_plan.append(
                    (
                        "drawing_title_extract",
                        titleblock_roi,
                        {
                            "roi_id": titleblock_roi.roi_id,
                            "ocr_preview": [token.text for token in title_tokens[:20]],
                        },
                    )
                )

        if profile == "welding_map_sheet":
            weld_list_roi = next((roi for roi in layout.rois if roi.roi_id == "weld_list" and roi.image_path), None)
            if weld_list_roi:
                weld_list_tokens = [token.text for token in (ocr_result.tokens if ocr_result else []) if token.roi_id == "weld_list"]
                task_plan.append(
                    (
                        "weld_list_extract",
                        weld_list_roi,
                        {
                            "roi_id": weld_list_roi.roi_id,
                            "ocr_preview": weld_list_tokens[:20],
                        },
                    )
                )

        for roi in layout.rois:
            if roi.type != "roi_weld_label" or not roi.image_path:
                continue
            if mode == "review_only":
                matching_token = next((token for token in (ocr_result.tokens if ocr_result else []) if token.roi_id == roi.roi_id), None)
                if matching_token and matching_token.confidence >= 0.75:
                    continue
            task_plan.append(
                (
                    "weld_location_describe",
                    roi,
                    {"roi_id": roi.roi_id, "weld_hint": roi.weld_hint or ""},
                )
            )

        return task_plan


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
    if task_type == "drawing_title_extract":
        ocr_preview = options.get("ocr_preview", [])
        return (
            "You are reading a piping drawing title block.\n"
            f"OCR preview tokens: {ocr_preview}\n"
            "Return JSON only.\n"
            "Extract the best visible drawing_number.\n"
            "If visible, also provide pipe_size, material_spec, project_number, and spool_name.\n"
            "Prefer exact visible text. Leave unclear optional fields as empty strings."
        )
    if task_type == "weld_list_extract":
        ocr_preview = options.get("ocr_preview", [])
        return (
            "You are reading a welding list or weld identifier area from a piping drawing.\n"
            f"OCR preview tokens: {ocr_preview}\n"
            "Return JSON only.\n"
            "Extract the visible weld_ids as strings in reading order.\n"
            "If the list uses numeric identifiers, return numbers like \"1\", \"2\", \"3\".\n"
            "Do not invent weld IDs that are not visible."
        )
    if task_type == "review_assist":
        review_context = json.dumps(options.get("review_context", {}), ensure_ascii=False)
        return (
            "You are assisting a local weld-traceability review workflow.\n"
            "Return JSON only.\n"
            "Keep the summary concise and action-oriented.\n"
            "recommended_action must be one of: register_welds, keep_review_open, mark_resolved, inspect_manually, rerun_vlm.\n"
            "candidate_weld_ids must only reuse identifiers already present in the provided context.\n"
            f"Review context: {review_context}"
        )
    raise ValueError(f"Unsupported task_type: {task_type}")
