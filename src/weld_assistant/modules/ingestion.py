from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from weld_assistant.config import AppConfig
from weld_assistant.contracts import FileMetadata, InputDocument
from weld_assistant.utils.files import ensure_dir, read_json, sha256_bytes, write_json


class DocumentLoader:
    def __init__(self, config: AppConfig):
        self.config = config
        self.data_root = Path(config.pipeline.data_root)
        self.raw_dir = ensure_dir(self.data_root / "raw")
        self.index_path = self.raw_dir / "index.json"

    def load(self, file_bytes: bytes, metadata: dict | None = None) -> InputDocument:
        meta = FileMetadata.model_validate(metadata or {})
        file_hash = sha256_bytes(file_bytes)
        index = read_json(self.index_path, default={"items": []})

        for item in index["items"]:
            if item["sha256"] == file_hash:
                duplicate_doc = InputDocument.model_validate(item)
                duplicate_doc.metadata.duplicate_of = duplicate_doc.document_id
                return duplicate_doc

        document_id = self._generate_document_id(index["items"])
        extension = Path(meta.original_filename or "drawing.png").suffix or ".png"
        file_path = self.raw_dir / f"{document_id}{extension.lower()}"
        file_path.write_bytes(file_bytes)

        input_document = InputDocument(
            document_id=document_id,
            file_path=str(file_path),
            file_type=mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
            sha256=file_hash,
            received_at=datetime.now().astimezone(),
            metadata=meta,
        )

        index["items"].append(input_document.model_dump(mode="json"))
        write_json(self.index_path, index)
        return input_document

    @staticmethod
    def _generate_document_id(existing_items: list[dict]) -> str:
        prefix = datetime.now().strftime("doc_%Y%m%d")
        counter = sum(1 for item in existing_items if str(item.get("document_id", "")).startswith(prefix)) + 1
        return f"{prefix}_{counter:04d}_{uuid4().hex[:4]}"


class PdfDocumentLoader(DocumentLoader):
    def load_many(self, file_bytes: bytes, metadata: dict | None = None) -> list[InputDocument]:
        raise NotImplementedError("PDF page splitting is reserved for a later phase.")

