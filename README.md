# Weld Map Understanding and Weld Traceability Assistant

This project turns weld maps, spool drawings, and fabrication sheets into structured traceability data that can be reviewed, stored, updated, and exported.

The system is being built as a modular Python application with OCR-first extraction, optional VLM assistance, SQLite persistence, and a Streamlit demo UI.

## What The Project Does

- Ingest drawing files and assign stable `document_id` values.
- Preprocess images into OCR-friendly variants.
- Split drawings into semantic regions such as title blocks, BOM tables, isometric views, and weld labels.
- Extract structured fields from OCR output.
- Normalize and fuse drawing data, BOM items, and weld identifiers.
- Store results in SQLite for later review and progress tracking.
- Export JSON and CSV deliverables.
- Provide a lightweight web UI for upload, search, review, and export.

## Design Principles

- OCR is the primary source of truth for exact fields.
- VLM support is optional and used only for bounded semantic assistance.
- Modules communicate through explicit contracts and can be replaced independently.
- Uncertain fields go to `needs_review` instead of being silently forced.
- Every stage should remain runnable even when advanced modules are disabled.

## Module Map

- `M1` Input / Ingestion
- `M2` Preprocessing
- `M3` Layout & ROI Planner
- `M4` OCR Extraction
- `M5` VLM Understanding
- `M6` Fusion & Parsing
- `M7` Traceability Data Model
- `M8` Progress & Photo Linking
- `M9` Export / Integration
- `M10` UI / Demo

Shared contracts:

- `InputDocument`
- `PreprocessedDocument`
- `LayoutPlan`
- `OCRResult`
- `VLMResult`
- `StructuredDrawing`

See [docs/module-spec-summary.md](docs/module-spec-summary.md) for the English implementation summary derived from the original specification.

## Current Status

Implemented today:

- Modular project structure and typed contracts.
- Manual ROI flow with profile-based layout selection.
- OCR adapters with `RapidOCR` as the default local path and `PaddleOCR` retained as an optional adapter.
- Fusion logic for drawing fields, weld identifiers, and partially normalized BOM extraction.
- Bounded M5 integration for title-block fallback, weld-list assistance, and weld-location descriptions.
- Bounded M5 review-assistant flow for review queue explanation and action suggestions.
- SQLite repository, review queue persistence, and export services.
- Traceability actions for weld status, inspection status, photo evidence, and append-only event history.
- Streamlit demo UI.
- CLI support for single-file parsing, batch parsing, schema generation, DB initialization, and exports.
- Real-sample regression coverage with four drawing styles.

Current document profiles:

- `simple_spool`
- `fabrication_weld_sheet`
- `welding_map_sheet`
- `dual_isometric_sheet`

See [docs/sample-profile-analysis.md](docs/sample-profile-analysis.md) for the current sample set and parsing baseline.

## Module Status

- `M1` Input / Ingestion: running
- `M2` Preprocessing: running
- `M3` Layout & ROI Planner: running with manual templates and profile-based selection; auto mode is still limited
- `M4` OCR Extraction: running with `RapidOCR` by default
- `M5` VLM Understanding: integrated as bounded assistance for title-block fallback, weld-list extraction, weld-location descriptions, and review-queue guidance; still disabled by default for full runs because the current local Ollama runtime is CPU-bound
- `M6` Fusion & Parsing: running with OCR-first / review-first rules
- `M7` Traceability Data Model: running on SQLite
- `M8` Progress & Photo Linking: running for status updates, inspection updates, photo uploads, and event logging
- `M9` Export / Integration: running for JSON / CSV export
- `M10` UI / Demo: running for upload, search, review, export, and traceability actions

## Repository Structure

```text
.
├── config/
│   ├── config.yaml
│   └── roi_template_default.json
├── docs/
├── samples/
│   └── real/
├── schemas/
├── src/weld_assistant/
├── tests/
├── app.py
└── weld_cli.py
```

## Real Samples

The repository currently includes these real drawing samples:

- [samples/real/1.jpg](samples/real/1.jpg)
- [samples/real/2.jpeg](samples/real/2.jpeg)
- [samples/real/3.png](samples/real/3.png)
- [samples/real/4.webp](samples/real/4.webp)

These samples are used as the current regression set for layout classification, OCR behavior, BOM extraction, weld extraction, and database import.

