from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image

from weld_assistant.config import AppConfig
from weld_assistant.contracts import LayoutPlan, OCRResult, OCRTable, OCRTableCell, OCRToken, PreprocessedDocument
from weld_assistant.utils.files import ensure_dir, write_json


class OCRDependencyError(RuntimeError):
    pass


class BaseOCREngine:
    engine_name = "base"

    def __init__(self, config: AppConfig):
        self.config = config
        self.output_dir = ensure_dir(Path(config.pipeline.data_root) / "ocr")

    def extract_layout(self, doc: PreprocessedDocument, layout_plan: LayoutPlan) -> OCRResult:
        tokens: list[OCRToken] = []
        tables: list[OCRTable] = []
        for roi in layout_plan.rois:
            result = self.extract(
                roi.image_path or "",
                {"roi_id": roi.roi_id, "roi_type": roi.type, "weld_hint": roi.weld_hint},
            )
            tokens.extend(result.get("tokens", []))
            tables.extend(result.get("tables", []))

        ocr_result = OCRResult(document_id=doc.document_id, engine=self.engine_name, tokens=tokens, tables=tables)
        write_json(self.output_dir / f"{doc.document_id}.json", ocr_result.model_dump(mode="json"))
        return ocr_result

    def extract(self, roi_image: str, roi_meta: dict[str, Any]) -> dict[str, list[Any]]:
        raise NotImplementedError


class PaddleOCREngine(BaseOCREngine):
    engine_name = "paddleocr"

    def __init__(self, config: AppConfig):
        super().__init__(config)
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as exc:
            raise OCRDependencyError(
                "PaddleOCR is not installed. Install it with `python -m pip install paddleocr`."
            ) from exc
        self._ocr = PaddleOCR(
            use_angle_cls=True,
            lang=config.ocr.lang,
            use_gpu=config.ocr.use_gpu,
            table=config.ocr.table_enabled,
            layout=False,
        )

    def extract(self, roi_image: str, roi_meta: dict[str, Any]) -> dict[str, list[Any]]:
        if roi_meta["roi_type"] == "roi_bom_table" and self.config.ocr.table_enabled:
            return self._extract_table(roi_image, roi_meta)
        return self._extract_tokens(roi_image, roi_meta)

    def _extract_tokens(self, roi_image: str, roi_meta: dict[str, Any]) -> dict[str, list[Any]]:
        raw = self._ocr.ocr(roi_image, cls=True)
        tokens: list[OCRToken] = []
        for line in raw[0] if raw and raw[0] else []:
            bbox_points, (text, confidence) = line
            if confidence < self.config.ocr.confidence_threshold:
                continue
            bbox = self._points_to_bbox(bbox_points)
            normalized, raw_text, corrected = normalize_token_text(text)
            tokens.append(
                OCRToken(
                    text=normalized,
                    raw_text=raw_text if corrected else None,
                    correction_applied=corrected,
                    bbox=bbox,
                    confidence=float(confidence),
                    roi_id=roi_meta["roi_id"],
                )
            )
        return {"tokens": tokens, "tables": []}

    def _extract_table(self, roi_image: str, roi_meta: dict[str, Any]) -> dict[str, list[Any]]:
        raw = self._ocr.ocr(roi_image, cls=True)
        tokens: list[OCRToken] = []
        cells: list[OCRTableCell] = []
        html = None

        if isinstance(raw, list) and raw:
            first = raw[0]
            if isinstance(first, dict):
                html = first.get("html")
                for cell in first.get("cells", []) or []:
                    cells.append(
                        OCRTableCell(
                            row=int(cell.get("row", 0)),
                            col=int(cell.get("col", 0)),
                            text=str(cell.get("text", "")),
                            confidence=float(cell.get("confidence", 0.0)),
                        )
                    )
            elif isinstance(first, list):
                for row_index, line in enumerate(first):
                    if not isinstance(line, list) or len(line) != 2:
                        continue
                    bbox_points, (text, confidence) = line
                    bbox = self._points_to_bbox(bbox_points)
                    tokens.append(
                        OCRToken(text=text, bbox=bbox, confidence=float(confidence), roi_id=roi_meta["roi_id"])
                    )
                    cells.append(OCRTableCell(row=row_index + 1, col=0, text=text, confidence=float(confidence)))

        table = OCRTable(roi_id=roi_meta["roi_id"], cells=cells, html=html, confidence=self._avg_confidence(cells))
        return {"tokens": tokens, "tables": [table]}

    @staticmethod
    def _points_to_bbox(points: Any) -> list[int]:
        xs = [int(point[0]) for point in points]
        ys = [int(point[1]) for point in points]
        return [min(xs), min(ys), max(xs), max(ys)]

    @staticmethod
    def _avg_confidence(cells: list[OCRTableCell]) -> float:
        return sum(cell.confidence for cell in cells) / len(cells) if cells else 0.0


class NullOCREngine(BaseOCREngine):
    engine_name = "null"

    def extract(self, roi_image: str, roi_meta: dict[str, Any]) -> dict[str, list[Any]]:
        Image.open(roi_image)
        return {"tokens": [], "tables": []}


def build_ocr_engine(config: AppConfig) -> BaseOCREngine:
    if config.ocr.engine == "paddleocr":
        return PaddleOCREngine(config)
    if config.ocr.engine == "null":
        return NullOCREngine(config)
    raise ValueError(f"Unsupported OCR engine: {config.ocr.engine}")


def normalize_token_text(text: str) -> tuple[str, str, bool]:
    raw = text.strip()
    normalized = raw.replace("—", "-").replace("–", "-").replace(" ", "")
    normalized = re.sub(r"(?<=W-)I", "1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<=W-)O", "0", normalized, flags=re.IGNORECASE)
    corrected = normalized != raw
    return normalized, raw, corrected
