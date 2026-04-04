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

    uploaded = st.file_uploader("Upload drawing", type=["png", "jpg", "jpeg", "webp"])
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
    drawing_query = st.text_input("Search by drawing number, spool name, or document id")
    drawing_matches = repository.search_drawings(drawing_query, limit=12) if drawing_query else repository.list_drawings(limit=12)

    selected_drawing_number: str | None = None
    if drawing_matches:
        selected_drawing_number = st.selectbox(
            "Matching drawings",
            options=[row["drawing_number"] for row in drawing_matches],
            format_func=lambda number: format_drawing_option(number, drawing_matches),
        )
    elif drawing_query:
        st.caption("No matching drawings found.")

    if selected_drawing_number and st.button("Load export files"):
        json_path, csv_path = repo_exporter.export(selected_drawing_number)
        st.code(json.dumps({"json": json_path, "csv": csv_path}, ensure_ascii=False, indent=2))
        st.download_button("Download JSON", Path(json_path).read_text(encoding="utf-8"), file_name=Path(json_path).name)
        st.download_button("Download CSV", Path(csv_path).read_text(encoding="utf-8"), file_name=Path(csv_path).name)

    st.subheader("Review queue")
    reviews = repository.list_review_queue(selected_drawing_number or None)
    if reviews:
        st.dataframe([dict(row) for row in reviews])
    else:
        st.caption("No review items yet.")


def format_drawing_option(drawing_number: str, matches) -> str:
    row = next(row for row in matches if row["drawing_number"] == drawing_number)
    parts = [drawing_number]
    if row["spool_name"]:
        parts.append(f"spool={row['spool_name']}")
    if row["document_id"]:
        parts.append(f"doc={row['document_id']}")
    return " | ".join(parts)


if __name__ == "__main__":  # pragma: no cover
    main()
