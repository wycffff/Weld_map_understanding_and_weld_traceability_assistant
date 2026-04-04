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
- SQLite repository, review queue persistence, and export services.
- Streamlit demo UI.
- CLI support for single-file parsing, batch parsing, schema generation, DB initialization, and exports.
- Real-sample regression coverage with four drawing styles.

Current document profiles:

- `simple_spool`
- `fabrication_weld_sheet`
- `welding_map_sheet`
- `dual_isometric_sheet`

See [docs/sample-profile-analysis.md](docs/sample-profile-analysis.md) for the current sample set and parsing baseline.

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
- Previewing generated ROIs.
- Searching existing reports by drawing number, spool name, or document ID.
- Exporting JSON and CSV outputs from stored results.
- Reviewing unresolved items from the review queue.

Search is normalized so queries like `C52`, `c-52`, or partial drawing fragments can still return matches.

## CLI Commands

- `parse`: process a single drawing
- `parse-batch`: process all files in a directory
- `init-db`: initialize SQLite schema
- `export`: export stored JSON and CSV for a drawing
- `write-schema`: write the current JSON schema to disk

## Configuration

Main runtime config: [config/config.yaml](config/config.yaml)

Important fields:

- `layout.mode`: `manual | auto`
- `layout.weld_id_pattern`: weld ID regex
- `ocr.engine`: default OCR engine
- `vlm.enabled`: enable or disable VLM assistance
- `database.path`: SQLite database path
- `export.output_dir`: export directory

## Testing

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

## Current Batch Baseline

Latest local batch summary:

- `1.jpg` -> drawing `4-N1-101`, `5` BOM rows, `1` weld
- `2.jpeg` -> drawing `C-52`, `1` BOM row, `11` welds
- `3.png` -> drawing `N-30-P-22009-AA1`, `2` BOM rows, `0` welds
- `4.webp` -> low-resolution fallback, review-first

This baseline is intentionally incomplete. The goal right now is reliable modular parsing with reviewable outputs, then continued hardening toward customer-grade accuracy across multiple drawing styles.

## Next Priorities

- Improve `WELDING LIST` extraction for welding-map sheets.
- Expand parts-list and item-code table mapping.
- Strengthen low-resolution fallback for stacked isometric pages.
- Add more evaluation metrics and regression outputs for real samples.
