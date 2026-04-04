from __future__ import annotations

import csv
import io
import json
from datetime import datetime
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
        review_queue = self.repository.list_review_queue(drawing_number, unresolved_only=False)

        json_path = self.output_dir / f"{drawing_number}.export.json"
        csv_path = self.output_dir / f"{drawing_number}.weld_progress.csv"

        payload = {
            "drawing": dict(drawing),
            "welds": [dict(row) for row in welds],
            "bom": [dict(row) for row in bom_items],
            "progress_events": [dict(row) for row in progress_events],
            "photo_evidence": [dict(row) for row in photo_evidence],
            "review_queue": [dict(row) for row in review_queue],
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

    def export_weld_log_csv(self, drawing_number: str) -> str:
        drawing = self.repository.get_drawing(drawing_number)
        if not drawing:
            raise ValueError(f"Drawing not found: {drawing_number}")

        weld_rows = self.repository.list_welds(drawing_number)
        progress_rows = self.repository.list_weld_progress(drawing_number)

        csv_path = self.output_dir / f"{drawing_number}.weld_log.csv"
        csv_path.write_text(
            build_weld_log_csv(
                drawing=dict(drawing),
                weld_rows=[dict(row) for row in weld_rows],
                progress_rows=[dict(row) for row in progress_rows],
            ),
            encoding="utf-8",
            newline="",
        )
        return str(csv_path)


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


def build_weld_log_csv(drawing: dict, weld_rows: list[dict], progress_rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["WELD LOG"])
    writer.writerow(["Drawing", drawing.get("drawing_number", ""), "P&ID", "", "Project", drawing.get("project_number", "") or ""])
    writer.writerow(["Pack", drawing.get("spool_name", "") or "", "System", "", "Client", ""])
    writer.writerow([])

    writer.writerow(
        [
            "WELD #",
            "JOINT TYPE",
            "DIAMETER",
            "SCHEDULE",
            "THICKNESS",
            "WPS",
            "ROOT_PERSON",
            "ROOT_DATE",
            "ROOT_STATUS",
            "WELD_PERSON",
            "WELD_DATE",
            "WELD_STATUS",
            "VT_PERSON",
            "VT_DATE",
            "VT_STATUS",
            "RT_PERSON",
            "RT_DATE",
            "RT_STATUS",
        ]
    )

    stage_events = latest_stage_events_by_weld(progress_rows)
    for weld in weld_rows:
        weld_id = weld.get("weld_id", "")
        root_event = stage_events.get((weld_id, "root"))
        weld_event = stage_events.get((weld_id, "weld"))
        vt_event = stage_events.get((weld_id, "vt"))
        rt_event = stage_events.get((weld_id, "rt"))

        writer.writerow(
            [
                weld_id,
                weld.get("weld_type") or "",
                weld.get("pipe_size") or "",
                "",
                "",
                weld.get("wps_number") or "",
                event_person(root_event),
                event_date(root_event),
                event_status(root_event),
                event_person(weld_event),
                event_date(weld_event),
                event_status(weld_event, fallback=weld.get("status")),
                event_person(vt_event),
                event_date(vt_event),
                event_status(vt_event, fallback=weld.get("inspection_status")),
                event_person(rt_event),
                event_date(rt_event),
                event_status(rt_event),
            ]
        )

    return buffer.getvalue()


def latest_stage_events_by_weld(progress_rows: list[dict]) -> dict[tuple[str, str], dict]:
    latest: dict[tuple[str, str], dict] = {}
    for row in progress_rows:
        row_dict = dict(row)
        stage = infer_weld_log_stage(row_dict)
        if not stage:
            continue
        key = (row_dict.get("weld_id", ""), stage)
        existing = latest.get(key)
        if not existing or row_dict.get("event_at", "") > existing.get("event_at", ""):
            latest[key] = row_dict
    return latest


def infer_weld_log_stage(progress_row: dict) -> str | None:
    event_type = str(progress_row.get("event_type") or "").lower()
    search_blob = " ".join(
        [
            str(progress_row.get("event_type") or ""),
            str(progress_row.get("from_status") or ""),
            str(progress_row.get("to_status") or ""),
            str(progress_row.get("note") or ""),
        ]
    ).upper()

    if any(token in event_type for token in ("root_", "_root", "root")) or "ROOT" in search_blob:
        return "root"
    if any(token in event_type for token in ("vt_", "_vt")) or "VISUAL" in search_blob or " VT" in f" {search_blob}":
        return "vt"
    if any(token in event_type for token in ("rt_", "_rt")) or any(token in search_blob for token in ("RADIOGRAPH", "X-RAY", "XRAY", " RT")):
        return "rt"
    if event_type == "status_update" or any(token in event_type for token in ("weld_", "_weld")):
        return "weld"
    if event_type == "inspection_update":
        return "vt"
    return None


def event_person(progress_row: dict | None) -> str:
    if not progress_row:
        return ""
    return str(progress_row.get("operator") or "")


def event_date(progress_row: dict | None) -> str:
    if not progress_row:
        return ""
    raw_value = str(progress_row.get("event_at") or "").strip()
    if not raw_value:
        return ""
    try:
        return datetime.fromisoformat(raw_value).strftime("%Y-%m-%d")
    except ValueError:
        return raw_value


def event_status(progress_row: dict | None, fallback: str | None = None) -> str:
    raw_value = ""
    if progress_row:
        raw_value = str(progress_row.get("to_status") or "")
    if not raw_value:
        raw_value = str(fallback or "")
    return normalize_weld_log_status(raw_value)


def normalize_weld_log_status(value: str | None) -> str:
    normalized = str(value or "").strip().replace("_", " ").replace("-", " ")
    if not normalized:
        return ""

    uppercase = " ".join(part for part in normalized.upper().split())
    aliases = {
        "DONE": "COMPLETE",
        "COMPLETED": "COMPLETE",
        "IN PROGRESS": "IN PROGRESS",
        "NOT STARTED": "NOT STARTED",
        "NOT CHECKED": "NOT CHECKED",
        "ACCEPTED": "ACCEPT",
        "ACCEPT": "ACCEPT",
        "REJECTED": "REJECT",
        "REJECT": "REJECT",
    }
    return aliases.get(uppercase, uppercase)
