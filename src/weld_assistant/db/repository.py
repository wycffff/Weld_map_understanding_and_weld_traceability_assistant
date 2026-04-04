from __future__ import annotations

import json
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
                connection.execute("DELETE FROM bom_item WHERE drawing_number = ?", (drawing_number,))
                connection.execute("DELETE FROM weld WHERE drawing_number = ?", (drawing_number,))
                connection.execute("DELETE FROM review_queue WHERE drawing_number = ?", (drawing_number,))
                connection.execute("DELETE FROM drawing WHERE drawing_number = ?", (drawing_number,))

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

    def list_welds(self, drawing_number: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM weld WHERE drawing_number = ? ORDER BY weld_id",
                (drawing_number,),
            ).fetchall()
            return list(rows)

    def list_bom_items(self, drawing_number: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM bom_item WHERE drawing_number = ? ORDER BY line_no",
                (drawing_number,),
            ).fetchall()
            return list(rows)

    def list_review_queue(self, drawing_number: str | None = None) -> list[sqlite3.Row]:
        with self.connect() as connection:
            if drawing_number:
                rows = connection.execute(
                    "SELECT * FROM review_queue WHERE drawing_number = ? ORDER BY created_at DESC",
                    (drawing_number,),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM review_queue ORDER BY created_at DESC").fetchall()
            return list(rows)
