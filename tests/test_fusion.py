from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weld_assistant.config import AppConfig
from weld_assistant.contracts import LayoutPlan, OCRResult, OCRTable, OCRTableCell, OCRToken, VLMResult, VLMTaskResult
from weld_assistant.modules.fusion import FusionEngine


class FusionEngineTest(unittest.TestCase):
    def test_merge_builds_structured_drawing(self) -> None:
        config = AppConfig()
        engine = FusionEngine(config)
        layout = LayoutPlan(
            document_id="doc_test_0001",
            rois=[],
            layout_log={"layout_confidence": "high"},
        )
        ocr = OCRResult(
            document_id="doc_test_0001",
            engine="test",
            tokens=[
                OCRToken(text='4"-N1-101', bbox=[0, 0, 10, 10], confidence=0.95, roi_id="titleblock"),
                OCRToken(text="ASTM A106 Gr.B", bbox=[0, 0, 10, 10], confidence=0.91, roi_id="note"),
                OCRToken(text='4"', bbox=[0, 0, 10, 10], confidence=0.90, roi_id="titleblock"),
                OCRToken(text="W-01", bbox=[0, 0, 10, 10], confidence=0.92, roi_id="weld_W01"),
            ],
            tables=[
                OCRTable(
                    roi_id="bom",
                    cells=[
                        OCRTableCell(row=0, col=0, text="TAG", confidence=0.9),
                        OCRTableCell(row=0, col=1, text="DESCRIPTION", confidence=0.9),
                        OCRTableCell(row=0, col=2, text="QTY", confidence=0.9),
                        OCRTableCell(row=0, col=3, text="MATERIAL", confidence=0.9),
                        OCRTableCell(row=1, col=0, text="P-101", confidence=0.9),
                        OCRTableCell(row=1, col=1, text='Pipe 4" SCH40', confidence=0.9),
                        OCRTableCell(row=1, col=2, text="12", confidence=0.9),
                        OCRTableCell(row=1, col=3, text="ASTM A106", confidence=0.9),
                    ],
                    confidence=0.9,
                )
            ],
        )
        vlm = VLMResult(
            document_id="doc_test_0001",
            model="qwen3.5:0.8b",
            tasks=[
                VLMTaskResult(
                    task_type="weld_location_describe",
                    roi_id="weld_W01",
                    output_json={"weld_id": "W-01", "location_description": "Left joint"},
                )
            ],
        )

        structured = engine.merge(layout, ocr, vlm)

        self.assertEqual(structured.drawing.drawing_number, '4-N1-101')
        self.assertEqual(structured.welds[0].weld_id, "W01")
        self.assertEqual(structured.welds[0].location_description, "Left joint")
        self.assertEqual(structured.bom[0].tag, "P-101")

    def test_merge_normalizes_multiline_bom_rows(self) -> None:
        config = AppConfig()
        engine = FusionEngine(config)
        layout = LayoutPlan(
            document_id="doc_test_0002",
            rois=[],
            layout_log={"layout_confidence": "high"},
        )
        ocr = OCRResult(
            document_id="doc_test_0002",
            engine="test",
            tokens=[
                OCRToken(text="4CN1-101", bbox=[0, 0, 10, 10], confidence=0.95, roi_id="titleblock"),
                OCRToken(text="PPE4SCH40", bbox=[0, 0, 10, 10], confidence=0.95, roi_id="titleblock"),
                OCRToken(text="ASTMAI06GRB", bbox=[0, 0, 10, 10], confidence=0.95, roi_id="note"),
            ],
            tables=[
                OCRTable(
                    roi_id="bom",
                    cells=[
                        OCRTableCell(row=0, col=0, text="TAG", confidence=0.9),
                        OCRTableCell(row=0, col=1, text="DESCRIPTION", confidence=0.9),
                        OCRTableCell(row=0, col=2, text="QTY", confidence=0.9),
                        OCRTableCell(row=0, col=3, text="MATERIAL", confidence=0.9),
                        OCRTableCell(row=1, col=0, text="P-101", confidence=0.9),
                        OCRTableCell(row=1, col=1, text='Poe4"', confidence=0.9),
                        OCRTableCell(row=1, col=1, text="COHOS", confidence=0.9),
                        OCRTableCell(row=1, col=2, text="12m", confidence=0.9),
                        OCRTableCell(row=1, col=3, text="ASTY", confidence=0.9),
                        OCRTableCell(row=1, col=3, text="AXOS", confidence=0.9),
                        OCRTableCell(row=2, col=1, text="Fanoe4", confidence=0.9),
                        OCRTableCell(row=2, col=1, text="RF1SOE", confidence=0.9),
                        OCRTableCell(row=2, col=3, text="ASTX", confidence=0.9),
                        OCRTableCell(row=2, col=3, text="AOS", confidence=0.9),
                        OCRTableCell(row=3, col=0, text="-0", confidence=0.9),
                        OCRTableCell(row=3, col=1, text="Cete", confidence=0.9),
                        OCRTableCell(row=3, col=1, text='vave4"', confidence=0.9),
                        OCRTableCell(row=3, col=3, text="ASTM", confidence=0.9),
                        OCRTableCell(row=3, col=3, text="A27M", confidence=0.9),
                    ],
                    confidence=0.9,
                )
            ],
        )

        structured = engine.merge(layout, ocr, None)

        self.assertEqual(structured.drawing.drawing_number, "4-N1-101")
        self.assertEqual(len(structured.bom), 3)
        self.assertEqual(structured.bom[0].description, 'Pipe 4" SCH40')
        self.assertEqual(structured.bom[0].qty, "12")
        self.assertEqual(structured.bom[0].uom, "METER")
        self.assertEqual(structured.bom[0].material, "ASTM A106 GR B")
        self.assertEqual(structured.bom[1].tag, "F-RF150")
        self.assertEqual(structured.bom[1].description, 'Flange 4" RF 150#')
        self.assertEqual(structured.bom[1].material, "ASTM A105")
        self.assertEqual(structured.bom[2].tag, "V-0-4")
        self.assertEqual(structured.bom[2].description, 'Gate Valve 4"')
        self.assertEqual(structured.bom[2].material, "ASTM A216")
        self.assertTrue(all(item.needs_review for item in structured.bom[1:]))


if __name__ == "__main__":
    unittest.main()
