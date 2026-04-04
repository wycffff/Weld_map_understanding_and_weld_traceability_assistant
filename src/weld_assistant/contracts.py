from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FileMetadata(BaseModel):
    project_id: str | None = None
    uploader: str | None = None
    capture_method: Literal["exported_image", "scanned", "photo"] = "exported_image"
    original_filename: str | None = None
    duplicate_of: str | None = None


class InputDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    source_type: str = "spool_drawing"
    file_path: str
    file_type: str
    sha256: str
    received_at: datetime
    metadata: FileMetadata


class PreprocessedDocument(BaseModel):
    document_id: str
    source_filename: str | None = None
    versions: dict[str, str]
    preprocess_log: dict[str, Any]


class ROI(BaseModel):
    roi_id: str
    type: str
    bbox: list[int]
    overlap: float = 0.0
    source_image_version: str = "clean"
    weld_hint: str | None = None
    image_path: str | None = None


class LayoutPlan(BaseModel):
    document_id: str
    rois: list[ROI]
    layout_log: dict[str, Any] = Field(default_factory=dict)


class OCRToken(BaseModel):
    text: str
    bbox: list[int]
    confidence: float
    roi_id: str
    raw_text: str | None = None
    correction_applied: bool = False


class OCRTableCell(BaseModel):
    row: int
    col: int
    text: str
    confidence: float = 0.0


class OCRTable(BaseModel):
    roi_id: str
    cells: list[OCRTableCell]
    html: str | None = None
    confidence: float = 0.0


class OCRResult(BaseModel):
    document_id: str
    engine: str
    tokens: list[OCRToken] = Field(default_factory=list)
    tables: list[OCRTable] = Field(default_factory=list)


class VLMTaskResult(BaseModel):
    task_type: str
    roi_id: str
    output_json: dict[str, Any]
    schema_valid: bool = True
    retry_count: int = 0
    latency_ms: int | None = None
    weld_hint_from_ocr: str | None = None


class VLMResult(BaseModel):
    document_id: str
    model: str
    tasks: list[VLMTaskResult] = Field(default_factory=list)


class ReviewItem(BaseModel):
    item_type: str
    field: str
    roi_id: str | None = None
    ocr_value: str | None = None
    vlm_value: str | None = None
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    roi_image_path: str | None = None


class DrawingData(BaseModel):
    drawing_number: str | None = None
    spool_name: str | None = None
    pipe_size: str | None = None
    material_spec: str | None = None
    revision: str | None = None
    project_number: str | None = None


class BOMItem(BaseModel):
    line_no: int
    tag: str | None = None
    description: str | None = None
    qty: str | None = None
    uom: str | None = None
    material: str | None = None
    confidence: float = 0.0
    source: str = "ocr_table"
    needs_review: bool = False


class WeldProvenance(BaseModel):
    ocr_token_bbox: list[int] | None = None
    roi_id: str | None = None
    ocr_confidence: float | None = None
    vlm_used: bool = False
    correction_applied: bool = False


class WeldItem(BaseModel):
    weld_id: str
    location_description: str | None = None
    status: str = "not_started"
    inspection_status: str = "not_checked"
    confidence: float = 0.0
    needs_review: bool = False
    provenance: WeldProvenance = Field(default_factory=WeldProvenance)


class ProcessingLog(BaseModel):
    pipeline_version: str
    processed_at: datetime
    layout_confidence: str = "unknown"
    ocr_engine: str
    vlm_model: str | None = None


class StructuredDrawing(BaseModel):
    document_id: str
    schema_version: str = "1.1"
    drawing: DrawingData
    bom: list[BOMItem] = Field(default_factory=list)
    welds: list[WeldItem] = Field(default_factory=list)
    needs_review_items: list[ReviewItem] = Field(default_factory=list)
    processing_log: ProcessingLog

    def to_jsonable(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def schema_jsonable(cls) -> dict[str, Any]:
        return cls.model_json_schema()


class ReviewQueueItem(BaseModel):
    review_id: str
    document_id: str
    drawing_number: str | None = None
    weld_id: str | None = None
    item_type: str
    payload: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None = None


class WeldProgressEvent(BaseModel):
    event_id: str
    drawing_number: str
    weld_id: str
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    operator: str | None = None
    event_at: datetime
    note: str | None = None


class PhotoEvidence(BaseModel):
    photo_id: str
    drawing_number: str
    weld_id: str
    file_path: str
    file_hash: str
    captured_at: datetime | None = None
    linked_at: datetime
    linked_by: str | None = None
    note: str | None = None


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
