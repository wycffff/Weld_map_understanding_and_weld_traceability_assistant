from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from PIL import Image

from weld_assistant.config import AppConfig
from weld_assistant.modules.ingestion import DocumentLoader
from weld_assistant.modules.preprocessing import Preprocessor


class ServiceSmokeTest(unittest.TestCase):
    def test_ingestion_and_preprocessing(self) -> None:
        temp_root = Path("data/test_runs")
        temp_root.mkdir(parents=True, exist_ok=True)
        tmpdir = temp_root / f"svc_{uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        config = AppConfig.model_validate({"pipeline": {"data_root": str(tmpdir)}})
        image_path = tmpdir / "input.png"
        Image.new("RGB", (200, 100), color="white").save(image_path)

        loader = DocumentLoader(config)
        doc = loader.load(image_path.read_bytes(), {"original_filename": "input.png"})
        preprocessed = Preprocessor(config).process(doc)

        self.assertTrue(Path(doc.file_path).exists())
        self.assertTrue(Path(preprocessed.versions["clean"]).exists())
        self.assertTrue(Path(preprocessed.versions["strong"]).exists())


if __name__ == "__main__":
    unittest.main()
