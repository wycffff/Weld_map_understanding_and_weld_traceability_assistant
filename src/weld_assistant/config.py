from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class PipelineSection(BaseModel):
    version: str = "0.1.0"
    data_root: str = "data"


class PreprocessingSection(BaseModel):
    max_width: int = 2400
    versions: list[str] = Field(default_factory=lambda: ["clean", "strong"])
    deskew_max_angle: int = 30


class LayoutSection(BaseModel):
    mode: str = "manual"
    manual_roi_config: str = "config/roi_template_default.json"
    bom_keywords: list[str] = Field(default_factory=list)
    titleblock_keywords: list[str] = Field(default_factory=list)
    weld_id_pattern: str = r"^W[- ]?\d+$"
    weld_roi_padding_px: int = 80
    weld_roi_overlap: float = 0.2


class OcrSection(BaseModel):
    engine: str = "paddleocr"
    lang: str = "en"
    use_gpu: bool = False
    table_enabled: bool = True
    confidence_threshold: float = 0.5
    char_correction: dict[str, Any] = Field(default_factory=dict)


class VlmSection(BaseModel):
    enabled: bool = False
    model: str = "qwen3.5:0.8b"
    temperature: float = 0
    num_ctx: int = 4096
    max_retries: int = 2
    mode: str = "review_only"
    max_tasks_per_document: int = 3
    max_output_tokens: int = 96
    request_timeout_sec: int = 30
    review_request_timeout_sec: int = 180
    task_max_output_tokens: dict[str, int] = Field(default_factory=dict)


class FusionSection(BaseModel):
    ocr_primary_confidence_threshold: float = 0.8
    conflict_strategy: str = "needs_review"
    schema_version: str = "1.1"


class DatabaseSection(BaseModel):
    type: str = "sqlite"
    path: str = "data/db/weld_traceability.db"


class ExportSection(BaseModel):
    output_dir: str = "data/final"
    csv_fields: list[str] = Field(default_factory=list)


class UiSection(BaseModel):
    max_upload_mb: int = 200
    show_roi_preview: bool = True


class AppConfig(BaseModel):
    pipeline: PipelineSection = Field(default_factory=PipelineSection)
    preprocessing: PreprocessingSection = Field(default_factory=PreprocessingSection)
    layout: LayoutSection = Field(default_factory=LayoutSection)
    ocr: OcrSection = Field(default_factory=OcrSection)
    vlm: VlmSection = Field(default_factory=VlmSection)
    fusion: FusionSection = Field(default_factory=FusionSection)
    database: DatabaseSection = Field(default_factory=DatabaseSection)
    export: ExportSection = Field(default_factory=ExportSection)
    ui: UiSection = Field(default_factory=UiSection)


def load_config(config_path: str | Path = "config/config.yaml") -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        return AppConfig()

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return AppConfig.model_validate(data)
