from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from weld_assistant.config import AppConfig
from weld_assistant.contracts import ReviewQueueItem, StructuredDrawing
from weld_assistant.db.schema import SCHEMA_SQL
from weld_assistant.utils.files import ensure_dir


class SQLiteRepository:
    def __init__(self, config: AppConfig):
        self.config = config
        self.db_path = Path(config.database.path)
        ensure_dir(self.db_path.parent)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=MEMORY;")
        connection.execute("PRAGMA synchronous=OFF;")
        connection.execute("PRAGMA foreign_keys=ON;")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)

    def import_structured_drawing(self, drawing: StructuredDrawing, overwrite: bool = False) -> None:
        drawing_number = drawing.drawing.drawing_number or drawing.document_id
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT drawing_number FROM drawing WHERE drawing_number = ?",
                (drawing_number,),
            ).fetchone()
            if existing and not overwrite:
                raise ValueError(f"drawing_number already exists: {drawing_number}")

            if overwrite:
                previous_numbers = [
                    row["drawing_number"]
                    for row in connection.execute(
                        "SELECT drawing_number FROM drawing WHERE drawing_number = ? OR document_id = ?",
                        (drawing_number, drawing.document_id),
                    ).fetchall()
                ]
                for previous_number in previous_numbers:
                    connection.execute("DELETE FROM photo_evidence WHERE drawing_number = ?", (previous_number,))
                    connection.execute("DELETE FROM weld_progress WHERE drawing_number = ?", (previous_number,))
                    connection.execute("DELETE FROM bom_item WHERE drawing_number = ?", (previous_number,))
                    connection.execute("DELETE FROM weld WHERE drawing_number = ?", (previous_number,))
                    connection.execute("DELETE FROM review_queue WHERE drawing_number = ?", (previous_number,))
                    connection.execute("DELETE FROM drawing WHERE drawing_number = ?", (previous_number,))

            connection.execute(
                """
                INSERT INTO drawing (
                  drawing_number, document_id, spool_name, pipe_size, material_spec,
                  revision, project_number, imported_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    drawing_number,
                    drawing.document_id,
                    drawing.drawing.spool_name,
                    drawing.drawing.pipe_size,
                    drawing.drawing.material_spec,
                    drawing.drawing.revision,
                    drawing.drawing.project_number,
                    datetime.now().astimezone().isoformat(),
                    drawing.schema_version,
                ),
            )

            for item in drawing.bom:
                connection.execute(
                    """
                    INSERT INTO bom_item (
                      drawing_number, line_no, tag, description, qty, uom, material, confidence, needs_review
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        drawing_number,
                        item.line_no,
                        item.tag,
                        item.description,
                        item.qty,
                        item.uom,
                        item.material,
                        item.confidence,
                        int(item.needs_review),
                    ),
                )

            for weld in drawing.welds:
                connection.execute(
                    """
                    INSERT INTO weld (
                      drawing_number, weld_id, location_description, status,
                      inspection_status, ocr_confidence, needs_review, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        drawing_number,
                        weld.weld_id,
                        weld.location_description,
                        weld.status,
                        weld.inspection_status,
                        weld.confidence,
                        int(weld.needs_review),
                        datetime.now().astimezone().isoformat(),
                    ),
                )

            for item in drawing.needs_review_items:
                review = ReviewQueueItem(
                    review_id=f"rv_{uuid4().hex[:10]}",
                    document_id=drawing.document_id,
                    drawing_number=drawing_number,
                    weld_id=item.ocr_value if item.field == "weld_id" else None,
                    item_type=item.item_type,
                    payload=item.model_dump(mode="json"),
                    created_at=datetime.now().astimezone(),
                )
                connection.execute(
                    """
                    INSERT INTO review_queue (
                      review_id, document_id, drawing_number, weld_id, item_type, payload_json, created_at, resolved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review.review_id,
                        review.document_id,
                        review.drawing_number,
                        review.weld_id,
                        review.item_type,
                        json.dumps(review.payload, ensure_ascii=False),
                        review.created_at.isoformat(),
                        None,
                    ),
                )

    def get_drawing(self, drawing_number: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM drawing WHERE drawing_number = ?", (drawing_number,)).fetchone()

    def list_drawings(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM drawing ORDER BY imported_at DESC, drawing_number ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return list(rows)

    def search_drawings(self, query: str, limit: int = 10) -> list[sqlite3.Row]:
        normalized_query = normalize_lookup_key(query)
        if not normalized_query:
            return self.list_drawings(limit=limit)

        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM drawing ORDER BY imported_at DESC, drawing_number ASC").fetchall()

        scored_rows: list[tuple[int, sqlite3.Row]] = []
        for row in rows:
            score = self._score_drawing_match(row, query, normalized_query)
            if score > 0:
                scored_rows.append((score, row))

        scored_rows.sort(key=lambda item: (-item[0], item[1]["drawing_number"]))
        return [row for _, row in scored_rows[:limit]]

    def list_welds(self, drawing_number: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM weld WHERE drawing_number = ? ORDER BY weld_id",
                (drawing_number,),
            ).fetchall()
            return list(rows)

    def get_weld(self, drawing_number: str, weld_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM weld WHERE drawing_number = ? AND weld_id = ?",
                (drawing_number, weld_id),
            ).fetchone()

    def list_bom_items(self, drawing_number: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM bom_item WHERE drawing_number = ? ORDER BY line_no",
                (drawing_number,),
            ).fetchall()
            return list(rows)

    def list_weld_progress(self, drawing_number: str, weld_id: str | None = None) -> list[sqlite3.Row]:
        with self.connect() as connection:
            if weld_id:
                rows = connection.execute(
                    """
                    SELECT * FROM weld_progress
                    WHERE drawing_number = ? AND weld_id = ?
                    ORDER BY event_at DESC, event_id DESC
                    """,
                    (drawing_number, weld_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM weld_progress
                    WHERE drawing_number = ?
                    ORDER BY event_at DESC, event_id DESC
                    """,
                    (drawing_number,),
                ).fetchall()
            return list(rows)

    def list_photo_evidence(self, drawing_number: str, weld_id: str | None = None) -> list[sqlite3.Row]:
        with self.connect() as connection:
            if weld_id:
                rows = connection.execute(
                    """
                    SELECT * FROM photo_evidence
                    WHERE drawing_number = ? AND weld_id = ?
                    ORDER BY linked_at DESC, photo_id DESC
                    """,
                    (drawing_number, weld_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM photo_evidence
                    WHERE drawing_number = ?
                    ORDER BY linked_at DESC, photo_id DESC
                    """,
                    (drawing_number,),
                ).fetchall()
            return list(rows)

    def get_review_item(self, review_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM review_queue WHERE review_id = ?",
                (review_id,),
            ).fetchone()

    def list_review_queue(self, drawing_number: str | None = None, unresolved_only: bool = False) -> list[sqlite3.Row]:
        with self.connect() as connection:
            filters: list[str] = []
            values: list[str] = []
            if drawing_number:
                filters.append("drawing_number = ?")
                values.append(drawing_number)
            if unresolved_only:
                filters.append("resolved_at IS NULL")
            where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""
            query = f"SELECT * FROM review_queue{where_clause} ORDER BY created_at DESC"
            rows = connection.execute(query, tuple(values)).fetchall()
            return list(rows)

    def resolve_review_item(self, review_id: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE review_queue
                SET resolved_at = ?
                WHERE review_id = ? AND resolved_at IS NULL
                """,
                (datetime.now().astimezone().isoformat(), review_id),
            )
            if cursor.rowcount == 0:
                review = connection.execute(
                    "SELECT review_id FROM review_queue WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
                if not review:
                    raise ValueError(f"Review item not found: {review_id}")

    def reopen_review_item(self, review_id: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE review_queue
                SET resolved_at = NULL
                WHERE review_id = ?
                """,
                (review_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Review item not found: {review_id}")

    @staticmethod
    def _score_drawing_match(row: sqlite3.Row, raw_query: str, normalized_query: str) -> int:
        score = 0
        raw_query_upper = raw_query.strip().upper()
        candidates = [
            ("drawing_number", row["drawing_number"] or ""),
            ("spool_name", row["spool_name"] or ""),
            ("document_id", row["document_id"] or ""),
        ]

        for field, value in candidates:
            value_upper = value.upper()
            normalized_value = normalize_lookup_key(value)

            if raw_query_upper and value_upper == raw_query_upper:
                score = max(score, 120 if field == "drawing_number" else 100)
            if normalized_value == normalized_query:
                score = max(score, 115 if field == "drawing_number" else 95)
            if raw_query_upper and value_upper.startswith(raw_query_upper):
                score = max(score, 100 if field == "drawing_number" else 85)
            if normalized_value.startswith(normalized_query):
                score = max(score, 95 if field == "drawing_number" else 80)
            if raw_query_upper and raw_query_upper in value_upper:
                score = max(score, 80 if field == "drawing_number" else 70)
            if normalized_query in normalized_value:
                score = max(score, 75 if field == "drawing_number" else 65)

        return score


def normalize_lookup_key(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", value.upper())