## Quick Start

### 1. Install dependencies

```powershell
python -m pip install -r requirements.txt
python -m pip install streamlit rapidocr_onnxruntime
```

Optional OCR adapter:

```powershell
python -m pip install paddleocr paddlepaddle
```

### 2. Generate the schema

```powershell
python weld_cli.py write-schema --output schemas\structured_drawing.schema.json
```

### 3. Initialize the database

```powershell
python weld_cli.py init-db
```

### 4. Parse one drawing

```powershell
python weld_cli.py parse --input samples\real\1.jpg --persist --overwrite --output data\final\sample_output.json
```

### 5. Parse the full sample set

```powershell
python weld_cli.py parse-batch --input-dir samples\real --persist --overwrite --output data\final\batch_summary.json
```

### 6. Launch the web UI

```powershell
streamlit run app.py
```

## UI Notes

The web UI supports:

- Uploading and processing a new drawing.
- Choosing whether to use VLM assistance for a specific run.
- Manually registering a weld when OCR/VLM did not create one yet.
- Bulk-registering missing weld IDs for drawings that are already stored in the database.
- Previewing generated ROIs.
- Searching existing reports by drawing number, spool name, or document ID.
- Updating weld status and inspection status.
- Uploading weld photos and linking them to stored weld IDs.
- Viewing append-only event history and linked photo evidence per weld.
- Exporting JSON and CSV outputs from stored results.
- Reviewing unresolved items from the review queue and resolving or reopening them.
- Running a bounded M5 review assistant on a selected review item.

Search is normalized so queries like `C52`, `c-52`, or partial drawing fragments can still return matches.
VLM assistance is visible in the UI status banner and can be enabled per run. On the current machine the local Ollama runtime is CPU-bound, so selective use is recommended.
When a drawing has no stored weld rows yet, or when some welds are still missing after parsing, the UI exposes a manual weld-intake flow so users can bulk-register weld IDs, skip already-existing IDs, and then continue with photos and progress events.
Weld identity is scoped by `drawing_number + weld_id`, so `W01` may exist on multiple drawings without conflict while remaining unique inside each drawing.
The review assistant now uses a hard timeout for local Ollama calls so difficult requests fail fast instead of blocking the UI indefinitely.

## CLI Commands

- `parse`: process a single drawing
- `parse-batch`: process all files in a directory
- `init-db`: initialize SQLite schema
- `export`: export stored JSON and CSV for a drawing
- `write-schema`: write the current JSON schema to disk

`parse` and `parse-batch` also support `--use-vlm` for selective M5 runs.

## Configuration

Main runtime config: [config/config.yaml](config/config.yaml)

Important fields:

- `layout.mode`: `manual | auto`
- `layout.weld_id_pattern`: weld ID regex
- `ocr.engine`: default OCR engine
- `vlm.enabled`: enable or disable VLM assistance
- `vlm.mode`: `review_only | always`
- `vlm.max_tasks_per_document`: cap VLM task count per drawing
- `vlm.max_output_tokens`: limit local Ollama output size per task
- `vlm.request_timeout_sec`: hard timeout for each bounded Ollama call
- `database.path`: SQLite database path
- `export.output_dir`: export directory

## Testing

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

## Current Batch Baseline

Latest local batch summary:

- `1.jpg` -> drawing `4-N1-101`, `4` BOM rows, `1` weld
- `2.jpeg` -> drawing `C-52`, `6` BOM rows, `11` welds
- `3.png` -> drawing `N-30-P-22009-AA1`, `3` BOM rows, `17` numeric welds inferred from the welding list
- `4.webp` -> low-resolution fallback, review-first

This baseline is intentionally incomplete. The current focus is reliable modular parsing with reviewable outputs, then continued hardening toward customer-grade accuracy across multiple drawing styles.

## Next Priorities

- Replace review-first `WELDING LIST` row-count inference with cell-level weld-list parsing.
- Improve parts-list normalization so more `C-52` rows keep usable descriptions and materials.
- Expand the M5 task planner for bigger local models on 24GB-class GPUs while keeping the current small-model prompts bounded and short.
- Strengthen low-resolution fallback for stacked isometric pages.
- Add more evaluation metrics and regression outputs for real samples.
