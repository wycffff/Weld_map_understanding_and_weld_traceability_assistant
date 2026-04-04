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

        json_path = self.output_dir / f"{drawing_number}.export.json"
        csv_path = self.output_dir / f"{drawing_number}.weld_progress.csv"

        payload = {
            "drawing": dict(drawing),
            "welds": [dict(row) for row in welds],
            "bom": [dict(row) for row in bom_items],
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=self.config.export.csv_fields)
        writer.writeheader()
        for weld in welds:
            writer.writerow(
                {
                    "drawing_number": weld["drawing_number"],
                    "weld_id": weld["weld_id"],
                    "status": weld["status"],
                    "completed_by": "",
                    "completed_at": "",
                    "inspection_status": weld["inspection_status"],
                    "last_photo_id": "",
                    "last_photo_path": "",
                }
            )
        csv_path.write_text(buffer.getvalue(), encoding="utf-8", newline="")
        return str(json_path), str(csv_path)
