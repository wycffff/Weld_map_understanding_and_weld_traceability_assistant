from __future__ import annotations

import json
import re
from pathlib import Path

from weld_assistant.config import load_config
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.services.exporter import RepositoryExporter
from weld_assistant.services.pipeline import PipelineService
from weld_assistant.services.progress import ProgressService, normalize_manual_weld_id


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
    progress_service = ProgressService(repository)

    st.set_page_config(page_title="Weld Traceability Assistant", layout="wide")
    st.title("Weld Traceability Assistant")
    st.caption(
        f"OCR engine: {config.ocr.engine} | "
        f"VLM default: {'enabled' if config.vlm.enabled else 'disabled'} "
        f"({config.vlm.model}, mode={config.vlm.mode})"
    )

    warnings = pipeline.validate_runtime()
    for warning in warnings:
        st.warning(warning)
    if not config.vlm.enabled:
        st.info(
            "VLM assistance is disabled by default in config/config.yaml. "
            "You can still turn it on per run below. OCR remains the primary source of truth."
        )
    st.warning(
        "Local Ollama vision inference is currently CPU-bound on this machine, "
        "so VLM is best used selectively on hard cases instead of every batch by default."
    )

    uploaded = st.file_uploader("Upload drawing", type=["png", "jpg", "jpeg", "webp"])
    persist = st.checkbox("Persist to database", value=True)
    use_vlm = st.checkbox(
        "Use VLM assistance for this run",
        value=config.vlm.enabled,
        help="Recommended only for hard drawings or review-heavy cases on the current CPU-only Ollama runtime.",
    )
    if use_vlm:
        st.caption(
            f"VLM run settings: model={config.vlm.model}, mode={config.vlm.mode}, "
            f"max_tasks={config.vlm.max_tasks_per_document}"
        )

    if uploaded and st.button("Run pipeline"):
        temp_dir = Path(config.pipeline.data_root) / "ui_uploads"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / uploaded.name
        temp_path.write_bytes(uploaded.getvalue())
        with st.spinner("Processing drawing..."):
            structured = pipeline.process_file(temp_path, persist=persist, overwrite=True, use_vlm=use_vlm)
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

    if selected_drawing_number:
        render_traceability_workspace(st, repository, progress_service, selected_drawing_number)

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


