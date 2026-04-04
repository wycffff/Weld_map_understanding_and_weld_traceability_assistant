from __future__ import annotations

import json
from pathlib import Path

from weld_assistant.config import load_config
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.services.exporter import RepositoryExporter
from weld_assistant.services.pipeline import PipelineService


def _require_streamlit():
    try:
        import streamlit as st
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed. Install it with `python -m pip install streamlit`.") from exc
    return st


def main() -> None:  # pragma: no cover
    st = _require_streamlit()
    config = load_config()
    pipeline = PipelineService(config)
    repository = SQLiteRepository(config)
    repository.init_db()
    repo_exporter = RepositoryExporter(config, repository)

    st.set_page_config(page_title="Weld Traceability Assistant", layout="wide")
    st.title("Weld Traceability Assistant")

    warnings = pipeline.validate_runtime()
    for warning in warnings:
        st.warning(warning)

    uploaded = st.file_uploader("Upload drawing", type=["png", "jpg", "jpeg"])
    persist = st.checkbox("Persist to database", value=True)

    if uploaded and st.button("Run pipeline"):
        temp_dir = Path(config.pipeline.data_root) / "ui_uploads"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / uploaded.name
        temp_path.write_bytes(uploaded.getvalue())
        with st.spinner("Processing drawing..."):
            structured = pipeline.process_file(temp_path, persist=persist, overwrite=True)
        st.success("Pipeline finished.")
        st.subheader("StructuredDrawing")
        st.json(structured.to_jsonable())

        if config.ui.show_roi_preview:
            roi_dir = Path(config.pipeline.data_root) / "rois"
            roi_paths = sorted(roi_dir.glob(f"{structured.document_id}_*.png"))
            if roi_paths:
                st.subheader("ROI previews")
                for roi_path in roi_paths:
                    st.image(str(roi_path), caption=roi_path.name)

    st.subheader("Export existing drawing")
    drawing_number = st.text_input("Drawing number")
    if drawing_number and st.button("Load export files"):
        json_path, csv_path = repo_exporter.export(drawing_number)
        st.code(json.dumps({"json": json_path, "csv": csv_path}, ensure_ascii=False, indent=2))
        st.download_button("Download JSON", Path(json_path).read_text(encoding="utf-8"), file_name=Path(json_path).name)
        st.download_button("Download CSV", Path(csv_path).read_text(encoding="utf-8"), file_name=Path(csv_path).name)

    st.subheader("Review queue")
    reviews = repository.list_review_queue(drawing_number or None)
    if reviews:
        st.dataframe([dict(row) for row in reviews])
    else:
        st.caption("No review items yet.")


if __name__ == "__main__":  # pragma: no cover
    main()
