from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image

from weld_assistant.config import AppConfig
from weld_assistant.contracts import DrawingClassification, LayoutPlan, OCRResult, PreprocessedDocument, ROI
from weld_assistant.modules.classifier import DrawingClassifier
from weld_assistant.utils.files import ensure_dir


class RegionPlanner:
    def __init__(self, config: AppConfig):
        self.config = config
        self.roi_dir = ensure_dir(Path(config.pipeline.data_root) / "rois")
        self.classifier = DrawingClassifier()

    def build_preview_plan(self, doc: PreprocessedDocument) -> LayoutPlan:
        image = Image.open(doc.versions["clean"])
        preview_roi = ROI(
            roi_id="preview_fullpage",
            type="roi_preview",
            bbox=[0, 0, image.width, image.height],
            overlap=0.0,
            source_image_version="clean",
        )
        self._materialize_rois(doc, [preview_roi])
        return LayoutPlan(
            document_id=doc.document_id,
            rois=[preview_roi],
            drawing_type="unknown",
            supported=True,
            layout_log={"method": "preview_scan", "layout_confidence": "medium"},
        )

    def classify(self, ocr_preview: OCRResult | None) -> DrawingClassification:
        return self.classifier.classify(ocr_preview)

    def plan(
        self,
        doc: PreprocessedDocument,
        ocr_preview: OCRResult | None = None,
        classification: DrawingClassification | None = None,
    ) -> LayoutPlan:
        classification = classification or self.classify(ocr_preview)
        if not classification.supported:
            return LayoutPlan(
                document_id=doc.document_id,
                rois=[],
                drawing_type=classification.drawing_type,
                supported=False,
                rejection_reason=classification.rejection_reason,
                layout_log={
                    "method": "rejected_before_layout",
                    "layout_confidence": "high" if classification.matched_signals else "low",
                    "document_profile": classification.document_profile,
                    "drawing_type": classification.drawing_type,
                    "classification_method": classification.classification_method,
                    "matched_signals": classification.matched_signals,
                    "fallback_used": False,
                },
            )

        if classification.document_profile == "weld_log":
            return self._plan_weld_log(doc, classification)

        if self.config.layout.mode == "auto":
            planned = self._plan_auto(doc, ocr_preview, classification)
            if planned.rois:
                return planned
        return self._plan_manual(doc, ocr_preview, classification)

    def _plan_manual(
        self,
        doc: PreprocessedDocument,
        ocr_preview: OCRResult | None = None,
        classification: DrawingClassification | None = None,
    ) -> LayoutPlan:
        config_path = Path(self.config.layout.manual_roi_config)
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        classification = classification or self.classify(ocr_preview)
        profile = classification.document_profile
        templates = (
            raw.get(doc.document_id)
            or raw.get((doc.source_filename or "").lower())
            or raw.get(doc.source_filename or "")
            or raw.get(f"profile:{profile}")
            or raw.get("default")
            or []
        )

        base_image = Image.open(doc.versions["clean"])
        rois = [
            self._roi_from_template(template, base_image.width, base_image.height)
            for template in templates
        ]
        rois.extend(self._weld_rois_from_preview(ocr_preview, classification.drawing_type, profile))
        self._materialize_rois(doc, rois)
        return LayoutPlan(
            document_id=doc.document_id,
            rois=rois,
            drawing_type=classification.drawing_type,
            supported=classification.supported,
            rejection_reason=classification.rejection_reason,
            layout_log={
                "method": "manual",
                "layout_confidence": "medium",
                "fallback_used": False,
                "document_profile": profile,
                "drawing_type": classification.drawing_type,
                "classification_method": classification.classification_method,
                "matched_signals": classification.matched_signals,
            },
        )

    def _plan_auto(
        self,
        doc: PreprocessedDocument,
        ocr_preview: OCRResult | None = None,
        classification: DrawingClassification | None = None,
    ) -> LayoutPlan:
        classification = classification or self.classify(ocr_preview)
        rois: list[ROI] = []
        if ocr_preview:
            rois.extend(self._keyword_rois(doc, ocr_preview))
            rois.extend(self._weld_rois_from_preview(ocr_preview, classification.drawing_type, classification.document_profile))
        if not rois:
            return LayoutPlan(
                document_id=doc.document_id,
                rois=[],
                drawing_type=classification.drawing_type,
                supported=classification.supported,
                rejection_reason=classification.rejection_reason,
                layout_log={"layout_confidence": "low", "document_profile": classification.document_profile},
            )
        self._materialize_rois(doc, rois)
        return LayoutPlan(
            document_id=doc.document_id,
            rois=self._dedupe(rois),
            drawing_type=classification.drawing_type,
            supported=classification.supported,
            rejection_reason=classification.rejection_reason,
            layout_log={
                "method": "keyword_preview",
                "layout_confidence": "low",
                "fallback_used": True,
                "document_profile": classification.document_profile,
                "drawing_type": classification.drawing_type,
                "classification_method": classification.classification_method,
                "matched_signals": classification.matched_signals,
            },
        )

    def _plan_weld_log(self, doc: PreprocessedDocument, classification: DrawingClassification) -> LayoutPlan:
        image = Image.open(doc.versions["clean"])
        rois = [
            ROI(
                roi_id="titleblock",
                type="roi_titleblock",
                bbox=[0, 0, image.width, int(image.height * 0.18)],
                overlap=0.0,
                source_image_version="clean",
            ),
            ROI(
                roi_id="weld_log_table",
                type="roi_bom_table",
                bbox=[0, int(image.height * 0.12), image.width, int(image.height * 0.80)],
                overlap=0.02,
                source_image_version="clean",
            ),
        ]
        self._materialize_rois(doc, rois)
        return LayoutPlan(
            document_id=doc.document_id,
            rois=rois,
            drawing_type=classification.drawing_type,
            supported=classification.supported,
            rejection_reason=classification.rejection_reason,
            layout_log={
                "method": "table_only",
                "layout_confidence": "high",
                "fallback_used": False,
                "document_profile": classification.document_profile,
                "drawing_type": classification.drawing_type,
                "classification_method": classification.classification_method,
                "matched_signals": classification.matched_signals,
            },
        )

    def _keyword_rois(self, doc: PreprocessedDocument, ocr_preview: OCRResult) -> list[ROI]:
        title_keywords = tuple(k.upper() for k in self.config.layout.titleblock_keywords)
        bom_keywords = tuple(k.upper() for k in self.config.layout.bom_keywords)
        matched: list[ROI] = []

        for token in ocr_preview.tokens:
            token_text = token.text.upper()
            if any(keyword in token_text for keyword in title_keywords):
                matched.append(
                    ROI(
                        roi_id="titleblock_auto",
                        type="roi_titleblock",
                        bbox=self._expand_bbox(token.bbox, 280),
                        overlap=0.0,
                        source_image_version="clean",
                    )
                )
            if any(keyword in token_text for keyword in bom_keywords):
                matched.append(
                    ROI(
                        roi_id="bom_auto",
                        type="roi_bom_table",
                        bbox=self._expand_bbox(token.bbox, 420),
                        overlap=0.1,
                        source_image_version="clean",
                    )
                )

        if not any(roi.type == "roi_isometric" for roi in matched):
            image = Image.open(doc.versions["clean"])
            matched.append(
                ROI(
                    roi_id="iso_auto",
                    type="roi_isometric",
                    bbox=[0, 0, image.width, image.height],
                    overlap=0.05,
                    source_image_version="clean",
                )
            )
        return matched

    def _weld_rois_from_preview(
        self,
        ocr_preview: OCRResult | None,
        drawing_type: str | None = None,
        document_profile: str | None = None,
    ) -> list[ROI]:
        if not ocr_preview:
            return []
        patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.config.layout.patterns_for(drawing_type, document_profile)
        ]
        if not patterns:
            return []
        rois: list[ROI] = []
        for token in ocr_preview.tokens:
            candidate = token.text.strip().replace("—", "-")
            if not any(pattern.match(candidate) for pattern in patterns):
                continue
            rois.append(
                ROI(
                    roi_id=f"weld_{candidate.replace(' ', '').replace('-', '')}",
                    type="roi_weld_label",
                    bbox=self._expand_bbox(token.bbox, self.config.layout.weld_roi_padding_px),
                    overlap=self.config.layout.weld_roi_overlap,
                    source_image_version="clean",
                    weld_hint=token.text,
                )
            )
        return self._dedupe(rois)

    @staticmethod
    def _dedupe(rois: list[ROI]) -> list[ROI]:
        unique: dict[tuple[str, tuple[int, ...]], ROI] = {}
        for roi in rois:
            unique[(roi.type, tuple(roi.bbox))] = roi
        return list(unique.values())

    @staticmethod
    def _expand_bbox(bbox: list[int], padding: int) -> list[int]:
        x1, y1, x2, y2 = bbox
        return [max(0, x1 - padding), max(0, y1 - padding), x2 + padding, y2 + padding]

    def _roi_from_template(self, template: dict, width: int, height: int) -> ROI:
        if "bbox" in template:
            bbox = template["bbox"]
        else:
            x1, y1, x2, y2 = template["bbox_ratio"]
            bbox = [int(width * x1), int(height * y1), int(width * x2), int(height * y2)]
        return ROI(
            roi_id=template["roi_id"],
            type=template["type"],
            bbox=bbox,
            overlap=template.get("overlap", 0.0),
            source_image_version=template.get("source_image_version", "clean"),
            weld_hint=template.get("weld_hint"),
        )

    def _materialize_rois(self, doc: PreprocessedDocument, rois: list[ROI]) -> None:
        source_suffix = ""
        if doc.source_filename:
            source_suffix = re.sub(r"[^A-Z0-9]+", "_", Path(doc.source_filename).stem.upper()).strip("_")
        for roi in rois:
            source = Image.open(doc.versions.get(roi.source_image_version, doc.versions["clean"]))
            cropped = source.crop(tuple(roi.bbox))
            name_parts = [doc.document_id]
            if source_suffix:
                name_parts.append(source_suffix)
            name_parts.append(roi.roi_id)
            output_path = self.roi_dir / f"{'_'.join(name_parts)}.png"
            cropped.save(output_path)
            roi.image_path = str(output_path)
