from __future__ import annotations

import csv
import io
import json
import unittest
from pathlib import Path
from uuid import uuid4

from weld_assistant.config import AppConfig
from weld_assistant.contracts import DrawingData, ProcessingLog, StructuredDrawing, WeldItem
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.services.exporter import RepositoryExporter
from weld_assistant.services.progress import ProgressService


class ProgressServiceTest(unittest.TestCase):
    def test_manual_weld_registration_creates_traceable_row(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"progress_{uuid4().hex[:8]}"
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

        structured = StructuredDrawing(
            document_id="doc_progress_manual",
            drawing=DrawingData(drawing_number="DRAW-MANUAL", spool_name="DRAW-MANUAL"),
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:00:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )
        repo.import_structured_drawing(structured)

        register_event = progress.register_weld(
            "DRAW-MANUAL",
            "W77",
            location_description="Manual fallback entry",
            operator="alice",
            note="Created from UI fallback",
        )
        evidence = progress.link_photo("DRAW-MANUAL", "W77", b"fake-image", "w77.jpg", linked_by="alice")

        weld = repo.get_weld("DRAW-MANUAL", "W77")
        self.assertIsNotNone(weld)
        self.assertEqual(weld["location_description"], "Manual fallback entry")
        self.assertEqual(weld["needs_review"], 1)
        self.assertEqual(register_event.event_type, "weld_registered")
        self.assertEqual(len(repo.list_photo_evidence("DRAW-MANUAL", "W77")), 1)
        self.assertTrue(Path(evidence.file_path).exists())

    def test_bulk_weld_registration_skips_existing_and_normalizes_ids(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"progress_{uuid4().hex[:8]}"
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

        structured = StructuredDrawing(
            document_id="doc_progress_bulk",
            drawing=DrawingData(drawing_number="DRAW-BULK", spool_name="DRAW-BULK"),
            welds=[WeldItem(weld_id="W01", confidence=0.95)],
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:00:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )
        repo.import_structured_drawing(structured)

        result = progress.register_welds(
            "DRAW-BULK",
            ["W1", "W02", "W-02", "3"],
            operator="alice",
            skip_existing=True,
        )

        self.assertEqual(result["created"], ["W02", "3"])
        self.assertEqual(result["skipped_existing"], ["W01"])
        self.assertEqual([row["weld_id"] for row in repo.list_welds("DRAW-BULK")], ["3", "W01", "W02"])

    def test_status_inspection_and_photo_linking_are_persisted_and_exported(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"progress_{uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        config = AppConfig.model_validate(
            {
                "pipeline": {"data_root": str(tmpdir)},
                "database": {"path": str(tmpdir / "db" / "test.db")},
                "export": {
                    "output_dir": str(tmpdir / "exports"),
                    "csv_fields": [
                        "drawing_number",
                        "weld_id",
                        "status",
                        "completed_by",
                        "completed_at",
                        "inspection_status",
                        "last_photo_id",
                        "last_photo_path",
                    ],
                },
            }
        )
        repo = SQLiteRepository(config)
        repo.init_db()
        progress = ProgressService(repo)

        structured = StructuredDrawing(
            document_id="doc_progress_001",
            drawing=DrawingData(drawing_number="DRAW-001", spool_name="DRAW-001"),
            welds=[WeldItem(weld_id="W01", confidence=0.95)],
            processing_log=ProcessingLog(
                pipeline_version="0.1.0",
                processed_at="2026-04-04T10:00:00+03:00",
                layout_confidence="high",
                ocr_engine="test",
            ),
        )
        repo.import_structured_drawing(structured)

        progress.update_status("DRAW-001", "W01", "done", operator="alice", note="finished")
        progress.update_inspection("DRAW-001", "W01", "accepted", operator="bob", note="checked")
        evidence = progress.link_photo("DRAW-001", "W01", b"fake-image", "w01.jpg", linked_by="alice", note="as-built")

        weld = repo.get_weld("DRAW-001", "W01")
        events = repo.list_weld_progress("DRAW-001", "W01")
        photos = repo.list_photo_evidence("DRAW-001", "W01")

        self.assertIsNotNone(weld)
        self.assertEqual(weld["status"], "done")
        self.assertEqual(weld["inspection_status"], "accepted")
        self.assertEqual(len(events), 3)
        self.assertEqual({row["event_type"] for row in events}, {"status_update", "inspection_update", "photo_linked"})
        self.assertEqual(len(photos), 1)
        self.assertTrue(Path(evidence.file_path).exists())

        exporter = RepositoryExporter(config, repo)
        json_path, csv_path = exporter.export("DRAW-001")
        export_payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
        csv_rows = list(csv.DictReader(io.StringIO(Path(csv_path).read_text(encoding="utf-8"))))

        self.assertEqual(len(export_payload["progress_events"]), 3)
        self.assertEqual(len(export_payload["photo_evidence"]), 1)
        self.assertEqual(export_payload["review_queue"], [])
        self.assertEqual(csv_rows[0]["completed_by"], "alice")
        self.assertEqual(csv_rows[0]["inspection_status"], "accepted")
        self.assertEqual(csv_rows[0]["last_photo_id"], evidence.photo_id)
        self.assertTrue(csv_rows[0]["last_photo_path"].endswith(".jpg"))

    def test_link_photo_requires_existing_weld(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"progress_{uuid4().hex[:8]}"
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

        with self.assertRaises(ValueError):
            progress.link_photo("DRAW-404", "W99", b"fake-image", "missing.jpg")


if __name__ == "__main__":
    unittest.main()
