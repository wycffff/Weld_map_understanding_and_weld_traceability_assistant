from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image

from weld_assistant.config import AppConfig
from weld_assistant.contracts import LayoutPlan, OCRResult, PreprocessedDocument, ROI
from weld_assistant.utils.files import ensure_dir


class RegionPlanner:
    def __init__(self, config: AppConfig):
        self.config = config
        self.roi_dir = ensure_dir(Path(config.pipeline.data_root) / "rois")

    def plan(self, doc: PreprocessedDocument, ocr_preview: OCRResult | None = None) -> LayoutPlan:
        if self.config.layout.mode == "auto":
            planned = self._plan_auto(doc, ocr_preview)
            if planned.rois:
                return planned
        return self._plan_manual(doc, ocr_preview)

    def _plan_manual(self, doc: PreprocessedDocument, ocr_preview: OCRResult | None = None) -> LayoutPlan:
        config_path = Path(self.config.layout.manual_roi_config)
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        templates = raw.get(doc.document_id) or raw.get("default") or []

        base_image = Image.open(doc.versions["clean"])
        rois = [
            self._roi_from_template(template, base_image.width, base_image.height)
            for template in templates
        ]
        rois.extend(self._weld_rois_from_preview(ocr_preview))
        self._materialize_rois(doc, rois)
        return LayoutPlan(
            document_id=doc.document_id,
            rois=rois,
            layout_log={"method": "manual", "layout_confidence": "medium", "fallback_used": False},
        )

    def _plan_auto(self, doc: PreprocessedDocument, ocr_preview: OCRResult | None = None) -> LayoutPlan:
        rois: list[ROI] = []
        if ocr_preview:
            rois.extend(self._keyword_rois(doc, ocr_preview))
            rois.extend(self._weld_rois_from_preview(ocr_preview))
        if not rois:
            return LayoutPlan(document_id=doc.document_id, rois=[], layout_log={"layout_confidence": "low"})
        self._materialize_rois(doc, rois)
        return LayoutPlan(
            document_id=doc.document_id,
            rois=self._dedupe(rois),
            layout_log={"method": "keyword_preview", "layout_confidence": "low", "fallback_used": True},
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

    def _weld_rois_from_preview(self, ocr_preview: OCRResult | None) -> list[ROI]:
        if not ocr_preview:
            return []
        pattern = re.compile(self.config.layout.weld_id_pattern, re.IGNORECASE)
        rois: list[ROI] = []
        for token in ocr_preview.tokens:
            candidate = token.text.strip().replace("—", "-")
            if not pattern.match(candidate):
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
        for roi in rois:
            source = Image.open(doc.versions.get(roi.source_image_version, doc.versions["clean"]))
            cropped = source.crop(tuple(roi.bbox))
            output_path = self.roi_dir / f"{doc.document_id}_{roi.roi_id}.png"
            cropped.save(output_path)
            roi.image_path = str(output_path)

