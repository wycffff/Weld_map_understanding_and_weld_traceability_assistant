from __future__ import annotations

import json
from pathlib import Path

from weld_assistant.config import AppConfig
from weld_assistant.contracts import StructuredDrawing
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.modules.fusion import FusionEngine
from weld_assistant.modules.ingestion import DocumentLoader
from weld_assistant.modules.layout import RegionPlanner
from weld_assistant.modules.ocr import BaseOCREngine, NullOCREngine, OCRDependencyError, RapidOCREngine, build_ocr_engine
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
            if self.config.ocr.engine != "rapidocr":
                try:
                    return RapidOCREngine(self.config)
                except OCRDependencyError:
                    pass
            return NullOCREngine(self.config)

    def process_file(
        self,
        input_path: str | Path,
        metadata: dict | None = None,
        persist: bool = False,
        overwrite: bool = False,
        use_vlm: bool | None = None,
    ) -> StructuredDrawing:
        path = Path(input_path)
        input_doc = self.loader.load(
            path.read_bytes(),
            {"original_filename": path.name, **(metadata or {})},
        )
        preprocessed = self.preprocessor.process(input_doc)

        ocr_engine = self.build_ocr_engine()
        preview_layout = self.region_planner.build_preview_plan(preprocessed)
        ocr_result = ocr_engine.extract_layout(preprocessed, preview_layout)
        classification = self.region_planner.classify(ocr_result)

        layout_plan = self.region_planner.plan(preprocessed, ocr_preview=ocr_result, classification=classification)
        if layout_plan.rois:
            ocr_result = ocr_engine.extract_layout(preprocessed, layout_plan)

        vlm_enabled = use_vlm if layout_plan.supported else False
        vlm_result = self.vlm.analyze_layout(layout_plan, ocr_result=ocr_result, enabled=vlm_enabled)
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
