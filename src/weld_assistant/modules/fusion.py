from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
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
        drawing = self._extract_drawing(ocr, vlm, review_items)
        bom_items = self._extract_bom(ocr, drawing, review_items)
        welds = self._extract_welds(layout, ocr, vlm, review_items)

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

    def _extract_drawing(self, ocr: OCRResult, vlm: VLMResult | None, review_items: list[ReviewItem]) -> DrawingData:
        title_tokens = [token for token in ocr.tokens if token.roi_id.startswith("titleblock")]
        note_tokens = [token for token in ocr.tokens if token.roi_id.startswith("note")]
        all_text = [token.text for token in title_tokens + note_tokens]

        drawing_number = extract_drawing_number(all_text)
        pipe_size = normalize_pipe_size(all_text)
        material_spec = normalize_material_spec(first_match(all_text, r"ASTM[A-Z0-9 .-]+") or first_match(all_text, r"ASTM\s+[A-Z0-9 .-]+"))
        vlm_title = first_vlm_task(vlm, "drawing_title_extract")
        vlm_payload = vlm_title.output_json if vlm_title and vlm_title.schema_valid else {}
        vlm_drawing_number = normalize_drawing_number(stringify_vlm_value(vlm_payload.get("drawing_number")))
        vlm_pipe_size = stringify_vlm_value(vlm_payload.get("pipe_size"))
        vlm_material_spec = normalize_material_spec(stringify_vlm_value(vlm_payload.get("material_spec")))
        vlm_project_number = stringify_vlm_value(vlm_payload.get("project_number"))
        vlm_spool_name = stringify_vlm_value(vlm_payload.get("spool_name"))

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

        if drawing_number and vlm_drawing_number and drawing_number != vlm_drawing_number:
            review_items.append(
                ReviewItem(
                    item_type="ocr_vlm_conflict",
                    field="drawing_number",
                    roi_id=vlm_title.roi_id if vlm_title else None,
                    ocr_value=drawing_number,
                    vlm_value=vlm_drawing_number,
                    message="OCR and VLM disagree on drawing_number; OCR remains primary.",
                    evidence={"ocr_tokens": all_text[:20], "vlm_payload": vlm_payload},
                )
            )

        if not drawing_number and vlm_drawing_number:
            review_items.append(
                ReviewItem(
                    item_type="drawing_number_from_vlm",
                    field="drawing_number",
                    roi_id=vlm_title.roi_id if vlm_title else None,
                    vlm_value=vlm_drawing_number,
                    message="drawing_number was filled from VLM because OCR did not produce a confident value.",
                    evidence={"vlm_payload": vlm_payload},
                )
            )
            drawing_number = vlm_drawing_number

        if not pipe_size and vlm_pipe_size:
            pipe_size = vlm_pipe_size
        if not material_spec and vlm_material_spec:
            material_spec = vlm_material_spec

        spool_name = drawing_number.split("-", 1)[-1] if drawing_number and "-" in drawing_number else drawing_number
        if not spool_name and vlm_spool_name:
            spool_name = vlm_spool_name
        return DrawingData(
            drawing_number=drawing_number,
            spool_name=spool_name,
            pipe_size=pipe_size,
            material_spec=material_spec,
            project_number=vlm_project_number,
        )

    def _extract_bom(self, ocr: OCRResult, drawing: DrawingData, review_items: list[ReviewItem]) -> list[BOMItem]:
        items: list[BOMItem] = []
        for table in ocr.tables:
            mapped_rows, raw_cols = map_bom_table(table.cells)
            table_items: list[BOMItem] = []
            for row_index, row in enumerate(mapped_rows, start=1):
                bom_item, bom_issues = build_bom_item(
                    line_no=row_index,
                    row=row,
                    drawing=drawing,
                    fallback_confidence=float(row.get("confidence", table.confidence)),
                )
                if table_items and is_redundant_bom_fragment(table_items[-1], bom_item):
                    continue
                table_items.append(bom_item)
                items.append(bom_item)
                if bom_issues:
                    review_items.append(
                        ReviewItem(
                            item_type="bom_item_needs_review",
                            field="bom",
                            roi_id=table.roi_id,
                            ocr_value=bom_item.tag or bom_item.description,
                            message=f"BOM line {row_index} requires review: {', '.join(bom_issues)}",
                            evidence={"line_no": row_index, "row": row, "issues": bom_issues},
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

    def _extract_welds(self, layout: LayoutPlan, ocr: OCRResult, vlm: VLMResult | None, review_items: list[ReviewItem]) -> list[WeldItem]:
        location_map = {
            task.output_json.get("weld_id", "").replace("-", "").replace(" ", "").upper(): task.output_json.get("location_description")
            for task in (vlm.tasks if vlm else [])
            if task.task_type == "weld_location_describe" and task.schema_valid
        }
        vlm_weld_ids = extract_vlm_weld_ids(vlm)
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

        profile = str(layout.layout_log.get("document_profile", ""))
        if profile == "welding_map_sheet":
            inferred_ids, evidence = infer_numeric_weld_ids_from_weld_list(layout.rois)
            if inferred_ids:
                review_items.append(
                    ReviewItem(
                        item_type="numeric_weld_ids_inferred",
                        field="weld_id",
                        roi_id="weld_list",
                        message="Numeric weld identifiers were inferred from the welding-list grid and require review.",
                        evidence={**evidence, "candidate_weld_ids": inferred_ids},
                    )
                )
            for inferred_id in inferred_ids:
                if inferred_id in welds:
                    continue
                welds[inferred_id] = WeldItem(
                    weld_id=inferred_id,
                    location_description=location_map.get(inferred_id.upper()),
                    confidence=0.0,
                    needs_review=True,
                    provenance=WeldProvenance(
                        ocr_token_bbox=None,
                        roi_id="weld_list",
                        ocr_confidence=None,
                        vlm_used=inferred_id.upper() in location_map,
                        correction_applied=False,
                    ),
                )

        added_by_vlm: list[str] = []
        for vlm_id in vlm_weld_ids:
            if vlm_id in welds:
                continue
            welds[vlm_id] = WeldItem(
                weld_id=vlm_id,
                location_description=location_map.get(vlm_id.upper()),
                confidence=0.0,
                needs_review=True,
                provenance=WeldProvenance(
                    ocr_token_bbox=None,
                    roi_id="weld_list_vlm",
                    ocr_confidence=None,
                    vlm_used=True,
                    correction_applied=False,
                ),
            )
            added_by_vlm.append(vlm_id)

        if added_by_vlm:
            review_items.append(
                ReviewItem(
                    item_type="weld_ids_from_vlm",
                    field="weld_id",
                    roi_id="weld_list",
                    vlm_value=", ".join(added_by_vlm),
                    message="Additional weld identifiers were supplied by VLM and require review before acceptance.",
                    evidence={"vlm_weld_ids": vlm_weld_ids, "candidate_weld_ids": added_by_vlm},
                )
            )
        return list(welds.values())


def normalize_weld_id(text: str) -> str | None:
    normalized = text.replace(" ", "").replace("-", "").upper()
    if not normalized.startswith("W"):
        return None
    digits = normalized[1:]
    if not digits.isdigit() or len(digits) > 4:
        return None
    return f"W{digits.zfill(2)}"


def first_match(values: Iterable[str], pattern: str) -> str | None:
    regex = re.compile(pattern, re.IGNORECASE)
    for value in values:
        match = regex.search(value)
        if match:
            return match.group(0)
    return None


def first_vlm_task(vlm: VLMResult | None, task_type: str):
    if not vlm:
        return None
    return next((task for task in vlm.tasks if task.task_type == task_type), None)


def stringify_vlm_value(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extract_vlm_weld_ids(vlm: VLMResult | None) -> list[str]:
    if not vlm:
        return []

    candidates: list[str] = []
    for task in vlm.tasks:
        if task.task_type != "weld_list_extract" or not task.schema_valid:
            continue
        for raw_value in task.output_json.get("weld_ids", []):
            normalized = normalize_weld_id_or_numeric(raw_value)
            if normalized:
                candidates.append(normalized)
    return dedupe_preserve_order(candidates)


def normalize_weld_id_or_numeric(value) -> str | None:
    text = stringify_vlm_value(value)
    if not text:
        return None
    normalized_weld = normalize_weld_id(text)
    if normalized_weld:
        return normalized_weld
    compact = text.replace(" ", "").replace("-", "")
    if compact.isdigit() and len(compact) <= 4:
        return str(int(compact))
    return None


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def map_bom_table(cells) -> tuple[list[dict], dict[int, str]]:
    if not cells:
        return [], {}

    rows: dict[int, dict[int, list[tuple[str, float]]]] = {}
    for cell in cells:
        rows.setdefault(cell.row, {}).setdefault(cell.col, []).append((cell.text, cell.confidence))

    header_row_index = choose_bom_header_row(rows)
    headers = rows.pop(header_row_index)
    mapping: dict[int, str] = {}
    raw_cols: dict[int, str] = {}

    for col, values in headers.items():
        text = " ".join(part for part, _ in values)
        semantic = classify_bom_header(text)
        if semantic:
            mapping[col] = semantic
        else:
            raw_cols[col] = text

    result_rows: list[dict] = []
    for row_number, row in sorted(rows.items()):
        if row_number < header_row_index:
            continue
        row_payload: dict[str, str | float | None] = {"confidence": 0.0}
        confidences: list[float] = []
        for col, values in row.items():
            text = " ".join(part for part, _ in values)
            confidence = sum(score for _, score in values) / len(values)
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


def normalize_drawing_number(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.upper().replace('"', "")
    normalized = re.sub(r"(?<=\d)C(?=[A-Z])", "-", normalized)
    normalized = re.sub(r"(?<=\d)(?=[A-Z])", "-", normalized, count=1)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized


def extract_drawing_number(values: Iterable[str]) -> str | None:
    patterns = (
        r"\b\d+[A-Z0-9\"]+-[A-Z0-9]+(?:-[A-Z0-9]+)?\b",
        r"\b[A-Z0-9]+(?:-[A-Z0-9]+){2,}(?:\([A-Z0-9-]+\))?\b",
        r"\b[A-Z]-\d{2,}\b",
        r"\b\d+-[A-Z0-9]+-\d+\b",
    )
    candidates: list[str] = []
    for value in values:
        for pattern in patterns:
            candidates.extend(re.findall(pattern, value.upper()))

    filtered = [candidate for candidate in candidates if not is_bad_drawing_candidate(candidate)]
    if not filtered:
        return None
    return normalize_drawing_number(max(filtered, key=len))


def is_bad_drawing_candidate(value: str) -> bool:
    compact = re.sub(r"[^A-Z0-9]", "", value.upper())
    if compact.isdigit():
        return True
    if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{2,4}", value):
        return True
    if compact in {
        "ISOMETRICDRAWING",
        "WELDINGMAPDRAWING",
        "PROJECTNO",
        "PROJECTNAME",
        "CLIENTTITLE",
        "CONTRACTORTITLE",
    }:
        return True
    return False


def normalize_pipe_size(values: list[str]) -> str | None:
    for value in values:
        upper = value.upper()
        if "SCH" in upper:
            match = re.search(r"(\d+)", upper)
            if match:
                return f'{match.group(1)}"'
    for value in values:
        match = re.search(r'(\d+)"', value)
        if match:
            return f'{match.group(1)}"'
    return None


def normalize_material_spec(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.upper()
    normalized = normalized.replace("ASTMA", "ASTM A")
    normalized = normalized.replace("AI", "A1")
    normalized = normalized.replace("AI06", "A106")
    normalized = normalized.replace("A106GR", "A106 GR")
    normalized = normalized.replace("GRB", "GR B")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def classify_bom_header(text: str) -> str | None:
    upper = re.sub(r"[^A-Z]", "", text.upper())
    if upper in {"TAG", "TAO", "TAC", "TA6", "ITEM", "NO"} or upper.startswith("TA"):
        return "tag"
    if upper.startswith(("ITEMCO", "PARTNUM", "PARTNO", "ITEMNO")) or upper in {"PARTNUMBER", "TEMCOCC", "ITEMCOCE"}:
        return "tag"
    if "DESC" in upper or upper.startswith("DES"):
        return "description"
    if upper in {"QTY", "GTY", "OTY", "QIY"} or upper.endswith("TY"):
        return "qty"
    if upper in {"MAT", "XAT", "HAT"} or upper.startswith(("MAT", "XAT", "HAT")):
        return "material"
    if upper in {"UOM", "UNIT"} or upper.startswith("UO"):
        return "uom"
    return None


def choose_bom_header_row(rows: dict[int, dict[int, list[tuple[str, float]]]]) -> int:
    def score(row: dict[int, list[tuple[str, float]]]) -> tuple[int, int]:
        values = [" ".join(text for text, _ in entries) for entries in row.values()]
        header_hits = sum(1 for text in values if classify_bom_header(text))
        return header_hits, len(values)

    return max(rows.items(), key=lambda item: score(item[1]))[0]


def build_bom_item(
    line_no: int,
    row: dict[str, str | float | None],
    drawing: DrawingData,
    fallback_confidence: float,
) -> tuple[BOMItem, list[str]]:
    raw_columns = extract_raw_columns(row)
    raw_tag = stringify_cell(row.get("tag"))
    raw_description = stringify_cell(row.get("description"))
    raw_qty = stringify_cell(row.get("qty"))
    raw_uom = stringify_cell(row.get("uom"))
    raw_material = stringify_cell(row.get("material"))

    tag_seed, description_from_tag = split_bom_tag_and_description(raw_tag)
    description_seed = raw_description or description_from_tag or infer_description_from_raw_columns(raw_columns)
    qty_seed = raw_qty or infer_qty_from_raw_columns(raw_columns)
    material_seed = raw_material or infer_material_from_raw_columns(raw_columns)

    description, description_inferred = normalize_bom_description(description_seed, drawing.pipe_size)
    tag, tag_inferred = normalize_bom_tag(tag_seed, description)
    qty, uom, qty_inferred = normalize_bom_quantity(qty_seed, raw_uom, description)
    material, material_inferred = normalize_bom_material(material_seed, description, drawing.material_spec)

    issues: list[str] = []
    if any((description_inferred, tag_inferred, qty_inferred, material_inferred)):
        issues.append("heuristic_normalization")
    if not tag:
        issues.append("missing_tag")
    if not description:
        issues.append("missing_description")
    if not qty:
        issues.append("missing_qty")
    if not material:
        issues.append("missing_material")

    return (
        BOMItem(
            line_no=line_no,
            tag=tag,
            description=description,
            qty=qty,
            uom=uom,
            material=material,
            confidence=float(row.get("confidence", fallback_confidence)),
            source="ocr_table+heuristic" if issues else "ocr_table",
            needs_review=bool(issues),
        ),
        issues,
    )


def stringify_cell(value: str | float | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extract_raw_columns(row: dict[str, str | float | None]) -> list[tuple[int, str]]:
    raw_columns: list[tuple[int, str]] = []
    for key, value in row.items():
        if not key.startswith("raw_col_"):
            continue
        text = stringify_cell(value)
        if not text:
            continue
        try:
            index = int(key.rsplit("_", 1)[-1])
        except ValueError:
            continue
        raw_columns.append((index, text))
    return sorted(raw_columns)


def split_bom_tag_and_description(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    parts = [part for part in re.split(r"\s+", value.strip()) if part]
    if len(parts) <= 1:
        return value, None

    first = parts[0]
    clean_first = re.sub(r"[^A-Z0-9-]", "", first.upper())
    if not looks_like_part_identifier(clean_first):
        return value, None
    return clean_first, " ".join(parts[1:]) or None


def looks_like_part_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)+", value))


def infer_description_from_raw_columns(raw_columns: list[tuple[int, str]]) -> str | None:
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for index, text in raw_columns:
        compact = re.sub(r"[^A-Z0-9]", "", text.upper())
        alpha_count = sum(char.isalpha() for char in compact)
        if alpha_count < 4:
            continue
        if "ASTM" in compact:
            continue
        score = (alpha_count, len(compact), -index)
        candidates.append((score, text))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def infer_qty_from_raw_columns(raw_columns: list[tuple[int, str]]) -> str | None:
    numeric_candidates: list[tuple[int, str]] = []
    for index, text in raw_columns:
        match = re.fullmatch(r"(\d{1,4})", text.strip())
        if not match:
            continue
        numeric_candidates.append((index, match.group(1)))

    if not numeric_candidates:
        return None

    preferred = [candidate for candidate in numeric_candidates if candidate[0] > 0]
    if preferred:
        return min(preferred, key=lambda item: item[0])[1]
    return None


def infer_material_from_raw_columns(raw_columns: list[tuple[int, str]]) -> str | None:
    for _, text in raw_columns:
        compact = re.sub(r"[^A-Z0-9]", "", text.upper())
        if "ASTM" in compact or re.search(r"A\d{3}", compact):
            return text
    return None


def is_redundant_bom_fragment(previous: BOMItem, current: BOMItem) -> bool:
    if previous.tag and current.tag and previous.tag == current.tag:
        if previous.description == current.description and previous.material == current.material:
            return True

    if not current.tag and previous.tag and current.description and current.description == previous.description:
        if not current.qty and (not current.material or current.material == previous.material):
            return True

    if previous.description and current.description and previous.description == current.description:
        if previous.material == current.material and previous.qty == current.qty and previous.tag == current.tag:
            return True

    return False


def normalize_bom_description(value: str | None, pipe_size: str | None) -> tuple[str | None, bool]:
    if not value:
        return None, False
    compact = re.sub(r"[^A-Z0-9\"]", "", value.upper())
    normalized_size = pipe_size or '4"'

    if "INFORMATIONTAGPLATE" in compact:
        return "Information Tag Plate", True
    if "NAMEPLATE" in compact:
        return "Name Plate", True
    if any(token in compact for token in ("PIPE", "POE", "PPE")) or "SCH" in compact or "COHOS" in compact:
        return f'Pipe {normalized_size} SCH40', True
    if any(token in compact for token in ("ELBOW", "EBOW", "EOOW")) or "90" in compact:
        return f'Elbow 90 {normalized_size}', True
    if any(token in compact for token in ("FLANGE", "FANGE", "FANOE")) or "RF1SO" in compact or "RFSSO" in compact:
        return f'Flange {normalized_size} RF 150#', True
    if any(token in compact for token in ("GATE", "CETE", "VALVE", "VAVE")):
        return f'Gate Valve {normalized_size}', True

    pretty = re.sub(r"\s+", " ", value).strip()
    return pretty, pretty.upper() != compact


def normalize_bom_tag(value: str | None, description: str | None) -> tuple[str | None, bool]:
    if value:
        clean = re.sub(r"[^A-Z0-9-]", "", value.upper())
        clean = clean.replace("-O", "-0").replace("O-", "0-")
        if clean in {"-0", "V-0"} and description and "GATE VALVE" in description.upper():
            return "V-0-4", True
        if clean:
            return clean, clean != value.upper()

    if not description:
        return None, False
    upper = description.upper()
    if upper.startswith("ELBOW 90"):
        return "E-90-4", True
    if upper.startswith("FLANGE"):
        return "F-RF150", True
    if upper.startswith("GATE VALVE"):
        return "V-0-4", True
    return None, False


def normalize_bom_quantity(value: str | None, uom: str | None, description: str | None) -> tuple[str | None, str | None, bool]:
    raw = " ".join(part for part in (value, uom) if part)
    if raw:
        match = re.search(r"(\d+)\s*([A-Z]+)?", raw.upper())
        if match:
            qty = match.group(1)
            unit = match.group(2) or ""
            if "M" in unit:
                return qty, "METER", True
            return qty, None, False

    if not description:
        return None, None, False
    upper = description.upper()
    if upper.startswith("ELBOW 90"):
        return "1", None, True
    if upper.startswith("FLANGE"):
        return "2", None, True
    if upper.startswith("GATE VALVE"):
        return "1", None, True
    return None, None, False


def normalize_bom_material(
    value: str | None,
    description: str | None,
    drawing_material: str | None,
) -> tuple[str | None, bool]:
    upper = re.sub(r"\s+", "", (value or "").upper())
    description_upper = (description or "").upper()

    if "A216" in upper or "A27M" in upper:
        return "ASTM A216", upper != "ASTMA216"
    if "A105" in upper or "ASTXAOS" in upper or "ASTXA105" in upper:
        return "ASTM A105", upper != "ASTMA105"
    if "A234" in upper:
        return "ASTM A234", upper != "ASTMA234"
    if "A106" in upper:
        return normalize_material_spec(value), normalize_material_spec(value) != value

    if description_upper.startswith("PIPE") and drawing_material:
        return drawing_material, True
    if description_upper.startswith("ELBOW 90"):
        return "ASTM A234", True
    if description_upper.startswith("FLANGE"):
        return "ASTM A105", True
    if description_upper.startswith("GATE VALVE"):
        return "ASTM A216", True
    if value:
        return normalize_material_spec(value), normalize_material_spec(value) != value
    return None, False


def infer_numeric_weld_ids_from_weld_list(rois) -> tuple[list[str], dict[str, int | str]]:
    weld_list_roi = next((roi for roi in rois if roi.roi_id == "weld_list" and roi.image_path), None)
    if not weld_list_roi or not weld_list_roi.image_path:
        return [], {}

    row_count = estimate_weld_list_row_count(Path(weld_list_roi.image_path))
    if row_count <= 0:
        return [], {}

    inferred_ids = [str(index) for index in range(1, row_count + 1)]
    return (
        inferred_ids,
        {
            "strategy": "weld_list_grid_inference",
            "row_count": row_count,
            "roi_image_path": weld_list_roi.image_path,
        },
    )


def estimate_weld_list_row_count(image_path: Path) -> int:
    try:
        import cv2  # type: ignore
        import numpy as np
    except ImportError:
        return 0

    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return 0

    _, threshold = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel_width = max(24, image.shape[1] // 10)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1))
    horizontal_lines = cv2.morphologyEx(threshold, cv2.MORPH_OPEN, horizontal_kernel)

    row_sum = horizontal_lines.sum(axis=1) / 255
    strong_rows = np.where(row_sum > image.shape[1] * 0.35)[0]
    line_clusters = cluster_line_indices(strong_rows.tolist())
    if len(line_clusters) < 4:
        return 0

    return max(0, len(line_clusters) - 2)


def cluster_line_indices(indices: list[int], max_gap: int = 2) -> list[list[int]]:
    if not indices:
        return []

    clusters: list[list[int]] = [[indices[0]]]
    for value in indices[1:]:
        if value - clusters[-1][-1] <= max_gap:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return clusters
