from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from weld_assistant.config import AppConfig
from weld_assistant.contracts import (
    BOMItem,
    DrawingData,
    LayoutPlan,
    OCRResult,
    ProcessingLog,
    ReviewItem,
    StructuredDrawing,
    VLMResult,
    WeldItem,
    WeldProvenance,
)


class FusionEngine:
    def __init__(self, config: AppConfig):
        self.config = config

    def merge(self, layout: LayoutPlan, ocr: OCRResult, vlm: VLMResult | None = None) -> StructuredDrawing:
        review_items: list[ReviewItem] = []
        drawing = self._extract_drawing(ocr, review_items)
        bom_items = self._extract_bom(ocr, review_items)
        welds = self._extract_welds(ocr, vlm, review_items)

        if not drawing.drawing_number:
            review_items.append(
                ReviewItem(
                    item_type="drawing_number_missing",
                    field="drawing_number",
                    message="drawing_number was not confidently detected; using document_id as fallback.",
                )
            )
            drawing.drawing_number = layout.document_id

        return StructuredDrawing(
            document_id=layout.document_id,
            schema_version=self.config.fusion.schema_version,
            drawing=drawing,
            bom=bom_items,
            welds=welds,
            needs_review_items=review_items,
            processing_log=ProcessingLog(
                pipeline_version=self.config.pipeline.version,
                processed_at=datetime.now().astimezone(),
                layout_confidence=str(layout.layout_log.get("layout_confidence", "unknown")),
                ocr_engine=ocr.engine,
                vlm_model=vlm.model if vlm and vlm.tasks else None,
            ),
        )

    def _extract_drawing(self, ocr: OCRResult, review_items: list[ReviewItem]) -> DrawingData:
        title_tokens = [token for token in ocr.tokens if token.roi_id.startswith("titleblock")]
        note_tokens = [token for token in ocr.tokens if token.roi_id.startswith("note")]
        all_text = [token.text for token in title_tokens + note_tokens]

        drawing_number = first_match(all_text, r"\d+[-A-Z0-9\"]+\d")
        pipe_size = first_match(all_text, r'\d+"')
        material_spec = first_match(all_text, r"ASTM\s+[A-Z0-9 .-]+")

        for token in title_tokens:
            if token.confidence < 0.7:
                review_items.append(
                    ReviewItem(
                        item_type="low_confidence",
                        field="drawing_field",
                        roi_id=token.roi_id,
                        ocr_value=token.text,
                        message=f"Low OCR confidence for titleblock token: {token.text}",
                        evidence={"ocr_confidence": token.confidence, "ocr_bbox": token.bbox},
                    )
                )

        spool_name = drawing_number.split("-", 1)[-1] if drawing_number and "-" in drawing_number else drawing_number
        return DrawingData(
            drawing_number=drawing_number,
            spool_name=spool_name,
            pipe_size=pipe_size,
            material_spec=material_spec,
        )

    def _extract_bom(self, ocr: OCRResult, review_items: list[ReviewItem]) -> list[BOMItem]:
        items: list[BOMItem] = []
        for table in ocr.tables:
            mapped_rows, raw_cols = map_bom_table(table.cells)
            for row_index, row in enumerate(mapped_rows, start=1):
                items.append(
                    BOMItem(
                        line_no=row_index,
                        tag=row.get("tag"),
                        description=row.get("description"),
                        qty=row.get("qty"),
                        uom=row.get("uom"),
                        material=row.get("material"),
                        confidence=float(row.get("confidence", table.confidence)),
                        needs_review=bool(raw_cols),
                    )
                )
            if raw_cols:
                review_items.append(
                    ReviewItem(
                        item_type="bom_column_mismatch",
                        field="bom",
                        roi_id=table.roi_id,
                        message="BOM columns could not be fully mapped to expected semantics.",
                        evidence={"raw_columns": raw_cols},
                    )
                )
        return items

    def _extract_welds(self, ocr: OCRResult, vlm: VLMResult | None, review_items: list[ReviewItem]) -> list[WeldItem]:
        location_map = {
            task.output_json.get("weld_id", "").replace("-", "").replace(" ", "").upper(): task.output_json.get("location_description")
            for task in (vlm.tasks if vlm else [])
            if task.task_type == "weld_location_describe" and task.schema_valid
        }
        welds: dict[str, WeldItem] = {}
        for token in ocr.tokens:
            candidate = normalize_weld_id(token.text)
            if not candidate:
                continue
            if candidate in welds:
                review_items.append(
                    ReviewItem(
                        item_type="duplicate_weld_id",
                        field="weld_id",
                        roi_id=token.roi_id,
                        ocr_value=candidate,
                        message=f"Duplicate weld_id detected: {candidate}",
                        evidence={"ocr_confidence": token.confidence, "ocr_bbox": token.bbox},
                    )
                )
                continue
            needs_review = token.confidence < 0.7
            if needs_review:
                review_items.append(
                    ReviewItem(
                        item_type="low_confidence",
                        field="weld_id",
                        roi_id=token.roi_id,
                        ocr_value=candidate,
                        message=f"Low OCR confidence for weld_id: {candidate}",
                        evidence={"ocr_confidence": token.confidence, "ocr_bbox": token.bbox},
                    )
                )
            welds[candidate] = WeldItem(
                weld_id=candidate,
                location_description=location_map.get(candidate.upper()),
                confidence=token.confidence,
                needs_review=needs_review,
                provenance=WeldProvenance(
                    ocr_token_bbox=token.bbox,
                    roi_id=token.roi_id,
                    ocr_confidence=token.confidence,
                    vlm_used=candidate.upper() in location_map,
                    correction_applied=token.correction_applied,
                ),
            )
        return list(welds.values())


