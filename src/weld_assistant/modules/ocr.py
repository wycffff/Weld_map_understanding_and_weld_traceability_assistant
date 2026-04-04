from __future__ import annotations

import os
import re
from pathlib import Path
from statistics import median
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
                "PaddleOCR is not installed. Install it with `python -m pip install paddleocr paddlepaddle`."
            ) from exc

        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        self._ocr = PaddleOCR(
            lang=config.ocr.lang,
            ocr_version="PP-OCRv4",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def extract(self, roi_image: str, roi_meta: dict[str, Any]) -> dict[str, list[Any]]:
        try:
            raw = self._ocr.predict(roi_image)
        except Exception as exc:
            raise OCRDependencyError(f"PaddleOCR runtime failed: {exc}") from exc
        return self._convert_predict_result(raw, roi_meta)

    def _convert_predict_result(self, raw: Any, roi_meta: dict[str, Any]) -> dict[str, list[Any]]:
        tokens: list[OCRToken] = []
        tables: list[OCRTable] = []
        token_like_entries = self._flatten_paddle_entries(raw)
        for entry in token_like_entries:
            points, text, confidence = entry
            if confidence < self.config.ocr.confidence_threshold:
                continue
            bbox = self._points_to_bbox(points)
            normalized, raw_text, corrected = normalize_token_text_safe(text)
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
        if roi_meta["roi_type"] == "roi_bom_table":
            tables.append(build_table_from_tokens(roi_meta["roi_id"], tokens))
        return {"tokens": tokens, "tables": tables}

    @staticmethod
    def _flatten_paddle_entries(raw: Any) -> list[tuple[list[list[float]], str, float]]:
        entries: list[tuple[list[list[float]], str, float]] = []
        for item in raw or []:
            # Try object-style result first.
            if hasattr(item, "res"):
                res = getattr(item, "res")
                dt_polys = res.get("dt_polys", [])
                rec_texts = res.get("rec_texts", [])
                rec_scores = res.get("rec_scores", [])
                for points, text, score in zip(dt_polys, rec_texts, rec_scores):
                    entries.append((points.tolist() if hasattr(points, "tolist") else points, str(text), float(score)))
                continue
            # Rapid-style or legacy list-like result.
            if isinstance(item, list):
                for maybe in item:
                    if isinstance(maybe, list) and len(maybe) >= 3:
                        entries.append((maybe[0], str(maybe[1]), float(maybe[2])))
        return entries

    @staticmethod
    def _points_to_bbox(points: Any) -> list[int]:
        xs = [int(point[0]) for point in points]
        ys = [int(point[1]) for point in points]
        return [min(xs), min(ys), max(xs), max(ys)]


class RapidOCREngine(BaseOCREngine):
    engine_name = "rapidocr"

    def __init__(self, config: AppConfig):
        super().__init__(config)
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
        except ImportError as exc:
            raise OCRDependencyError(
                "RapidOCR is not installed. Install it with `python -m pip install rapidocr_onnxruntime`."
            ) from exc
        self._ocr = RapidOCR()

    def extract(self, roi_image: str, roi_meta: dict[str, Any]) -> dict[str, list[Any]]:
        raw, _ = self._ocr(roi_image)
        tokens: list[OCRToken] = []
        for points, text, confidence in raw or []:
            if confidence < self.config.ocr.confidence_threshold:
                continue
            bbox = self._points_to_bbox(points)
            normalized, raw_text, corrected = normalize_token_text_safe(text)
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

        tables: list[OCRTable] = []
        if roi_meta["roi_type"] == "roi_bom_table":
            tables.append(build_table_from_tokens(roi_meta["roi_id"], tokens))
        return {"tokens": tokens, "tables": tables}

    @staticmethod
    def _points_to_bbox(points: Any) -> list[int]:
        xs = [int(point[0]) for point in points]
        ys = [int(point[1]) for point in points]
        return [min(xs), min(ys), max(xs), max(ys)]


class NullOCREngine(BaseOCREngine):
    engine_name = "null"

    def extract(self, roi_image: str, roi_meta: dict[str, Any]) -> dict[str, list[Any]]:
        Image.open(roi_image)
        return {"tokens": [], "tables": []}


def build_ocr_engine(config: AppConfig) -> BaseOCREngine:
    if config.ocr.engine == "rapidocr":
        return RapidOCREngine(config)
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


def normalize_token_text_safe(text: str) -> tuple[str, str, bool]:
    raw = text.strip()
    normalized = (
        raw.replace("〞", "-")
        .replace("每", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace(" ", "")
    )
    normalized = re.sub(r"(?<=W-)I", "1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<=W-)O", "0", normalized, flags=re.IGNORECASE)
    corrected = normalized != raw
    return normalized, raw, corrected


def build_table_from_tokens(roi_id: str, tokens: list[OCRToken], row_tolerance: int = 8) -> OCRTable:
    if not tokens:
        return OCRTable(roi_id=roi_id, cells=[], html=None, confidence=0.0)

    sorted_tokens = sorted(tokens, key=lambda token: ((token.bbox[1] + token.bbox[3]) / 2, token.bbox[0]))
    adaptive_tolerance = max(row_tolerance, _adaptive_row_tolerance(sorted_tokens))
    rows = _cluster_tokens_by_y(sorted_tokens, adaptive_tolerance)

    def header_score(row: list[OCRToken]) -> tuple[int, int]:
        score = sum(1 for token in row if _looks_like_bom_header(token.text))
        return score, len(row)

    header_candidates = [row for row in rows if len(row) > 1]
    header_row = max(header_candidates or rows, key=header_score)
    header_positions = sorted(
        [((token.bbox[0] + token.bbox[2]) / 2, idx) for idx, token in enumerate(sorted(header_row, key=lambda item: item.bbox[0]))]
    )

    cells: list[OCRTableCell] = []
    row_index = 0
    for row in rows:
        ordered = sorted(row, key=lambda item: item.bbox[0])
        for token in ordered:
            center_x = (token.bbox[0] + token.bbox[2]) / 2
            if header_positions:
                col_index = min(header_positions, key=lambda item: abs(center_x - item[0]))[1]
            else:
                col_index = ordered.index(token)
            cells.append(
                OCRTableCell(
                    row=row_index,
                    col=col_index,
                    text=token.text,
                    confidence=token.confidence,
                )
            )
        row_index += 1

    avg_conf = sum(token.confidence for token in tokens) / len(tokens)
    return OCRTable(roi_id=roi_id, cells=cells, html=None, confidence=avg_conf)


def _looks_like_bom_header(text: str) -> bool:
    upper = re.sub(r"[^A-Z]", "", text.upper())
    return (
        upper.startswith(("TA", "DES", "QT", "GT", "MA", "XA", "IT", "NO"))
        or upper in {"QTY", "GTY", "MAT", "XAT", "TAG", "TAO", "ITEM", "NO"}
    )


def _adaptive_row_tolerance(tokens: list[OCRToken]) -> int:
    heights = [max(1, token.bbox[3] - token.bbox[1]) for token in tokens]
    if not heights:
        return 0
    return min(80, max(40, int(median(heights) * 0.9)))


def _cluster_tokens_by_y(tokens: list[OCRToken], row_tolerance: int) -> list[list[OCRToken]]:
    rows: list[list[OCRToken]] = []
    for token in tokens:
        y_center = (token.bbox[1] + token.bbox[3]) / 2
        if not rows:
            rows.append([token])
            continue
        last_row = rows[-1]
        last_center = sum((item.bbox[1] + item.bbox[3]) / 2 for item in last_row) / len(last_row)
        if abs(y_center - last_center) <= row_tolerance:
            last_row.append(token)
        else:
            rows.append([token])
    return rows