def render_traceability_workspace(st, repository: SQLiteRepository, progress_service: ProgressService, drawing_number: str) -> None:
    weld_rows = repository.list_welds(drawing_number)
    st.subheader("Weld Traceability")
    manual_tab, manage_tab = st.tabs(["Manual weld intake", "Manage stored welds"])

    with manual_tab:
        st.caption(
            "Use this for drawings that are already scanned into the database but still miss some weld rows. "
            "You can register one or many weld IDs, skip already-existing IDs, and for a single weld also attach the first photo immediately."
        )
        if weld_rows:
            existing_ids = [row["weld_id"] for row in weld_rows]
            preview = ", ".join(existing_ids[:12])
            suffix = " ..." if len(existing_ids) > 12 else ""
            st.caption(f"Existing weld IDs: {preview}{suffix}")
        with st.form(f"manual_weld_form_{drawing_number}"):
            weld_id_text = st.text_area(
                "Weld IDs",
                key=f"manual_weld_id_{drawing_number}",
                help="Enter one weld ID per line or use commas. Examples: W01, W02, 1, 2",
            )
            location_description = st.text_input(
                "Shared location description (optional)",
                key=f"manual_weld_location_{drawing_number}",
            )
            operator = st.text_input("Recorded by", key=f"manual_weld_operator_{drawing_number}")
            note = st.text_input("Registration note", key=f"manual_weld_note_{drawing_number}")
            skip_existing = st.checkbox(
                "Skip weld IDs that already exist",
                value=True,
                key=f"manual_weld_skip_existing_{drawing_number}",
            )
            uploaded_photo = st.file_uploader(
                "Optional first weld photo for a single weld ID",
                type=["png", "jpg", "jpeg", "webp"],
                key=f"manual_weld_photo_{drawing_number}",
            )
            submitted = st.form_submit_button("Register weld")
        if submitted:
            normalized_ids = parse_manual_weld_ids(weld_id_text)
            if not normalized_ids:
                st.error("Enter at least one valid weld ID first.")
            elif uploaded_photo and len(normalized_ids) != 1:
                st.error("Photo linking from the manual intake form only works when exactly one weld ID is submitted.")
            else:
                result = progress_service.register_welds(
                    drawing_number=drawing_number,
                    weld_ids=normalized_ids,
                    location_description=location_description.strip() or None,
                    operator=operator.strip() or None,
                    note=note.strip() or None,
                    skip_existing=skip_existing,
                )
                created_ids = result["created"]
                skipped_ids = result["skipped_existing"]
                if uploaded_photo:
                    target_weld_id = normalized_ids[0]
                    evidence = progress_service.link_photo(
                        drawing_number=drawing_number,
                        weld_id=target_weld_id,
                        file_bytes=uploaded_photo.getvalue(),
                        filename=uploaded_photo.name,
                        linked_by=operator.strip() or None,
                        note=note.strip() or None,
                    )
                    st.success(
                        f"Processed weld intake for {target_weld_id}. "
                        f"Created: {', '.join(created_ids) if created_ids else 'none'}; "
                        f"skipped existing: {', '.join(skipped_ids) if skipped_ids else 'none'}. "
                        f"Linked photo {evidence.photo_id}."
                    )
                else:
                    st.success(
                        f"Created welds: {', '.join(created_ids) if created_ids else 'none'}. "
                        f"Skipped existing: {', '.join(skipped_ids) if skipped_ids else 'none'}."
                    )
                st.rerun()

    with manage_tab:
        if not weld_rows:
            st.caption("No weld rows are stored for this drawing yet. Use the manual intake tab above to create one.")
            photo_rows = repository.list_photo_evidence(drawing_number)
            if photo_rows:
                st.caption("Drawing-level linked photos")
                st.dataframe([dict(row) for row in photo_rows], use_container_width=True)
            return

        st.dataframe([dict(row) for row in weld_rows], use_container_width=True)

        selected_weld_id = st.selectbox(
            "Select weld",
            options=[row["weld_id"] for row in weld_rows],
            key=f"weld_select_{drawing_number}",
        )
        selected_weld = next(row for row in weld_rows if row["weld_id"] == selected_weld_id)

        status_tab, inspection_tab, photo_tab, history_tab = st.tabs(
            ["Status", "Inspection", "Photo evidence", "History"]
        )

        with status_tab:
            with st.form(f"status_form_{drawing_number}_{selected_weld_id}"):
                next_status = st.selectbox(
                    "Next status",
                    options=unique_options(selected_weld["status"], ["not_started", "in_progress", "done", "blocked"]),
                )
                operator = st.text_input("Operator", key=f"status_operator_{drawing_number}_{selected_weld_id}")
                note = st.text_input("Note", key=f"status_note_{drawing_number}_{selected_weld_id}")
                submitted = st.form_submit_button("Update status")
            if submitted:
                event = progress_service.update_status(
                    drawing_number=drawing_number,
                    weld_id=selected_weld_id,
                    to_status=next_status,
                    operator=operator or None,
                    note=note or None,
                )
                st.success(f"Status updated: {event.from_status} -> {event.to_status}")
                st.rerun()

        with inspection_tab:
            with st.form(f"inspection_form_{drawing_number}_{selected_weld_id}"):
                next_inspection = st.selectbox(
                    "Inspection status",
                    options=unique_options(selected_weld["inspection_status"], ["not_checked", "pending", "accepted", "rejected"]),
                )
                operator = st.text_input("Inspector", key=f"inspection_operator_{drawing_number}_{selected_weld_id}")
                note = st.text_input("Inspection note", key=f"inspection_note_{drawing_number}_{selected_weld_id}")
                submitted = st.form_submit_button("Update inspection")
            if submitted:
                event = progress_service.update_inspection(
                    drawing_number=drawing_number,
                    weld_id=selected_weld_id,
                    inspection_status=next_inspection,
                    operator=operator or None,
                    note=note or None,
                )
                st.success(f"Inspection updated: {event.from_status} -> {event.to_status}")
                st.rerun()

        with photo_tab:
            uploaded_photo = st.file_uploader(
                "Upload weld photo",
                type=["png", "jpg", "jpeg", "webp"],
                key=f"photo_upload_{drawing_number}_{selected_weld_id}",
            )
            linked_by = st.text_input("Linked by", key=f"photo_operator_{drawing_number}_{selected_weld_id}")
            note = st.text_input("Photo note", key=f"photo_note_{drawing_number}_{selected_weld_id}")
            if st.button("Link photo to weld", key=f"photo_submit_{drawing_number}_{selected_weld_id}"):
                if not uploaded_photo:
                    st.error("Choose a photo file first.")
                else:
                    evidence = progress_service.link_photo(
                        drawing_number=drawing_number,
                        weld_id=selected_weld_id,
                        file_bytes=uploaded_photo.getvalue(),
                        filename=uploaded_photo.name,
                        linked_by=linked_by or None,
                        note=note or None,
                    )
                    st.success(f"Linked photo {evidence.photo_id} to {selected_weld_id}")
                    st.rerun()

        with history_tab:
            event_rows = repository.list_weld_progress(drawing_number, selected_weld_id)
            photo_rows = repository.list_photo_evidence(drawing_number, selected_weld_id)

            st.caption(f"Events for {drawing_number} / {selected_weld_id}")
            if event_rows:
                st.dataframe([dict(row) for row in event_rows], use_container_width=True)
            else:
                st.caption("No events recorded yet.")

            st.caption("Linked photos")
            if photo_rows:
                st.dataframe([dict(row) for row in photo_rows], use_container_width=True)
                preview_columns = st.columns(min(3, len(photo_rows)))
                for index, row in enumerate(photo_rows[:3]):
                    with preview_columns[index % len(preview_columns)]:
                        st.image(row["file_path"], caption=f"{row['photo_id']} | {row['linked_at']}")
            else:
                st.caption("No photos linked yet.")


def unique_options(current_value: str | None, options: list[str]) -> list[str]:
    ordered = [current_value] if current_value else []
    ordered.extend(options)
    seen: set[str] = set()
    result: list[str] = []
    for item in ordered:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def parse_manual_weld_ids(raw_value: str) -> list[str]:
    values = re.split(r"[\s,;]+", raw_value or "")
    normalized: list[str] = []
    for value in values:
        normalized_value = normalize_manual_weld_id(value)
        if normalized_value:
            normalized.append(normalized_value)
    return dedupe_preserve_order(normalized)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


if __name__ == "__main__":  # pragma: no cover
    main()
