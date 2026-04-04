from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS drawing (
  drawing_number TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  spool_name TEXT,
  pipe_size TEXT,
  material_spec TEXT,
  revision TEXT,
  project_number TEXT,
  drawing_type TEXT,
  supported INTEGER NOT NULL DEFAULT 1,
  classification_reason TEXT,
  imported_at TEXT NOT NULL,
  schema_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weld (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  drawing_number TEXT NOT NULL REFERENCES drawing(drawing_number),
  weld_id TEXT NOT NULL,
  location_description TEXT,
  pipe_size TEXT,
  weld_type TEXT,
  wps_number TEXT,
  remarks TEXT,
  status TEXT NOT NULL DEFAULT 'not_started',
  inspection_status TEXT NOT NULL DEFAULT 'not_checked',
  ocr_confidence REAL,
  needs_review INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(drawing_number, weld_id)
);

CREATE TABLE IF NOT EXISTS weld_progress (
  event_id TEXT PRIMARY KEY,
  drawing_number TEXT NOT NULL,
  weld_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  operator TEXT,
  event_at TEXT NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS photo_evidence (
  photo_id TEXT PRIMARY KEY,
  drawing_number TEXT NOT NULL,
  weld_id TEXT NOT NULL,
  file_path TEXT NOT NULL,
  file_hash TEXT NOT NULL,
  captured_at TEXT,
  linked_at TEXT NOT NULL,
  linked_by TEXT,
  note TEXT
);

CREATE TABLE IF NOT EXISTS bom_item (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  drawing_number TEXT NOT NULL REFERENCES drawing(drawing_number),
  line_no INTEGER,
  tag TEXT,
  description TEXT,
  qty TEXT,
  uom TEXT,
  material TEXT,
  confidence REAL,
  needs_review INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS review_queue (
  review_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  drawing_number TEXT,
  weld_id TEXT,
  item_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
"""
