from __future__ import annotations

import re

from weld_assistant.contracts import DrawingClassification, OCRResult


class DrawingClassifier:
    def classify(self, ocr_preview: OCRResult | None) -> DrawingClassification:
        if not ocr_preview or not ocr_preview.tokens:
            return DrawingClassification(
                drawing_type="unknown",
                document_profile="default",
                supported=False,
                rejection_reason="drawing_type_unknown",
                matched_signals=[],
            )

        raw_texts = [token.raw_text or token.text for token in ocr_preview.tokens]
        raw_joined = " ".join(text.upper() for text in raw_texts)
        compact = re.sub(r"[^A-Z0-9]", "", raw_joined)
        normalized_tokens = [re.sub(r"[^A-Z0-9-]", "", text.upper()) for text in raw_texts]
        has_spool_code = any(re.search(r"\d+[A-Z0-9]*-\d+", token) for token in normalized_tokens)
        has_pipeline_code = bool(re.search(r"N-\d+-P-\d+-[A-Z0-9]+", raw_joined))
        has_welding_list_signal = any(keyword in compact for keyword in ("WELDINGLIST", "WELDINGUIST", "WELDINGL1ST"))
        has_material_table_signal = any(keyword in compact for keyword in ("ERECTIONMATERIALS", "FABRICATIONMATERIALS"))

        if any(keyword in compact for keyword in ("SHELLSIDE", "TUBESIDE", "NATIONALBOARD")):
            return DrawingClassification(
                drawing_type="pressure_vessel",
                document_profile="unsupported",
                supported=False,
                rejection_reason="drawing_type_not_supported",
                matched_signals=collect_signals(compact, ("SHELLSIDE", "TUBESIDE", "NATIONALBOARD")),
            )

        if "GENERALARRANGEMENT" in compact or "P&ID" in raw_joined or re.search(r"\bP\s*&\s*ID\b", raw_joined):
            return DrawingClassification(
                drawing_type="other",
                document_profile="unsupported",
                supported=False,
                rejection_reason="drawing_type_not_supported",
                matched_signals=collect_signals(compact, ("GENERALARRANGEMENT",)),
            )

        if (has_welding_list_signal and ("PIPELINENAME" in compact or has_pipeline_code)) or (has_material_table_signal and has_pipeline_code):
            return DrawingClassification(
                drawing_type="pipeline_isometric",
                document_profile="welding_map_sheet",
                matched_signals=collect_signals(
                    compact,
                    ("WELDINGLIST", "WELDINGUIST", "PIPELINENAME", "ERECTIONMATERIALS", "FABRICATIONMATERIALS"),
                ),
            )

        if ("PARTSLIST" in compact or "BILLOFMATERIALS" in compact) and (
            "WPS" in compact or "WPQR" in compact or re.search(r"\bW\d+\b", raw_joined)
        ):
            return DrawingClassification(
                drawing_type="fabrication_weld_map",
                document_profile="fabrication_weld_sheet",
                matched_signals=collect_signals(compact, ("PARTSLIST", "BILLOFMATERIALS", "WPS", "WPQR")),
            )

        if "BILLOFMATERIALS" in compact and has_spool_code:
            return DrawingClassification(
                drawing_type="simple_spool",
                document_profile="simple_spool",
                matched_signals=collect_signals(compact, ("BILLOFMATERIALS",)) + ["SPOOL_CODE"],
            )

        if compact.count("ISOMETRICDRAWING") >= 2 or ("ISOMETRICDRAWING" in compact and "WELDNO" in compact):
            return DrawingClassification(
                drawing_type="dual_isometric",
                document_profile="dual_isometric_sheet",
                matched_signals=collect_signals(compact, ("ISOMETRICDRAWING", "WELDNO")),
            )

        return DrawingClassification(
            drawing_type="unknown",
            document_profile="default",
            supported=False,
            rejection_reason="drawing_type_unknown",
            matched_signals=[],
        )


def collect_signals(compact_text: str, candidates: tuple[str, ...]) -> list[str]:
    return [candidate for candidate in candidates if candidate in compact_text]
