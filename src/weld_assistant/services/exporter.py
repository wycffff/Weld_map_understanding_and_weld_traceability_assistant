from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from weld_assistant.config import AppConfig
from weld_assistant.contracts import StructuredDrawing
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.utils.files import ensure_dir, write_json


class FileExporter:
    def __init__(self, config: AppConfig):
        self.config = config
        self.output_dir = ensure_dir(Path(config.export.output_dir))

    def export_structured_drawing(self, drawing: StructuredDrawing) -> tuple[str, str]:
        drawing_number = drawing.drawing.drawing_number or drawing.document_id
        json_path = self.output_dir / f"{drawing_number}.structured.json"
        csv_path = self.output_dir / f"{drawing_number}.weld_progress.csv"
        write_json(json_path, drawing.to_jsonable())
        csv_path.write_text(self._build_csv_from_structured(drawing), encoding="utf-8", newline="")
        return str(json_path), str(csv_path)

    def _build_csv_from_structured(self, drawing: StructuredDrawing) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=self.config.export.csv_fields)
        writer.writeheader()
        drawing_number = drawing.drawing.drawing_number or drawing.document_id
        for weld in drawing.welds:
            writer.writerow(
                {
                    "drawing_number": drawing_number,
                    "weld_id": weld.weld_id,
                    "status": weld.status,
                    "completed_by": "",
                    "completed_at": "",
                    "inspection_status": weld.inspection_status,
                    "last_photo_id": "",
                    "last_photo_path": "",
                }
            )
        return buffer.getvalue()


class RepositoryExporter:
    def __init__(self, config: AppConfig, repository: SQLiteRepository):
        self.config = config
        self.repository = repository
        self.output_dir = ensure_dir(Path(config.export.output_dir))

    def export(self, drawing_number: str) -> tuple[str, str]:
        drawing = self.repository.get_drawing(drawing_number)
        if not drawing:
            raise ValueError(f"Drawing not found: {drawing_number}")
        welds = self.repository.list_welds(drawing_number)
        bom_items = self.repository.list_bom_items(drawing_number)
        progress_events = self.repository.list_weld_progress(drawing_number)
        photo_evidence = self.repository.list_photo_evidence(drawing_number)

        json_path = self.output_dir / f"{drawing_number}.export.json"
        csv_path = self.output_dir / f"{drawing_number}.weld_progress.csv"

        payload = {
            "drawing": dict(drawing),
            "welds": [dict(row) for row in welds],
            "bom": [dict(row) for row in bom_items],
            "progress_events": [dict(row) for row in progress_events],
            "photo_evidence": [dict(row) for row in photo_evidence],
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=self.config.export.csv_fields)
        writer.writeheader()
        latest_photos = latest_photo_by_weld(photo_evidence)
        completion_events = latest_completion_event_by_weld(progress_events)
        for weld in welds:
            completion_event = completion_events.get(weld["weld_id"])
            photo = latest_photos.get(weld["weld_id"])
            writer.writerow(
                {
                    "drawing_number": weld["drawing_number"],
                    "weld_id": weld["weld_id"],
                    "status": weld["status"],
                    "completed_by": completion_event["operator"] if completion_event else "",
                    "completed_at": completion_event["event_at"] if completion_event else "",
                    "inspection_status": weld["inspection_status"],
                    "last_photo_id": photo["photo_id"] if photo else "",
                    "last_photo_path": photo["file_path"] if photo else "",
                }
            )
        csv_path.write_text(buffer.getvalue(), encoding="utf-8", newline="")
        return str(json_path), str(csv_path)


def latest_photo_by_weld(photo_rows) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in photo_rows:
        row_dict = dict(row)
        existing = latest.get(row_dict["weld_id"])
        if not existing or row_dict["linked_at"] > existing["linked_at"]:
            latest[row_dict["weld_id"]] = row_dict
    return latest


def latest_completion_event_by_weld(progress_rows) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in progress_rows:
        row_dict = dict(row)
        if row_dict["event_type"] != "status_update":
            continue
        if row_dict["to_status"] not in {"done", "completed"}:
            continue
        existing = latest.get(row_dict["weld_id"])
        if not existing or row_dict["event_at"] > existing["event_at"]:
            latest[row_dict["weld_id"]] = row_dict
    return latest
