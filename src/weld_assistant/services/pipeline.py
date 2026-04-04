from __future__ import annotations

import json
from pathlib import Path

from weld_assistant.config import AppConfig
from weld_assistant.contracts import StructuredDrawing
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.modules.fusion import FusionEngine
from weld_assistant.modules.ingestion import DocumentLoader
from weld_assistant.modules.layout import RegionPlanner
from weld_assistant.modules.ocr import BaseOCREngine, NullOCREngine, OCRDependencyError, build_ocr_engine
from weld_assistant.modules.preprocessing import Preprocessor
from weld_assistant.modules.vlm import VLMEngine
from weld_assistant.services.exporter import FileExporter
from weld_assistant.utils.files import ensure_dir, write_json


class PipelineService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.loader = DocumentLoader(config)
        self.preprocessor = Preprocessor(config)
        self.region_planner = RegionPlanner(config)
        self.fusion = FusionEngine(config)
        self.vlm = VLMEngine(config)
        self.exporter = FileExporter(config)
        self.repository = SQLiteRepository(config)

    def build_ocr_engine(self) -> BaseOCREngine:
        try:
            return build_ocr_engine(self.config)
        except OCRDependencyError:
            return NullOCREngine(self.config)

    def process_file(
        self,
        input_path: str | Path,
        metadata: dict | None = None,
        persist: bool = False,
        overwrite: bool = False,
    ) -> StructuredDrawing:
        path = Path(input_path)
        input_doc = self.loader.load(
            path.read_bytes(),
            {"original_filename": path.name, **(metadata or {})},
        )
        preprocessed = self.preprocessor.process(input_doc)

        ocr_engine = self.build_ocr_engine()
        preview_layout = self.region_planner.plan(preprocessed, ocr_preview=None)
        ocr_result = ocr_engine.extract_layout(preprocessed, preview_layout)

        layout_plan = (
            self.region_planner.plan(preprocessed, ocr_preview=ocr_result)
            if self.config.layout.mode == "auto"
            else preview_layout
        )
        ocr_result = ocr_engine.extract_layout(preprocessed, layout_plan)

        vlm_result = self.vlm.analyze_layout(layout_plan)
        structured = self.fusion.merge(layout_plan, ocr_result, vlm_result)

        final_dir = ensure_dir(Path(self.config.pipeline.data_root) / "final")
        final_path = final_dir / f"{structured.document_id}.structured.json"
        write_json(final_path, structured.to_jsonable())

        if persist:
            self.repository.init_db()
            self.repository.import_structured_drawing(structured, overwrite=overwrite)
            self.exporter.export_structured_drawing(structured)

        return structured

    def write_schema(self, output_path: str | Path) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(StructuredDrawing.schema_jsonable(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def validate_runtime(self) -> list[str]:
        warnings: list[str] = []
        try:
            self.build_ocr_engine()
        except OCRDependencyError as exc:
            warnings.append(str(exc))
        except Exception as exc:  # pragma: no cover
            warnings.append(f"OCR engine failed to initialize: {exc}")
        return warnings
