# Weld Map Understanding and Weld Traceability Assistant

This project converts weld maps, spool drawings, fabrication sheets, and weld-log style records into structured traceability data that can be reviewed, stored, updated, and exported locally.

It is implemented as a modular Python application with OCR-first extraction, optional bounded VLM assistance, SQLite persistence, a CLI, and a Streamlit demo UI.

## Final Project Status

On the currently available labeled local regression set, the main acceptance targets are met or exceeded:

- `drawing_number_accuracy = 1.0`
- `drawing_type_accuracy = 1.0`
- `weld_precision_micro = 1.0`
- `weld_recall_micro = 1.0`
- `bom_field_accuracy_micro = 0.8154`

Reference report:

- [data/final/evaluation_report.json](data/final/evaluation_report.json)

Important scope note:

- These metrics are based on the currently available curated local truth set.
- The project is in a good close-out state for this sample set, but broader customer validation still depends on more real drawings and stronger VLM runtime options.

## What The System Does

- Ingest raw drawing files and assign stable `document_id` values.
- Generate OCR-friendly image variants.
- Classify drawings before detailed ROI planning.
- Route supported and unsupported drawing types differently.
- Extract title-block data, BOM tables, weld lists, weld labels, and review evidence.
- Fuse OCR and optional bounded VLM outputs with review-first conflict handling.
- Store drawings, welds, BOM rows, review items, traceability events, and photo evidence in SQLite.
- Let users update weld status and inspection progress from the UI.
- Export JSON, CSV, and WELD LOG style CSV deliverables.

## Design Principles

- `OCR primary, VLM secondary`
- `review-first rather than hard-forcing uncertain values`
- `modular contracts instead of shared mutable state`
- `bounded local AI tasks instead of open-ended generation`
- `manual intake and manual review as first-class workflow paths`

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

See [docs/module-spec-summary.md](docs/module-spec-summary.md) for the implementation-oriented English summary of the original specification.

## Implemented End-to-End Pipeline

```text
Input file
  -> M1 ingestion
  -> M2 preprocessing
  -> preview OCR
  -> drawing classification
  -> M3 ROI planning / routing
  -> M4 OCR extraction
  -> optional bounded M5 assistance
  -> M6 fusion + normalization + review items
  -> M7 SQLite persistence
  -> M8 progress / inspection / photo events
  -> M9 exports
  -> M10 UI / CLI workflows
```

## Supported Drawing Types

Currently supported in the main pipeline:

- `simple_spool`
- `fabrication_weld_map`
- `pipeline_isometric`
- `dual_isometric`
- `weld_log`

Current behavior for unsupported or uncertain inputs:

- explicit classification warning
- review-first path
- manual weld-intake path in the UI instead of silent failure

## Sample Set

Current local regression samples:

- [samples/real/1.jpg](samples/real/1.jpg)
- [samples/real/2.jpeg](samples/real/2.jpeg)
- [samples/real/3.png](samples/real/3.png)
- [samples/real/4.webp](samples/real/4.webp)
- [samples/real/6.jpeg](samples/real/6.jpeg)
- [samples/real/11.png](samples/real/11.png)
- [samples/real/hjrz.webp](samples/real/hjrz.webp)

Ground truth:

- [eval/sample_ground_truth.json](eval/sample_ground_truth.json)

Analysis:

- [docs/sample-profile-analysis.md](docs/sample-profile-analysis.md)

## Current Highlights

- Modular OCR-first architecture with typed contracts.
- Drawing classification before detailed ROI planning.
- Profile-specific weld ID handling, including alphabetic, numeric, and weld-log style IDs.
- BOM semantic alignment with fuzzy header matching and grouped-BOM handling.
- Review queue persistence with resolve / reopen flow.
- Manual and bulk weld intake for drawings with missing weld rows.
- Weld status, inspection status, photo evidence, and append-only event history.
- WELD LOG CSV export and WELD LOG style UI workspace.
- Optional bounded M5 support for title-block fallback, weld-list assistance, weld-location descriptions, and review guidance.

## Current M5 Status

`M5` is implemented and integrated, but intentionally bounded:

- It is used for small, explicit tasks only.
- It participates in fusion as secondary assistance, not as the primary source of truth.
- It has hard timeouts and output caps.
- It is still disabled by default for full runs on the current machine because the available local Ollama runtime is CPU-bound.

This keeps the architecture aligned with the original customer direction while remaining practical on the current hardware.

## UI Capabilities

The Streamlit app supports:

- uploading and parsing drawings
- optional per-run VLM assistance
- normalized search by drawing number, spool name, and document ID
- WELD LOG style weld-traceability workspace
- manual weld registration and bulk missing-weld intake
- weld status and inspection updates
- weld photo uploads and evidence linking
- review queue resolution and reopening
- bounded review-assistant calls
- JSON / CSV / WELD LOG export

## CLI Commands

- `parse`: process one drawing
- `parse-batch`: process all drawings in a directory
- `evaluate-samples`: run the curated local benchmark
- `init-db`: initialize SQLite schema
- `export`: export stored JSON and CSV for one drawing
- `write-schema`: write the current JSON schema

`parse` and `parse-batch` also support `--use-vlm` for selective M5 runs.

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

### 2. Initialize the database

```powershell
python weld_cli.py init-db
```

### 3. Parse one drawing

```powershell
python weld_cli.py parse --input samples\real\1.jpg --persist --overwrite --output data\final\sample_output.json
```

### 4. Run the current benchmark

```powershell
python weld_cli.py evaluate-samples --input-dir samples\real --ground-truth eval\sample_ground_truth.json --output data\final\evaluation_report.json
```

### 5. Launch the UI

```powershell
streamlit run app.py
```

## Configuration

Main runtime config:

- [config/config.yaml](config/config.yaml)

Key fields:

- `layout.mode`
- `layout.weld_id_patterns`
- `ocr.engine`
- `vlm.enabled`
- `vlm.mode`
- `vlm.max_tasks_per_document`
- `vlm.task_max_output_tokens`
- `vlm.request_timeout_sec`
- `vlm.review_request_timeout_sec`
- `database.path`
- `export.output_dir`

## Testing

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

Current automated coverage includes:

- drawing classification
- BOM mapping and grouped-BOM handling
- weld-list parsing and weld-ID normalization
- OCR/VLM fusion behavior
- repository overwrite and search behavior
- progress and photo-linking workflows
- review-service behavior
- service smoke coverage

## Known Limitations

- The benchmark is still limited by available customer-grade drawings.
- `pipeline_isometric` weld-list parsing still needs stronger true cell-level extraction on harder samples.
- Low-resolution stacked isometric pages still fall back to review-first/manual paths.
- The current local M5 runtime is useful for bounded tasks, but not a substitute for a stronger 24GB-class local model or a cloud VLM adapter.

## Repository Structure

```text
.
|- config/
|  |- config.yaml
|  `- roi_template_default.json
|- docs/
|- eval/
|- samples/
|  `- real/
|- schemas/
|- src/weld_assistant/
|- tests/
|- app.py
`- weld_cli.py
```
