from __future__ import annotations

import json
import re
from pathlib import Path

from weld_assistant.config import load_config
from weld_assistant.db.repository import SQLiteRepository
from weld_assistant.services.exporter import RepositoryExporter, event_status, latest_stage_events_by_weld
from weld_assistant.services.pipeline import PipelineService
from weld_assistant.services.progress import ProgressService, normalize_manual_weld_id
from weld_assistant.services.review import ReviewService


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
    review_service = ReviewService(repository, pipeline.vlm)

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
    st.caption(
        f"VLM timeouts: visual tasks={config.vlm.request_timeout_sec}s, "
        f"review assistant default={config.vlm.review_request_timeout_sec}s"
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
        if not structured.drawing.drawing_type_supported:
            st.error(
                f"Automatic parsing was rejected for drawing type `{structured.drawing.drawing_type}`. "
                f"Reason: {structured.drawing.classification_reason or 'drawing_type_unknown'}. "
                "Use manual intake if this drawing still needs traceability records."
            )
        elif structured.drawing.drawing_type == "unknown":
            st.warning("The drawing type could not be classified confidently. Please verify the result before trusting auto-extracted data.")
        st.subheader("StructuredDrawing")
        st.json(structured.to_jsonable())

        if config.ui.show_roi_preview:
            roi_dir = Path(config.pipeline.data_root) / "rois"
            roi_paths = sorted(roi_dir.glob(f"{structured.document_id}_*.png"))
            if roi_paths:
                st.subheader("ROI previews")
                for roi_path in roi_paths:
                    st.image(str(roi_path), caption=roi_path.name)

    st.subheader("Open drawing")
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

    if selected_drawing_number:
        render_traceability_workspace(st, repository, progress_service, repo_exporter, selected_drawing_number)

    render_review_queue_workspace(st, repository, progress_service, review_service, selected_drawing_number)


def format_drawing_option(drawing_number: str, matches) -> str:
    row = next(row for row in matches if row["drawing_number"] == drawing_number)
    parts = [drawing_number]
    if row["spool_name"]:
        parts.append(f"spool={row['spool_name']}")
    if row["document_id"]:
        parts.append(f"doc={row['document_id']}")
    return " | ".join(parts)


def render_traceability_workspace(
    st,
    repository: SQLiteRepository,
    progress_service: ProgressService,
    repo_exporter: RepositoryExporter,
    drawing_number: str,
) -> None:
    drawing_row = repository.get_drawing(drawing_number)
    weld_rows = repository.list_welds(drawing_number)
    review_rows = repository.list_review_queue(drawing_number, unresolved_only=True)
    photo_rows = repository.list_photo_evidence(drawing_number)
    progress_rows = repository.list_weld_progress(drawing_number)
    st.subheader("Weld Traceability")
    render_drawing_health_summary(st, drawing_row, weld_rows, review_rows, photo_rows)
    render_weld_log_header(st, drawing_row)
    render_traceability_action_bar(st, repo_exporter, drawing_number)

    log_tab, manual_tab, operations_tab = st.tabs(["WELD LOG view", "Manual weld intake", "Operations"])

    with log_tab:
        render_weld_log_workspace(st, progress_service, drawing_number, weld_rows, review_rows, progress_rows)

    with manual_tab:
        st.caption(
            "Use this for drawings that are already scanned into the database but still miss some weld rows. "
            "Weld identity is scoped by drawing number, so the same weld ID can exist on another drawing. "
            "Within the selected drawing, you can register one or many weld IDs, skip already-existing IDs, "
            "and for a single weld also attach the first photo immediately."
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

    with operations_tab:
        if not weld_rows:
            st.error(
                "No weld rows are stored for this drawing yet. "
                "This usually means the drawing needs manual intake or the source image quality is too low for the current OCR path."
            )
            st.caption("Use the manual intake tab above to create weld rows before linking progress or photos.")
            if photo_rows:
                st.caption("Drawing-level linked photos")
                st.dataframe([dict(row) for row in photo_rows], use_container_width=True)
            return

        selected_weld_id = st.selectbox(
            "Select weld for operations",
            options=[row["weld_id"] for row in weld_rows],
            key=f"weld_select_{drawing_number}",
        )
        selected_weld = next(row for row in weld_rows if row["weld_id"] == selected_weld_id)

        batch_tab, photo_tab, history_tab = st.tabs(
            ["Batch update", "Upload photo", "History"]
        )

        with batch_tab:
            with st.form(f"batch_update_form_{drawing_number}"):
                batch_weld_ids = st.multiselect(
                    "Welds to update",
                    options=[row["weld_id"] for row in weld_rows],
                    default=[selected_weld_id],
                    key=f"batch_weld_ids_{drawing_number}",
                )
                batch_mode = st.selectbox(
                    "Update type",
                    options=["weld_status", "inspection_status"],
                    format_func=lambda value: "WELD status" if value == "weld_status" else "VT status",
                    key=f"batch_mode_{drawing_number}",
                )
                batch_value = st.selectbox(
                    "New value",
                    options=["not_started", "in_progress", "done", "blocked"]
                    if batch_mode == "weld_status"
                    else ["not_checked", "pending", "accepted", "rejected"],
                    key=f"batch_value_{drawing_number}",
                )
                operator = st.text_input("Operator", key=f"batch_operator_{drawing_number}")
                note = st.text_input("Batch note", key=f"batch_note_{drawing_number}")
                submitted = st.form_submit_button("Apply batch update")
            if submitted:
                if not batch_weld_ids:
                    st.error("Select at least one weld first.")
                else:
                    for weld_id in batch_weld_ids:
                        if batch_mode == "weld_status":
                            progress_service.update_status(
                                drawing_number=drawing_number,
                                weld_id=weld_id,
                                to_status=batch_value,
                                operator=operator or None,
                                note=note or None,
                            )
                        else:
                            progress_service.update_inspection(
                                drawing_number=drawing_number,
                                weld_id=weld_id,
                                inspection_status=batch_value,
                                operator=operator or None,
                                note=note or None,
                            )
                    st.success(f"Updated {len(batch_weld_ids)} weld row(s).")
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


def render_weld_log_header(st, drawing_row) -> None:
    if not drawing_row:
        return

    row_one = st.columns(3)
    row_one[0].markdown(f"**Drawing**  \n{drawing_row['drawing_number'] or ''}")
    row_one[1].markdown("**P&ID**  \n")
    row_one[2].markdown(f"**Project**  \n{drawing_row['project_number'] or ''}")

    row_two = st.columns(3)
    row_two[0].markdown(f"**Pack**  \n{drawing_row['spool_name'] or ''}")
    row_two[1].markdown("**System**  \n")
    row_two[2].markdown("**Client**  \n")


def render_traceability_action_bar(st, repo_exporter: RepositoryExporter, drawing_number: str) -> None:
    json_path, csv_path = repo_exporter.export(drawing_number)
    weld_log_path = repo_exporter.export_weld_log_csv(drawing_number)

    action_columns = st.columns(3)
    action_columns[0].download_button(
        "Export WELD LOG",
        Path(weld_log_path).read_text(encoding="utf-8"),
        file_name=Path(weld_log_path).name,
        key=f"download_weld_log_{drawing_number}",
        use_container_width=True,
    )
    action_columns[1].download_button(
        "Export CSV",
        Path(csv_path).read_text(encoding="utf-8"),
        file_name=Path(csv_path).name,
        key=f"download_csv_{drawing_number}",
        use_container_width=True,
    )
    action_columns[2].download_button(
        "Export JSON",
        Path(json_path).read_text(encoding="utf-8"),
        file_name=Path(json_path).name,
        key=f"download_json_{drawing_number}",
        use_container_width=True,
    )


def render_weld_log_workspace(st, progress_service: ProgressService, drawing_number: str, weld_rows, review_rows, progress_rows) -> None:
    if not weld_rows:
        st.error(
            "No weld rows are stored for this drawing yet. "
            "Use the manual intake tab to create weld rows before using the WELD LOG workflow."
        )
        return

    stage_events = latest_stage_events_by_weld([dict(row) for row in progress_rows])
    st.caption("Rows marked with ⚠ need operator review. WELD and VT buttons open a quick inline update panel.")
    header_columns = st.columns([1.0, 1.4, 1.0, 1.1, 0.7, 0.7, 0.7, 0.7, 0.9])
    labels = ["WELD#", "JOINT TYPE", "DIAMETER", "WPS", "ROOT", "WELD", "VT", "RT", "PHOTOS"]
    for column, label in zip(header_columns, labels):
        column.markdown(f"**{label}**")

    for weld in weld_rows:
        render_weld_log_row(st, drawing_number, weld, review_rows, progress_service, stage_events)

    render_inline_weld_update_panel(st, progress_service, drawing_number, weld_rows)


def render_weld_log_row(st, drawing_number: str, weld_row, review_rows, progress_service: ProgressService, stage_events) -> None:
    weld_id = weld_row["weld_id"]
    root_event = stage_events.get((weld_id, "root"))
    weld_event = stage_events.get((weld_id, "weld"))
    vt_event = stage_events.get((weld_id, "vt"))
    rt_event = stage_events.get((weld_id, "rt"))
    is_review = bool(weld_row["needs_review"]) or any(row["weld_id"] == weld_id for row in review_rows if row["weld_id"])

    row_columns = st.columns([1.0, 1.4, 1.0, 1.1, 0.7, 0.7, 0.7, 0.7, 0.9])
    weld_label = f"⚠ {weld_id}" if is_review else weld_id
    if is_review:
        row_columns[0].markdown(
            f"<div style='background:#fff3cd;padding:0.35rem 0.5rem;border-radius:0.4rem;'><strong>{weld_label}</strong></div>",
            unsafe_allow_html=True,
        )
    else:
        row_columns[0].markdown(f"**{weld_label}**")
    row_columns[1].write(weld_row["weld_type"] or "-")
    row_columns[2].write(weld_row["pipe_size"] or "-")
    row_columns[3].write(weld_row["wps_number"] or "-")
    row_columns[4].markdown(stage_icon(event_status(root_event), is_review and not root_event))

    if row_columns[5].button(stage_button_label(event_status(weld_event, fallback=weld_row["status"])), key=f"open_weld_status_{drawing_number}_{weld_id}", use_container_width=True):
        st.session_state[f"traceability_quick_action_{drawing_number}"] = {"weld_id": weld_id, "mode": "status"}
        st.rerun()
    if row_columns[6].button(stage_button_label(event_status(vt_event, fallback=weld_row["inspection_status"])), key=f"open_weld_vt_{drawing_number}_{weld_id}", use_container_width=True):
        st.session_state[f"traceability_quick_action_{drawing_number}"] = {"weld_id": weld_id, "mode": "inspection"}
        st.rerun()

    row_columns[7].markdown(stage_icon(event_status(rt_event), is_review and not rt_event))
    row_columns[8].write(str(len(progress_service.repository.list_photo_evidence(drawing_number, weld_id))))


def render_inline_weld_update_panel(st, progress_service: ProgressService, drawing_number: str, weld_rows) -> None:
    action_state = st.session_state.get(f"traceability_quick_action_{drawing_number}")
    if not action_state:
        return

    weld_id = action_state["weld_id"]
    mode = action_state["mode"]
    selected_weld = next((row for row in weld_rows if row["weld_id"] == weld_id), None)
    if not selected_weld:
        st.session_state.pop(f"traceability_quick_action_{drawing_number}", None)
        return

    st.markdown("---")
    st.markdown(f"**Quick update: {drawing_number} / {weld_id}**")
    with st.form(f"quick_update_form_{drawing_number}_{weld_id}_{mode}"):
        if mode == "status":
            next_value = st.selectbox(
                "Next WELD status",
                options=unique_options(selected_weld["status"], ["not_started", "in_progress", "done", "blocked"]),
                key=f"quick_status_value_{drawing_number}_{weld_id}",
            )
        else:
            next_value = st.selectbox(
                "Next VT status",
                options=unique_options(selected_weld["inspection_status"], ["not_checked", "pending", "accepted", "rejected"]),
                key=f"quick_inspection_value_{drawing_number}_{weld_id}",
            )
        operator = st.text_input("Operator", key=f"quick_operator_{drawing_number}_{weld_id}_{mode}")
        note = st.text_input("Note", key=f"quick_note_{drawing_number}_{weld_id}_{mode}")
        submit_columns = st.columns(2)
        submitted = submit_columns[0].form_submit_button("Apply update")
        cancelled = submit_columns[1].form_submit_button("Cancel")

    if cancelled:
        st.session_state.pop(f"traceability_quick_action_{drawing_number}", None)
        st.rerun()

    if submitted:
        if mode == "status":
            progress_service.update_status(
                drawing_number=drawing_number,
                weld_id=weld_id,
                to_status=next_value,
                operator=operator or None,
                note=note or None,
            )
        else:
            progress_service.update_inspection(
                drawing_number=drawing_number,
                weld_id=weld_id,
                inspection_status=next_value,
                operator=operator or None,
                note=note or None,
            )
        st.session_state.pop(f"traceability_quick_action_{drawing_number}", None)
        st.success(f"Updated {drawing_number}/{weld_id}.")
        st.rerun()


def stage_button_label(status_value: str) -> str:
    return stage_icon(status_value).replace("`", "")


def stage_icon(status_value: str | None, warn: bool = False) -> str:
    normalized = (status_value or "").strip().upper()
    if warn:
        return "⚠"
    if normalized in {"COMPLETE", "ACCEPT"}:
        return "✅"
    if normalized in {"IN PROGRESS", "PENDING"}:
        return "🔄"
    if normalized in {"REJECT", "BLOCKED"}:
        return "⚠"
    return "🔲"


def render_review_queue_workspace(
    st,
    repository: SQLiteRepository,
    progress_service: ProgressService,
    review_service: ReviewService,
    drawing_number: str | None,
) -> None:
    st.subheader("Review queue")
    unresolved_only = st.checkbox(
        "Show unresolved items only",
        value=True,
        key=f"review_unresolved_only_{drawing_number or 'all'}",
    )
    reviews = repository.list_review_queue(drawing_number, unresolved_only=unresolved_only)
    if not reviews:
        st.caption("No review items for the current filter.")
        return

    st.dataframe([summarize_review_row(row) for row in reviews], use_container_width=True)
    selected_review_id = st.selectbox(
        "Select review item",
        options=[row["review_id"] for row in reviews],
        format_func=lambda review_id: format_review_option(review_id, reviews),
        key=f"review_select_{drawing_number or 'all'}",
    )
    selected_review = next(row for row in reviews if row["review_id"] == selected_review_id)
    suggestion = review_service.suggest_review_item(selected_review_id, use_llm=False)
    payload = json.loads(selected_review["payload_json"])

    scope = selected_review["drawing_number"] or selected_review["document_id"]
    if selected_review["weld_id"]:
        scope = f"{scope}/{selected_review['weld_id']}"
    st.caption(f"Review scope: {scope}")
    st.json(payload)

    heuristic = suggestion["heuristic"]
    st.info(
        f"Heuristic recommendation: {heuristic['recommended_action']} | "
        f"confidence={heuristic['confidence']:.2f}\n\n{heuristic['summary']}"
    )
    if heuristic.get("notes"):
        st.caption(heuristic["notes"])

    operator = st.text_input("Review operator", key=f"review_operator_{selected_review_id}")
    note = st.text_input("Review note", key=f"review_note_{selected_review_id}")
    candidate_weld_ids = heuristic["candidate_weld_ids"]
    action_columns = st.columns(3)
    review_timeout_sec = int(
        st.number_input(
            "M5 review timeout (sec)",
            min_value=30,
            max_value=600,
            value=configured_review_timeout_seconds(review_service),
            step=30,
            key=f"review_timeout_{selected_review_id}",
            help="Use a longer timeout for very small local models on CPU if they are slow but eventually respond.",
        )
    )

    if st.button("Run M5 review assistant", key=f"review_assist_{selected_review_id}"):
        with st.spinner(f"Running bounded M5 review assist (timeout {review_timeout_sec}s)..."):
            st.session_state[f"review_assist_result_{selected_review_id}"] = review_service.suggest_review_item(
                selected_review_id,
                use_llm=True,
                timeout_override_sec=review_timeout_sec,
            )
        st.rerun()

    review_assist_result = st.session_state.get(f"review_assist_result_{selected_review_id}")
    if review_assist_result and review_assist_result.get("llm"):
        llm_result = review_assist_result["llm"]
        if llm_result.get("error"):
            st.warning(f"M5 review assist failed: {llm_result['error']}")
            if "timed out" in str(llm_result["error"]).lower():
                st.caption("Tip: increase the review timeout above if the local model is slow but usually completes.")
        else:
            st.success(
                f"M5 recommendation: {llm_result['recommended_action']} | "
                f"confidence={llm_result['confidence']:.2f} | "
                f"latency={llm_result['latency_ms']}ms"
            )
            st.write(llm_result["summary"])
            if llm_result.get("notes"):
                st.caption(llm_result["notes"])
            st.caption("AI-generated review guidance is advisory only. The final decision remains with the operator.")

    if candidate_weld_ids and selected_review["drawing_number"]:
        with action_columns[0]:
            if st.button("Register candidate welds", key=f"review_register_{selected_review_id}"):
                result = progress_service.register_welds(
                    drawing_number=selected_review["drawing_number"],
                    weld_ids=candidate_weld_ids,
                    operator=operator.strip() or None,
                    note=(note.strip() or None) or f"Accepted from review item {selected_review_id}.",
                    skip_existing=True,
                )
                repository.resolve_review_item(selected_review_id)
                st.success(
                    f"Processed review item {selected_review_id}. "
                    f"Created: {', '.join(result['created']) if result['created'] else 'none'}; "
                    f"skipped existing: {', '.join(result['skipped_existing']) if result['skipped_existing'] else 'none'}."
                )
                st.rerun()
        st.caption(
            f"Candidate weld IDs for {selected_review['drawing_number']}: {', '.join(candidate_weld_ids)}"
        )

    if selected_review["resolved_at"]:
        with action_columns[1]:
            if st.button("Reopen review item", key=f"review_reopen_{selected_review_id}"):
                repository.reopen_review_item(selected_review_id)
                st.success(f"Reopened review item {selected_review_id}.")
                st.rerun()
    else:
        with action_columns[1]:
            if st.button("Mark resolved", key=f"review_resolve_{selected_review_id}"):
                repository.resolve_review_item(selected_review_id)
                st.success(f"Resolved review item {selected_review_id}.")
                st.rerun()


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


def summarize_review_row(row) -> dict[str, str | None]:
    payload = json.loads(row["payload_json"])
    return {
        "review_id": row["review_id"],
        "drawing_number": row["drawing_number"],
        "weld_id": row["weld_id"],
        "item_type": row["item_type"],
        "field": payload.get("field"),
        "message": payload.get("message"),
        "resolved_at": row["resolved_at"],
    }


def format_review_option(review_id: str, reviews) -> str:
    row = next(row for row in reviews if row["review_id"] == review_id)
    scope = row["drawing_number"] or row["document_id"]
    if row["weld_id"]:
        scope = f"{scope}/{row['weld_id']}"
    state = "resolved" if row["resolved_at"] else "open"
    return f"{review_id} | {scope} | {row['item_type']} | {state}"


def configured_review_timeout_seconds(review_service: ReviewService) -> int:
    return int(review_service.vlm_engine.config.vlm.review_request_timeout_sec)


def render_drawing_health_summary(st, drawing_row, weld_rows, review_rows, photo_rows) -> None:
    metric_columns = st.columns(4)
    completed_welds = sum(1 for row in weld_rows if row["status"] in {"done", "completed"})
    pending_inspection = sum(1 for row in weld_rows if row["inspection_status"] in {"pending", "not_checked"})
    metric_columns[0].metric("Stored welds", len(weld_rows))
    metric_columns[1].metric("Completed welds", completed_welds)
    metric_columns[2].metric("Pending inspection", pending_inspection)
    metric_columns[3].metric("Open review items", len(review_rows))

    if drawing_row and drawing_row["drawing_type"]:
        st.caption(f"Drawing type: {drawing_row['drawing_type']}")
    if drawing_row and drawing_row["drawing_number"] == drawing_row["document_id"]:
        st.warning(
            "This drawing is still using document_id as the drawing number fallback. "
            "Title-block recognition likely needs manual confirmation."
        )
    if drawing_row and not bool(drawing_row["supported"]):
        st.error(
            f"This drawing was rejected for automatic parsing as `{drawing_row['drawing_type'] or 'unknown'}`. "
            f"Reason: {drawing_row['classification_reason'] or 'drawing_type_unknown'}. "
            "Manual weld intake is recommended."
        )
    if len(weld_rows) == 0:
        st.warning(
            "No welds were detected for this drawing. Please verify the source image and use manual weld intake if needed."
        )
    if len(photo_rows) > 0:
        st.caption(f"Linked photos for this drawing: {len(photo_rows)}")


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
