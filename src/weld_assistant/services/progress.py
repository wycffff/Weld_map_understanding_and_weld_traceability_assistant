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

    def register_welds(
        self,
        drawing_number: str,
        weld_ids: list[str],
        location_description: str | None = None,
        operator: str | None = None,
        note: str | None = None,
        status: str = "not_started",
        inspection_status: str = "not_checked",
        needs_review: bool = True,
        skip_existing: bool = True,
    ) -> dict[str, list[str]]:
        normalized_ids = dedupe_preserve_order(
            [normalize_manual_weld_id(weld_id) for weld_id in weld_ids if normalize_manual_weld_id(weld_id)]
        )
        created: list[str] = []
        skipped_existing: list[str] = []
        if not normalized_ids:
            return {"created": created, "skipped_existing": skipped_existing}

        created_at = datetime.now().astimezone()
        with self.repository.connect() as connection:
            drawing = connection.execute(
                "SELECT drawing_number FROM drawing WHERE drawing_number = ?",
                (drawing_number,),
            ).fetchone()
            if not drawing:
                raise ValueError(f"Drawing not found: {drawing_number}")

            existing_ids = {
                row["weld_id"]
                for row in connection.execute(
                    "SELECT weld_id FROM weld WHERE drawing_number = ?",
                    (drawing_number,),
                ).fetchall()
            }

            for weld_id in normalized_ids:
                if weld_id in existing_ids:
                    if skip_existing:
                        skipped_existing.append(weld_id)
                        continue
                    raise ValueError(f"Weld already exists: {drawing_number}/{weld_id}")

                self._insert_weld(
                    connection=connection,
                    drawing_number=drawing_number,
                    weld_id=weld_id,
                    location_description=location_description,
                    status=status,
                    inspection_status=inspection_status,
                    needs_review=needs_review,
                    created_at=created_at,
                )
                self._insert_event(
                    connection,
                    self._build_event(
                        event_id=f"ev_{uuid4().hex[:10]}",
                        drawing_number=drawing_number,
                        weld_id=weld_id,
                        event_type="weld_registered",
                        from_status=None,
                        to_status=status,
                        operator=operator,
                        note=note or "Weld was added manually.",
                    ),
                )
                existing_ids.add(weld_id)
                created.append(weld_id)

        return {"created": created, "skipped_existing": skipped_existing}

    def register_weld(
        self,
        drawing_number: str,
        weld_id: str,
        location_description: str | None = None,
        operator: str | None = None,
        note: str | None = None,
        status: str = "not_started",
        inspection_status: str = "not_checked",
        needs_review: bool = True,
    ) -> WeldProgressEvent:
        normalized_id = normalize_manual_weld_id(weld_id)
        if not normalized_id:
            raise ValueError("Invalid weld_id.")
        created_at = datetime.now().astimezone()
        with self.repository.connect() as connection:
            drawing = connection.execute(
                "SELECT drawing_number FROM drawing WHERE drawing_number = ?",
                (drawing_number,),
            ).fetchone()
            if not drawing:
                raise ValueError(f"Drawing not found: {drawing_number}")

            existing = connection.execute(
                "SELECT weld_id FROM weld WHERE drawing_number = ? AND weld_id = ?",
                (drawing_number, normalized_id),
            ).fetchone()
            if existing:
                raise ValueError(f"Weld already exists: {drawing_number}/{normalized_id}")

            self._insert_weld(
                connection=connection,
                drawing_number=drawing_number,
                weld_id=normalized_id,
                location_description=location_description,
                status=status,
                inspection_status=inspection_status,
                needs_review=needs_review,
                created_at=created_at,
            )
            event = self._build_event(
                event_id=f"ev_{uuid4().hex[:10]}",
                drawing_number=drawing_number,
                weld_id=normalized_id,
                event_type="weld_registered",
                from_status=None,
                to_status=status,
                operator=operator,
                note=note or "Weld was added manually.",
            )
            self._insert_event(connection, event)
            return event

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

    @staticmethod
    def _insert_weld(
        connection: sqlite3.Connection,
        drawing_number: str,
        weld_id: str,
        location_description: str | None,
        status: str,
        inspection_status: str,
        needs_review: bool,
        created_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO weld (
              drawing_number, weld_id, location_description, status,
              inspection_status, ocr_confidence, needs_review, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                drawing_number,
                weld_id,
                location_description,
                status,
                inspection_status,
                None,
                int(needs_review),
                created_at.isoformat(),
            ),
        )


def normalize_manual_weld_id(value: str | None) -> str | None:
    if not value:
        return None
    compact = value.strip().upper().replace(" ", "").replace("-", "")
    if not compact:
        return None
    if compact.startswith("W") and compact[1:].isdigit() and len(compact) <= 5:
        return f"W{compact[1:].zfill(2)}"
    if compact.isdigit() and len(compact) <= 4:
        return str(int(compact))
    return value.strip().upper()


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
