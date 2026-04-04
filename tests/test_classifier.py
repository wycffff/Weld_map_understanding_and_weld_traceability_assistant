from __future__ import annotations

import unittest

from weld_assistant.contracts import OCRResult, OCRToken
from weld_assistant.modules.classifier import DrawingClassifier


class DrawingClassifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = DrawingClassifier()

    def test_classifies_pipeline_isometric(self) -> None:
        result = self.classifier.classify(
            OCRResult(
                document_id="doc_test_pipeline",
                engine="test",
                tokens=[
                    OCRToken(text="WELDING LIST", bbox=[0, 0, 1, 1], confidence=0.9, roi_id="preview"),
                    OCRToken(text="PIPELINE NAME", bbox=[0, 0, 1, 1], confidence=0.9, roi_id="preview"),
                ],
            )
        )

        self.assertEqual(result.drawing_type, "pipeline_isometric")
        self.assertEqual(result.document_profile, "welding_map_sheet")
        self.assertTrue(result.supported)

    def test_rejects_pressure_vessel_drawings(self) -> None:
        result = self.classifier.classify(
            OCRResult(
                document_id="doc_test_vessel",
                engine="test",
                tokens=[
                    OCRToken(text="SHELL SIDE", bbox=[0, 0, 1, 1], confidence=0.9, roi_id="preview"),
                    OCRToken(text="TUBE SIDE", bbox=[0, 0, 1, 1], confidence=0.9, roi_id="preview"),
                    OCRToken(text="NATIONAL BOARD", bbox=[0, 0, 1, 1], confidence=0.9, roi_id="preview"),
                ],
            )
        )

        self.assertEqual(result.drawing_type, "pressure_vessel")
        self.assertFalse(result.supported)
        self.assertEqual(result.rejection_reason, "drawing_type_not_supported")

    def test_classifies_unknown_when_keywords_are_missing(self) -> None:
        result = self.classifier.classify(
            OCRResult(
                document_id="doc_test_unknown",
                engine="test",
                tokens=[OCRToken(text="UNRELATED TITLE", bbox=[0, 0, 1, 1], confidence=0.9, roi_id="preview")],
            )
        )

        self.assertEqual(result.drawing_type, "unknown")
        self.assertFalse(result.supported)
        self.assertEqual(result.rejection_reason, "drawing_type_unknown")


if __name__ == "__main__":
    unittest.main()
