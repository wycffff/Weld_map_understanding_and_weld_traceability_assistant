from __future__ import annotations

import unittest

from weld_assistant.contracts import DrawingData, ProcessingLog, StructuredDrawing, WeldItem
from weld_assistant.services.evaluation import evaluate_structured_drawing, summarize_evaluation


class EvaluationServiceTest(unittest.TestCase):
    def test_evaluate_structured_drawing_reports_weld_precision_and_recall(self) -> None:
        structured = StructuredDrawing(
            document_id="doc_eval_001",
            drawing=DrawingData(drawing_number="DRAW-001"),
            welds=[WeldItem(weld_id="W01"), WeldItem(weld_id="W02")],
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:00:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )

        report = evaluate_structured_drawing(
            input_file="samples/real/demo.png",
            structured=structured,
            sample_truth={
                "drawing_number": "DRAW-001",
                "weld_ids": ["W01", "W03"],
                "bom_count": 1,
            },
        )

        self.assertTrue(report["drawing_number_match"])
        self.assertEqual(report["weld_true_positive_ids"], ["W01"])
        self.assertEqual(report["weld_false_positive_ids"], ["W02"])
        self.assertEqual(report["weld_false_negative_ids"], ["W03"])
        self.assertEqual(report["weld_precision"], 0.5)
        self.assertEqual(report["weld_recall"], 0.5)

    def test_summarize_evaluation_ignores_excluded_samples(self) -> None:
        summary = summarize_evaluation(
            [
                {
                    "drawing_number_match": True,
                    "weld_true_positive_ids": ["W01"],
                    "weld_false_positive_ids": [],
                    "weld_false_negative_ids": [],
                    "excluded_from_metrics": False,
                },
                {
                    "drawing_number_match": False,
                    "weld_true_positive_ids": [],
                    "weld_false_positive_ids": ["W99"],
                    "weld_false_negative_ids": ["W01"],
                    "excluded_from_metrics": True,
                },
            ]
        )

        self.assertEqual(summary["included_sample_count"], 1)
        self.assertEqual(summary["drawing_number_accuracy"], 1.0)
        self.assertEqual(summary["weld_precision_micro"], 1.0)
        self.assertEqual(summary["weld_recall_micro"], 1.0)


if __name__ == "__main__":
    unittest.main()
