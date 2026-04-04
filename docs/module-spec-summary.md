# Module Specification Summary

This document is an implementation-oriented English summary derived from `weld_module_spec_v1.1.docx`. It keeps the key architectural decisions, module boundaries, and delivery phases that affect the codebase.

## 1. Spike Conclusions

Early experiments led to four important conclusions:

- A small VLM can understand coarse drawing structure, but it should not be trusted to directly transcribe exact fields.
- Weld IDs and BOM fields such as tag, quantity, and material must stay OCR-led.
- Small models can hallucinate, so strict boundaries are required.
- The project should first establish an OCR baseline, then evaluate VLM as an incremental enhancement.

From that, the system follows these design rules:

- `OCR primary, VLM secondary`
- `VLM only for bounded semantic assistance`
- `ROI-based, multi-step extraction instead of full-image generation`
- `Conflicts go to review; do not hard-force uncertain values`

## 2. Module Responsibilities

### M1 Input / Ingestion

- Accept raw drawing files.
- Generate `document_id`.
- Compute `sha256`.
- Manage raw storage and duplicate detection.

Output: `InputDocument`

### M2 Preprocessing

- Generate image variants such as `clean` and `strong`.
- Preserve preprocessing logs.
- Keep the original file untouched.

Output: `PreprocessedDocument`

### M3 Layout & ROI Planner

- Split the page into semantic ROIs.
- Support `roi_titleblock`, `roi_bom_table`, `roi_isometric`, and `roi_weld_label`.
- Start with manual templates and later expand with automatic layout assistance.

Output: `LayoutPlan`

### M4 OCR Extraction

- Use table-style OCR on BOM-like regions.
- Use token OCR for title blocks, notes, and weld labels.
- Preserve raw OCR text, corrected text, confidence, and position.

Output: `OCRResult`

### M5 VLM Understanding

- Provide bounded semantic help such as ROI classification, disambiguation, and location descriptions.
- Do not directly produce the final authoritative structured record.

Output: `VLMResult`

### M6 Fusion & Parsing

- Merge OCR and VLM results with field-level priorities.
- Normalize weld IDs.
- Align BOM columns and rows.
- Emit `needs_review` items when uncertainty remains.

Output: `StructuredDrawing`

### M7 Traceability Data Model

- Persist `StructuredDrawing` into the database.
- Maintain `drawing`, `weld`, `bom_item`, and `review_queue`.
- Treat weld identity as `drawing_number + weld_id`, not as a globally unique weld code.

### M8 Progress & Photo Linking

- Update weld status.
- Update inspection status.
- Link photos to weld records.
- Keep an append-only event history.

### M9 Export / Integration

- Export full JSON payloads.
- Export CSV summaries.
- Leave replaceable integration points for ERP or downstream systems.

### M10 UI / Demo

- Upload drawings.
- Display extraction results.
- Show review queue items and allow resolve/reopen actions.
- Manage weld status and evidence.
- Support manual or bulk weld intake for missing weld rows on already-scanned drawings.
- Download exported files.

## 3. Shared Data Flow

```text
InputDocument
  -> PreprocessedDocument
  -> LayoutPlan
  -> OCRResult (+ optional VLMResult)
  -> StructuredDrawing
  -> DB entities
  -> UI / Export
```

Modules do not share internal state directly. They communicate only through contract objects.

## 4. Delivery Phases

### Phase 1

- M1 + M2 + M3(manual) + M4 + M6(simplified)
- Goal: produce a schema-valid `StructuredDrawing.json`

### Phase 2

- M7 + M9 + M10(minimal UI)
- Goal: upload, display, persist, and export

### Phase 3

- M3(auto) + M5 + M6(full)
- Goal: automatic layout assistance and VLM semantic augmentation

### Phase 4

- M8 + richer review UI + stronger data model coverage
- Goal: demonstrate an end-to-end traceability loop

### Phase 5

- Batch evaluation, hardening, and error analysis

## 5. Target Metrics

The original specification targets the following quality goals:

- `schema_pass_rate >= 95%`
- `weld_recall >= 90%`
- `weld_precision >= 95%`
- `bom_field_accuracy >= 85%`
- `drawing_field_accuracy >= 90%`

## 6. Current Code Mapping

The current repository maps these concepts into:

- Contracts: `src/weld_assistant/contracts.py`
- Modules: `src/weld_assistant/modules/`
- Services: `src/weld_assistant/services/`
- Persistence: `src/weld_assistant/db/`
- UI: `src/weld_assistant/app.py`
- CLI: `src/weld_assistant/cli.py`

## 7. Current Implementation Status

- `M1` to `M4`: running in the main pipeline.
- `M5`: implemented as an optional Ollama-backed helper and now wired into fusion for title-block fallback, weld-list assistance, weld-location descriptions, and review-queue guidance. The current prompts are intentionally short and ROI-bounded so the small local model stays usable. It remains disabled by default for full runs because the current local Ollama runtime is CPU-bound, and each bounded call now uses a hard timeout. The review assistant uses a separate longer timeout and the UI can raise it further for very slow local inference.
- `M6`: running with OCR-first fusion and review-first conflict handling.
- `M7`: running with SQLite persistence for drawings, welds, BOM rows, and review items.
- `M8`: now running for weld status updates, inspection updates, photo evidence uploads, and append-only event logging.
- `M9`: running for JSON/CSV export, including stored traceability records.
- `M10`: running as a Streamlit demo for upload, search, review, export, weld traceability actions, review resolution, bounded M5 review assistance, and manual/bulk weld intake when recognition misses one or more weld rows.

This summary will evolve as implementation expands, but the OCR-first / review-first design rules above remain the stable baseline.
