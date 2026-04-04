from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from weld_assistant.contracts import PhotoEvidence, WeldProgressEvent
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.utils.files import ensure_dir, sha256_file


class ProgressService:
    def __init__(self, repository: SQLiteRepository):
        self.repository = repository

    def update_status(self, drawing_number: str, weld_id: str, to_status: str, operator: str | None = None, note: str | None = None) -> WeldProgressEvent:
        with self.repository.connect() as connection:
            weld = self._require_weld(connection, drawing_number, weld_id)

            from_status = weld["status"]
            connection.execute(
                "UPDATE weld SET status = ? WHERE drawing_number = ? AND weld_id = ?",
                (to_status, drawing_number, weld_id),
            )
            event = self._build_event(
                event_id=f"ev_{uuid4().hex[:10]}",
                drawing_number=drawing_number,
                weld_id=weld_id,
                event_type="status_update",
                from_status=from_status,
                to_status=to_status,
                operator=operator,
                note=note,
            )
            self._insert_event(connection, event)
            return event

    def update_inspection(self, drawing_number: str, weld_id: str, inspection_status: str, operator: str | None = None, note: str | None = None) -> WeldProgressEvent:
        with self.repository.connect() as connection:
            weld = self._require_weld(connection, drawing_number, weld_id)

            from_status = weld["inspection_status"]
            connection.execute(
                "UPDATE weld SET inspection_status = ? WHERE drawing_number = ? AND weld_id = ?",
                (inspection_status, drawing_number, weld_id),
            )
            event = self._build_event(
                event_id=f"ev_{uuid4().hex[:10]}",
                drawing_number=drawing_number,
                weld_id=weld_id,
                event_type="inspection_update",
                from_status=from_status,
                to_status=inspection_status,
                operator=operator,
                note=note,
            )
            self._insert_event(connection, event)
            return event

    def link_photo(
        self,
        drawing_number: str,
        weld_id: str,
        file_bytes: bytes,
        filename: str,
        linked_by: str | None = None,
        note: str | None = None,
    ) -> PhotoEvidence:
        photos_dir = ensure_dir(Path(self.repository.config.pipeline.data_root) / "photos")
        suffix = Path(filename).suffix or ".jpg"
        photo_id = f"ph_{uuid4().hex[:10]}"
        photo_path = photos_dir / f"{photo_id}{suffix}"
        photo_path.write_bytes(file_bytes)
        evidence = PhotoEvidence(
            photo_id=photo_id,
            drawing_number=drawing_number,
            weld_id=weld_id,
            file_path=str(photo_path),
            file_hash=sha256_file(photo_path),
            linked_at=datetime.now().astimezone(),
            linked_by=linked_by,
            note=note,
        )
        with self.repository.connect() as connection:
            self._require_weld(connection, drawing_number, weld_id)
            connection.execute(
                """
                INSERT INTO photo_evidence (
                  photo_id, drawing_number, weld_id, file_path, file_hash, captured_at, linked_at, linked_by, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.photo_id,
                    evidence.drawing_number,
                    evidence.weld_id,
                    evidence.file_path,
                    evidence.file_hash,
                    None,
                    evidence.linked_at.isoformat(),
                    evidence.linked_by,
                    evidence.note,
                ),
            )
            self._insert_event(
                connection,
                self._build_event(
                    event_id=f"ev_{uuid4().hex[:10]}",
                    drawing_number=drawing_number,
                    weld_id=weld_id,
                    event_type="photo_linked",
                    from_status=None,
                    to_status=photo_id,
                    operator=linked_by,
                    note=note or f"Linked photo {photo_id}",
                ),
            )
        return evidence

    @staticmethod
    def _require_weld(connection: sqlite3.Connection, drawing_number: str, weld_id: str) -> sqlite3.Row:
        weld = connection.execute(
            "SELECT status, inspection_status FROM weld WHERE drawing_number = ? AND weld_id = ?",
            (drawing_number, weld_id),
        ).fetchone()
        if not weld:
            raise ValueError(f"Weld not found: {drawing_number}/{weld_id}")
        return weld

    @staticmethod
    def _build_event(
        event_id: str,
        drawing_number: str,
        weld_id: str,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        operator: str | None,
        note: str | None,
    ) -> WeldProgressEvent:
        return WeldProgressEvent(
            event_id=event_id,
            drawing_number=drawing_number,
            weld_id=weld_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            operator=operator,
            event_at=datetime.now().astimezone(),
            note=note,
        )

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, event: WeldProgressEvent) -> None:
        connection.execute(
            """
            INSERT INTO weld_progress (
              event_id, drawing_number, weld_id, event_type, from_status, to_status, operator, event_at, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.drawing_number,
                event.weld_id,
                event.event_type,
                event.from_status,
                event.to_status,
                event.operator,
                event.event_at.isoformat(),
                event.note,
            ),
        )
