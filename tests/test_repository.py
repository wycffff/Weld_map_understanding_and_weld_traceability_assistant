from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from weld_assistant.config import AppConfig
from weld_assistant.contracts import BOMItem, DrawingData, ProcessingLog, StructuredDrawing, WeldItem
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.services.progress import ProgressService


class RepositoryTest(unittest.TestCase):
    def test_import_and_query_structured_drawing(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"repo_{uuid4().hex[:8]}"
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
            document_id="doc_test_0001",
            drawing=DrawingData(drawing_number="4-N1-101", spool_name="N1-101"),
            bom=[BOMItem(line_no=1, tag="P-101", qty="12", material="ASTM A106")],
            welds=[WeldItem(weld_id="W01", confidence=0.95)],
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:00:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )
        repo.import_structured_drawing(structured)

        drawing = repo.get_drawing("4-N1-101")
        welds = repo.list_welds("4-N1-101")
        bom_items = repo.list_bom_items("4-N1-101")

        self.assertIsNotNone(drawing)
        self.assertEqual(len(welds), 1)
        self.assertEqual(len(bom_items), 1)

    def test_overwrite_replaces_rows_by_document_id(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"repo_{uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        config = AppConfig.model_validate(
            {
                "pipeline": {"data_root": str(tmpdir)},
                "database": {"path": str(tmpdir / "db" / "test.db")},
            }
        )
        repo = SQLiteRepository(config)
        repo.init_db()
        progress = ProgressService(repo)

        original = StructuredDrawing(
            document_id="doc_test_same",
            drawing=DrawingData(drawing_number="OLD-001", spool_name="OLD-001"),
            bom=[BOMItem(line_no=1, tag="OLD", qty="1", material="ASTM A105")],
            welds=[WeldItem(weld_id="W01", confidence=0.95)],
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:00:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )
        updated = StructuredDrawing(
            document_id="doc_test_same",
            drawing=DrawingData(drawing_number="NEW-001", spool_name="NEW-001"),
            bom=[BOMItem(line_no=1, tag="NEW", qty="2", material="ASTM A106")],
            welds=[WeldItem(weld_id="W02", confidence=0.96)],
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:05:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )

        repo.import_structured_drawing(original)
        progress.update_status("OLD-001", "W01", "done", operator="tester")
        progress.link_photo("OLD-001", "W01", b"fake-image", "w01.jpg", linked_by="tester")
        repo.import_structured_drawing(updated, overwrite=True)

        self.assertIsNone(repo.get_drawing("OLD-001"))
        self.assertIsNotNone(repo.get_drawing("NEW-001"))
        self.assertEqual([row["weld_id"] for row in repo.list_welds("NEW-001")], ["W02"])
        self.assertEqual([row["tag"] for row in repo.list_bom_items("NEW-001")], ["NEW"])
        self.assertEqual(repo.list_weld_progress("OLD-001"), [])
        self.assertEqual(repo.list_photo_evidence("OLD-001"), [])

    def test_search_drawings_matches_normalized_queries(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"repo_{uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        config = AppConfig.model_validate(
            {
                "pipeline": {"data_root": str(tmpdir)},
                "database": {"path": str(tmpdir / "db" / "test.db")},
            }
        )
        repo = SQLiteRepository(config)
        repo.init_db()

        drawings = [
            StructuredDrawing(
                document_id="doc_a",
                drawing=DrawingData(drawing_number="C-52", spool_name="52"),
                processing_log=ProcessingLog(
                    pipeline_version="0.1.0",
                    processed_at="2026-04-04T10:00:00+03:00",
                    layout_confidence="high",
                    ocr_engine="test",
                ),
            ),
            StructuredDrawing(
                document_id="doc_b",
                drawing=DrawingData(drawing_number="N-30-P-22009-AA1", spool_name="30-P-22009-AA1"),
                processing_log=ProcessingLog(
                    pipeline_version="0.1.0",
                    processed_at="2026-04-04T10:01:00+03:00",
                    layout_confidence="high",
                    ocr_engine="test",
                ),
            ),
        ]
        for drawing in drawings:
            repo.import_structured_drawing(drawing)

        self.assertEqual(repo.search_drawings("C52")[0]["drawing_number"], "C-52")
        self.assertEqual(repo.search_drawings("c-52")[0]["drawing_number"], "C-52")
        self.assertEqual(repo.search_drawings("22009")[0]["drawing_number"], "N-30-P-22009-AA1")


if __name__ == "__main__":
    unittest.main()
