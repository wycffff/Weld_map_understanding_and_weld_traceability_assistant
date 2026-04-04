from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from weld_assistant.config import AppConfig
from weld_assistant.contracts import DrawingData, ProcessingLog, ReviewItem, StructuredDrawing, VLMTaskResult, WeldItem
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.modules.vlm import VLMEngine
from weld_assistant.services.review import ReviewService


class ReviewServiceTest(unittest.TestCase):
    def test_heuristic_review_suggestion_extracts_candidate_weld_ids(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"review_{uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        config = AppConfig.model_validate(
            {
                "pipeline": {"data_root": str(tmpdir)},
                "database": {"path": str(tmpdir / "db" / "test.db")},
            }
        )
        repo = SQLiteRepository(config)
        repo.init_db()
        service = ReviewService(repo, VLMEngine(config))

        structured = StructuredDrawing(
            document_id="doc_review_001",
            drawing=DrawingData(drawing_number="DRAW-REVIEW", spool_name="DRAW-REVIEW"),
            welds=[WeldItem(weld_id="W01", confidence=0.95)],
            needs_review_items=[
                ReviewItem(
                    item_type="weld_ids_from_vlm",
                    field="weld_id",
                    roi_id="weld_list",
                    vlm_value="W02, 3",
                    message="Additional weld identifiers require review.",
                    evidence={"vlm_weld_ids": ["W02", "3"]},
                )
            ],
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:00:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )
        repo.import_structured_drawing(structured)
        review_id = repo.list_review_queue("DRAW-REVIEW", unresolved_only=True)[0]["review_id"]

        suggestion = service.suggest_review_item(review_id, use_llm=False)

        self.assertEqual(suggestion["heuristic"]["recommended_action"], "register_welds")
        self.assertEqual(suggestion["heuristic"]["candidate_weld_ids"], ["W02", "3"])
        self.assertEqual(suggestion["context"]["existing_weld_ids"], ["W01"])
        self.assertIn("DRAW-REVIEW", suggestion["heuristic"]["summary"])

    def test_llm_overlay_is_sanitized_against_known_candidate_ids(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"review_{uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        config = AppConfig.model_validate(
            {
                "pipeline": {"data_root": str(tmpdir)},
                "database": {"path": str(tmpdir / "db" / "test.db")},
            }
        )
        repo = SQLiteRepository(config)
        repo.init_db()

        structured = StructuredDrawing(
            document_id="doc_review_002",
            drawing=DrawingData(drawing_number="DRAW-REVIEW-2", spool_name="DRAW-REVIEW-2"),
            needs_review_items=[
                ReviewItem(
                    item_type="weld_ids_from_vlm",
                    field="weld_id",
                    roi_id="weld_list",
                    vlm_value="W02",
                    message="Review the candidate weld.",
                    evidence={"vlm_weld_ids": ["W02"]},
                )
            ],
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:00:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )
        repo.import_structured_drawing(structured)
        review_id = repo.list_review_queue("DRAW-REVIEW-2", unresolved_only=True)[0]["review_id"]

        mock_vlm = Mock()
        mock_vlm.assist_review.return_value = VLMTaskResult(
            task_type="review_assist",
            roi_id=review_id,
            output_json={
                "summary": "Model thinks the weld is probably W09 but keep it short.",
                "recommended_action": "inspect_manually",
                "candidate_weld_ids": ["W09", "W02"],
                "notes": "Only W02 is supported by the review payload.",
                "confidence": 0.44,
            },
            latency_ms=321,
        )
        service = ReviewService(repo, mock_vlm)

        suggestion = service.suggest_review_item(review_id, use_llm=True)

        self.assertEqual(suggestion["llm"]["recommended_action"], "inspect_manually")
        self.assertEqual(suggestion["llm"]["candidate_weld_ids"], ["W02"])
        self.assertEqual(suggestion["final"]["candidate_weld_ids"], ["W02"])
        self.assertEqual(suggestion["final"]["model_latency_ms"], 321)

    def test_timeout_override_is_forwarded_to_review_assistant(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"review_{uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        config = AppConfig.model_validate(
            {
                "pipeline": {"data_root": str(tmpdir)},
                "database": {"path": str(tmpdir / "db" / "test.db")},
            }
        )
        repo = SQLiteRepository(config)
        repo.init_db()

        structured = StructuredDrawing(
            document_id="doc_review_003",
            drawing=DrawingData(drawing_number="DRAW-REVIEW-3", spool_name="DRAW-REVIEW-3"),
            needs_review_items=[
                ReviewItem(
                    item_type="weld_ids_from_vlm",
                    field="weld_id",
                    roi_id="weld_list",
                    vlm_value="W02",
                    message="Review the candidate weld.",
                    evidence={"vlm_weld_ids": ["W02"]},
                )
            ],
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:00:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )
        repo.import_structured_drawing(structured)
        review_id = repo.list_review_queue("DRAW-REVIEW-3", unresolved_only=True)[0]["review_id"]

        mock_vlm = Mock()
        mock_vlm.assist_review_with_timeout.return_value = VLMTaskResult(
            task_type="review_assist",
            roi_id=review_id,
            output_json={
                "summary": "Use W02 only.",
                "recommended_action": "register_welds",
                "candidate_weld_ids": ["W02"],
                "notes": "",
                "confidence": 0.51,
            },
            latency_ms=222,
        )
        service = ReviewService(repo, mock_vlm)

        suggestion = service.suggest_review_item(review_id, use_llm=True, timeout_override_sec=240)

        mock_vlm.assist_review_with_timeout.assert_called_once()
        self.assertEqual(mock_vlm.assist_review_with_timeout.call_args.args[1], 240)
        self.assertEqual(suggestion["llm"]["candidate_weld_ids"], ["W02"])


if __name__ == "__main__":
    unittest.main()
