from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from weld_assistant.config import AppConfig
from weld_assistant.contracts import BOMItem, DrawingData, ProcessingLog, StructuredDrawing, WeldItem
from weld_assistant.db.repository import SQLiteRepository


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


if __name__ == "__main__":
    unittest.main()