def normalize_weld_id(text: str) -> str | None:
    normalized = text.replace(" ", "").replace("-", "").upper()
    if not normalized.startswith("W"):
        return None
    digits = normalized[1:]
    if not digits.isdigit():
        return None
    return f"W{digits.zfill(2)}"


def first_match(values: Iterable[str], pattern: str) -> str | None:
    regex = re.compile(pattern, re.IGNORECASE)
    for value in values:
        match = regex.search(value)
        if match:
            return match.group(0)
    return None


def map_bom_table(cells) -> tuple[list[dict], dict[int, str]]:
    if not cells:
        return [], {}

    rows: dict[int, dict[int, tuple[str, float]]] = {}
    for cell in cells:
        rows.setdefault(cell.row, {})[cell.col] = (cell.text, cell.confidence)

    header_row_index = min(rows)
    headers = rows.pop(header_row_index)
    mapping: dict[int, str] = {}
    raw_cols: dict[int, str] = {}

    for col, (text, _) in headers.items():
        upper = text.upper()
        if any(keyword in upper for keyword in ("TAG", "ITEM", "NO")):
            mapping[col] = "tag"
        elif "DESC" in upper:
            mapping[col] = "description"
        elif "QTY" in upper or "QUANTITY" in upper:
            mapping[col] = "qty"
        elif "MAT" in upper:
            mapping[col] = "material"
        elif "UOM" in upper or "UNIT" in upper:
            mapping[col] = "uom"
        else:
            raw_cols[col] = text

    result_rows: list[dict] = []
    for _, row in sorted(rows.items()):
        row_payload: dict[str, str | float | None] = {"confidence": 0.0}
        confidences: list[float] = []
        for col, (text, confidence) in row.items():
            confidences.append(confidence)
            semantic = mapping.get(col)
            if semantic:
                row_payload[semantic] = text
            else:
                row_payload[f"raw_col_{col}"] = text
        row_payload["confidence"] = sum(confidences) / len(confidences) if confidences else 0.0
        if any(key in row_payload for key in ("tag", "description", "qty", "material", "uom")):
            result_rows.append(row_payload)
    return result_rows, raw_cols
