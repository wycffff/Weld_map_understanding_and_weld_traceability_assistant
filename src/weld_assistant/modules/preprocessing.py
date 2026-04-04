from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from weld_assistant.config import AppConfig
from weld_assistant.contracts import InputDocument, PreprocessedDocument
from weld_assistant.utils.files import ensure_dir


class Preprocessor:
    def __init__(self, config: AppConfig):
        self.config = config
        self.processed_dir = ensure_dir(Path(config.pipeline.data_root) / "processed")

    def process(self, doc: InputDocument) -> PreprocessedDocument:
        image = Image.open(doc.file_path).convert("RGB")
        resized = self._resize(image)

        clean = self._make_clean(resized)
        strong = self._make_strong(resized)

        clean_path = self.processed_dir / f"{doc.document_id}_clean.png"
        strong_path = self.processed_dir / f"{doc.document_id}_strong.png"
        clean.save(clean_path)
        strong.save(strong_path)

        preprocess_log = {
            "grayscale": True,
            "denoise": "median_3",
            "contrast": "clahe_like_autocontrast",
            "deskew": False,
            "resize": {
                "max_width": self.config.preprocessing.max_width,
                "kept_aspect": True,
            },
            "capture_method_detected": doc.metadata.capture_method,
        }

        return PreprocessedDocument(
            document_id=doc.document_id,
            source_filename=doc.metadata.original_filename,
            versions={"clean": str(clean_path), "strong": str(strong_path)},
            preprocess_log=preprocess_log,
        )

    def _resize(self, image: Image.Image) -> Image.Image:
        max_width = self.config.preprocessing.max_width
        if image.width == max_width:
            return image
        ratio = max_width / image.width
        return image.resize((max_width, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)

    @staticmethod
    def _make_clean(image: Image.Image) -> Image.Image:
        gray = ImageOps.grayscale(image)
        filtered = gray.filter(ImageFilter.MedianFilter(size=3))
        contrasted = ImageOps.autocontrast(filtered)
        return contrasted.convert("RGB")

    @staticmethod
    def _make_strong(image: Image.Image) -> Image.Image:
        gray = ImageOps.grayscale(image)
        filtered = gray.filter(ImageFilter.MedianFilter(size=5))
        contrasted = ImageOps.autocontrast(filtered, cutoff=1)
        enhanced = ImageEnhance.Contrast(contrasted).enhance(1.5)
        sharpened = enhanced.filter(ImageFilter.SHARPEN)
        return sharpened.convert("RGB")
