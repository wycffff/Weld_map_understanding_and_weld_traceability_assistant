from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from weld_assistant.config import AppConfig
from weld_assistant.contracts import DrawingData, LayoutPlan, OCRResult, OCRTable, OCRTableCell, OCRToken, ROI, VLMResult, VLMTaskResult
from weld_assistant.modules.fusion import (
    FusionEngine,
    build_bom_item,
    map_bom_table,
    map_weld_list_table,
    normalize_bom_quantity,
    normalize_weld_id_by_patterns,
)


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

    def test_merge_infers_numeric_weld_ids_from_welding_list_grid(self) -> None:
        config = AppConfig()
        engine = FusionEngine(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            weld_list_path = Path(tmpdir) / "weld_list.png"
            image = Image.new("L", (240, 160), color=255)
            draw = ImageDraw.Draw(image)
            for y in [10, 30, 50, 70, 90, 110, 130]:
                draw.line((10, y, 230, y), fill=0, width=2)
            image.save(weld_list_path)

            layout = LayoutPlan(
                document_id="doc_test_0003",
                rois=[
                    ROI(
                        roi_id="weld_list",
                        type="roi_bom_table",
                        bbox=[0, 0, 240, 160],
                        image_path=str(weld_list_path),
                    )
                ],
                layout_log={"layout_confidence": "high", "document_profile": "welding_map_sheet"},
            )
            ocr = OCRResult(
                document_id="doc_test_0003",
                engine="test",
                tokens=[
                    OCRToken(text="N-30-P-22009-AA1", bbox=[0, 0, 10, 10], confidence=0.95, roi_id="titleblock"),
                ],
                tables=[],
            )

            structured = engine.merge(layout, ocr, None)

        self.assertEqual([weld.weld_id for weld in structured.welds], ["1", "2", "3", "4", "5"])
        self.assertTrue(all(weld.needs_review for weld in structured.welds))
        review_item = next(item for item in structured.needs_review_items if item.item_type == "numeric_weld_ids_inferred")
        self.assertEqual(review_item.evidence["candidate_weld_ids"], ["1", "2", "3", "4", "5"])

    def test_build_bom_item_uses_unmapped_columns_and_split_tag_text(self) -> None:
        drawing = DrawingData(drawing_number="C-52")
        item, issues = build_bom_item(
            line_no=6,
            row={
                "confidence": 0.91,
                "tag": "NAMEPLATE-30 INFORMATIONTAGPLATE",
                "raw_col_0": "6",
                "raw_col_1": "1",
                "raw_col_4": "ASTM A105",
            },
            drawing=drawing,
            fallback_confidence=0.91,
        )

        self.assertEqual(item.tag, "NAMEPLATE-30")
        self.assertEqual(item.description, "Information Tag Plate")
        self.assertEqual(item.qty, "1")
        self.assertEqual(item.material, "ASTM A105")
        self.assertTrue(item.needs_review)
        self.assertIn("heuristic_normalization", issues)

    def test_build_bom_item_does_not_promote_item_number_to_quantity(self) -> None:
        drawing = DrawingData(drawing_number="C-52")
        item, issues = build_bom_item(
            line_no=3,
            row={
                "confidence": 0.88,
                "raw_col_0": "3",
                "tag": "265-03",
                "raw_col_3": "Support Bracket",
            },
            drawing=drawing,
            fallback_confidence=0.88,
        )

        self.assertEqual(item.tag, "265-03")
        self.assertEqual(item.description, "Support Bracket")
        self.assertIsNone(item.qty)
        self.assertIn("missing_qty", issues)

    def test_build_bom_item_normalizes_noisy_fabrication_pipe_row(self) -> None:
        drawing = DrawingData(drawing_number="C-52", pipe_size='4"')
        item, issues = build_bom_item(
            line_no=2,
            row={
                "confidence": 0.88,
                "tag": "261-02",
                "description": "PDFE18SCH'0C11.1S6NALL)",
            },
            drawing=drawing,
            fallback_confidence=0.88,
        )

        self.assertEqual(item.tag, "261-02")
        self.assertEqual(item.description, 'Pipe 4" SCH40')
        self.assertEqual(item.qty, "1")
        self.assertTrue(item.needs_review)
        self.assertIn("heuristic_normalization", issues)

    def test_build_bom_item_normalizes_noisy_flange_plate_row(self) -> None:
        drawing = DrawingData(drawing_number="C-52")
        item, issues = build_bom_item(
            line_no=5,
            row={
                "confidence": 0.91,
                "tag": "LFRDKO90520",
                "description": "RNDO28.15FLAN6EPLATE1CSTK",
                "raw_col_1": "1",
            },
            drawing=drawing,
            fallback_confidence=0.91,
        )

        self.assertEqual(item.tag, "LFRDKO90520")
        self.assertEqual(item.description, "Flange Plate")
        self.assertEqual(item.qty, "1")
        self.assertTrue(item.needs_review)
        self.assertIn("heuristic_normalization", issues)

    def test_merge_uses_vlm_titleblock_fallback_when_ocr_missing(self) -> None:
        config = AppConfig()
        engine = FusionEngine(config)
        layout = LayoutPlan(
            document_id="doc_test_0004",
            rois=[ROI(roi_id="titleblock", type="roi_titleblock", bbox=[0, 0, 10, 10], image_path="titleblock.png")],
            layout_log={"layout_confidence": "high"},
        )
        ocr = OCRResult(
            document_id="doc_test_0004",
            engine="test",
            tokens=[OCRToken(text="DRAWINGNO", bbox=[0, 0, 10, 10], confidence=0.61, roi_id="titleblock")],
            tables=[],
        )
        vlm = VLMResult(
            document_id="doc_test_0004",
            model="qwen3.5:0.8b",
            tasks=[
                VLMTaskResult(
                    task_type="drawing_title_extract",
                    roi_id="titleblock",
                    output_json={
                        "drawing_number": "C-52",
                        "pipe_size": '4"',
                        "material_spec": "ASTM A106 GR B",
                        "spool_name": "52",
                        "project_number": "PRJ-01",
                    },
                )
            ],
        )

        structured = engine.merge(layout, ocr, vlm)

        self.assertEqual(structured.drawing.drawing_number, "C-52")
        self.assertEqual(structured.drawing.pipe_size, '4"')
        self.assertEqual(structured.drawing.material_spec, "ASTM A106 GR B")
        self.assertEqual(structured.drawing.project_number, "PRJ-01")
        self.assertIn("drawing_number_from_vlm", [item.item_type for item in structured.needs_review_items])

    def test_merge_adds_vlm_weld_ids_when_ocr_has_none(self) -> None:
        config = AppConfig()
        engine = FusionEngine(config)
        layout = LayoutPlan(
            document_id="doc_test_0005",
            rois=[ROI(roi_id="weld_list", type="roi_bom_table", bbox=[0, 0, 10, 10])],
            layout_log={"layout_confidence": "high", "document_profile": "welding_map_sheet"},
        )
        ocr = OCRResult(
            document_id="doc_test_0005",
            engine="test",
            tokens=[],
            tables=[],
        )
        vlm = VLMResult(
            document_id="doc_test_0005",
            model="qwen3.5:0.8b",
            tasks=[
                VLMTaskResult(
                    task_type="weld_list_extract",
                    roi_id="weld_list",
                    output_json={"weld_ids": ["1", "2", "3"], "notes": "numeric list"},
                )
            ],
        )

        structured = engine.merge(layout, ocr, vlm)

        self.assertEqual([weld.weld_id for weld in structured.welds], ["1", "2", "3"])
        self.assertTrue(all(weld.provenance.vlm_used for weld in structured.welds))
        review_item = next(item for item in structured.needs_review_items if item.item_type == "weld_ids_from_vlm")
        self.assertEqual(review_item.evidence["candidate_weld_ids"], ["1", "2", "3"])

    def test_map_bom_table_uses_semantic_headers_and_body_inference(self) -> None:
        rows, raw_cols = map_bom_table(
            [
                OCRTableCell(row=0, col=3, text="PARTSLIST", confidence=0.99),
                OCRTableCell(row=1, col=0, text="ITBM", confidence=0.9),
                OCRTableCell(row=1, col=2, text="PARTNUMBER", confidence=0.9),
                OCRTableCell(row=1, col=4, text="HEAT_NO", confidence=0.9),
                OCRTableCell(row=1, col=5, text="PO_NO", confidence=0.9),
                OCRTableCell(row=2, col=0, text="1", confidence=0.9),
                OCRTableCell(row=2, col=1, text="1", confidence=0.9),
                OCRTableCell(row=2, col=2, text="261-01", confidence=0.9),
                OCRTableCell(row=2, col=3, text="PIPE 30", confidence=0.9),
                OCRTableCell(row=3, col=0, text="6.4", confidence=0.9),
                OCRTableCell(row=3, col=1, text="1", confidence=0.9),
                OCRTableCell(row=3, col=2, text="504-C4", confidence=0.9),
                OCRTableCell(row=3, col=3, text="RING SUPPORT", confidence=0.9),
                OCRTableCell(row=3, col=4, text="18C846", confidence=0.9),
                OCRTableCell(row=3, col=5, text="6044-00", confidence=0.9),
            ]
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["tag"], "261-01")
        self.assertEqual(rows[0]["qty"], "1")
        self.assertEqual(rows[0]["description"], "PIPE 30")
        self.assertEqual(rows[0]["source_line_no"], "1")
        self.assertEqual(rows[1]["tag"], "504-C4")
        self.assertEqual(rows[1]["description"], "RING SUPPORT")
        self.assertEqual(raw_cols, {})

    def test_map_bom_table_skips_group_headers_and_stops_before_weld_list(self) -> None:
        rows, raw_cols = map_bom_table(
            [
                OCRTableCell(row=0, col=3, text="BILL OF MATERIAL", confidence=0.99),
                OCRTableCell(row=1, col=0, text="No", confidence=0.95),
                OCRTableCell(row=1, col=1, text="Length", confidence=0.95),
                OCRTableCell(row=1, col=4, text="Description", confidence=0.95),
                OCRTableCell(row=1, col=5, text="Material", confidence=0.95),
                OCRTableCell(row=2, col=0, text="1", confidence=0.91),
                OCRTableCell(row=2, col=1, text='3\'-1"', confidence=0.91),
                OCRTableCell(row=2, col=4, text="PIPE SMLS BEXBE", confidence=0.91),
                OCRTableCell(row=2, col=5, text="A106 GR. B", confidence=0.91),
                OCRTableCell(row=3, col=4, text="Flanges", confidence=0.94),
                OCRTableCell(row=4, col=0, text="No", confidence=0.95),
                OCRTableCell(row=4, col=1, text="Qty", confidence=0.95),
                OCRTableCell(row=4, col=4, text="Description", confidence=0.95),
                OCRTableCell(row=4, col=5, text="Material", confidence=0.95),
                OCRTableCell(row=5, col=1, text="1", confidence=0.91),
                OCRTableCell(row=5, col=4, text="FLANGE RF WN", confidence=0.91),
                OCRTableCell(row=5, col=5, text="A105 GR II", confidence=0.91),
                OCRTableCell(row=6, col=4, text="VELD LIST", confidence=0.96),
                OCRTableCell(row=7, col=0, text="Weld ID", confidence=0.96),
                OCRTableCell(row=7, col=1, text="Welder ID", confidence=0.96),
            ]
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["qty"], '3\'-1"')
        self.assertEqual(rows[0]["description"], "PIPE SMLS BEXBE")
        self.assertEqual(rows[1]["description"], "FLANGE RF WN")
        self.assertEqual(raw_cols, {})

    def test_map_weld_list_table_uses_semantic_headers(self) -> None:
        rows, raw_cols = map_weld_list_table(
            [
                OCRTableCell(row=0, col=0, text="WELDING LIST", confidence=0.99),
                OCRTableCell(row=1, col=0, text="WELD NO", confidence=0.95),
                OCRTableCell(row=1, col=1, text="SIZE", confidence=0.95),
                OCRTableCell(row=1, col=2, text="TYPE", confidence=0.95),
                OCRTableCell(row=1, col=3, text="WPSNO", confidence=0.95),
                OCRTableCell(row=1, col=4, text="REMARKS", confidence=0.95),
                OCRTableCell(row=2, col=0, text="1", confidence=0.91),
                OCRTableCell(row=2, col=1, text='3/4"', confidence=0.91),
                OCRTableCell(row=2, col=2, text="BW", confidence=0.91),
                OCRTableCell(row=2, col=3, text="S10", confidence=0.91),
                OCRTableCell(row=2, col=4, text="FIELD", confidence=0.91),
                OCRTableCell(row=3, col=0, text="2", confidence=0.91),
                OCRTableCell(row=3, col=1, text='1"', confidence=0.91),
                OCRTableCell(row=3, col=2, text="FW", confidence=0.91),
                OCRTableCell(row=3, col=3, text="S11", confidence=0.91),
                OCRTableCell(row=3, col=4, text="SHOP", confidence=0.91),
            ]
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["weld_id"], "1")
        self.assertEqual(rows[0]["pipe_size"], "3/4")
        self.assertEqual(rows[0]["weld_type"], "BW")
        self.assertEqual(rows[0]["wps_number"], "S10")
        self.assertEqual(rows[0]["remarks"], "FIELD")
        self.assertEqual(raw_cols, {})

    def test_normalize_weld_id_by_patterns_supports_alphabetic_and_hyphenated_ids(self) -> None:
        patterns = [r"^[A-G]$", r"^\d{3}$", r"^[A-Z]\d*-\d+$"]

        self.assertEqual(normalize_weld_id_by_patterns("A", patterns), "A")
        self.assertEqual(normalize_weld_id_by_patterns("001", patterns), "001")
        self.assertEqual(normalize_weld_id_by_patterns("G1-1", patterns), "G1-1")

    def test_normalize_bom_quantity_preserves_imperial_lengths(self) -> None:
        self.assertEqual(normalize_bom_quantity('3\'-1"', None, None), ('3\'-1"', None, False))
        self.assertEqual(normalize_bom_quantity("147/8*", None, None), ("147/8*", None, False))
        self.assertEqual(normalize_bom_quantity("0-1178", None, None), ("0-1178", None, False))

    def test_build_bom_item_uses_line_number_as_simple_spool_tag(self) -> None:
        drawing = DrawingData(drawing_number="SG-3-HWS-SP-0001A", drawing_type="simple_spool")
        item, issues = build_bom_item(
            line_no=4,
            row={
                "confidence": 0.91,
                "qty": "1",
                "description": "FLANGE RF WN",
                "material": "A105 GR II",
            },
            drawing=drawing,
            fallback_confidence=0.91,
        )

        self.assertEqual(item.tag, "4")
        self.assertEqual(item.qty, "1")
        self.assertIn("heuristic_normalization", issues)

    def test_build_bom_item_prefers_simple_spool_length_column_for_qty(self) -> None:
        drawing = DrawingData(drawing_number="SG-3-HWS-SP-0001A", drawing_type="simple_spool")
        item, _ = build_bom_item(
            line_no=1,
            row={
                "confidence": 0.95,
                "qty": "1",
                "raw_col_1": '3\'-1"',
                "raw_col_2": "4",
                "description": "PIPESMLSBEXBE",
                "material": "A106GR.B",
            },
            drawing=drawing,
            fallback_confidence=0.95,
        )

        self.assertEqual(item.tag, "1")
        self.assertEqual(item.qty, '3\'-1"')

    def test_build_bom_item_ignores_imperial_value_as_simple_spool_tag(self) -> None:
        drawing = DrawingData(drawing_number="SG-3-HWS-SP-0001A", drawing_type="simple_spool")
        item, _ = build_bom_item(
            line_no=3,
            row={
                "confidence": 0.95,
                "qty": "3",
                "raw_col_1": "0-1178",
                "description": "PIPESMLSBEXBE",
                "material": "A106GR.B",
            },
            drawing=drawing,
            fallback_confidence=0.95,
        )

        self.assertEqual(item.tag, "3")
        self.assertEqual(item.qty, "0-1178")


if __name__ == "__main__":
    unittest.main()
