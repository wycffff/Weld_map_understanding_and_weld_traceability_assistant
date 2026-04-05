# Project Retrospective

## 1. Starting Point

The project began as a customer-facing idea described in specification documents rather than as an existing codebase.

At the start, the major uncertainties were:

- drawing formats were highly inconsistent
- real sample count was small
- OCR accuracy would vary widely by sheet style
- the current local VLM runtime was weak and slow
- the final target environment was expected to be stronger than the current development machine

Because of that, the project was intentionally framed as a modular engineering exercise rather than a single-model demo.

## 2. Initial Strategy

The first stable decision was:

- `OCR primary, VLM secondary`

That rule shaped everything that followed.

Why this mattered:

- weld IDs, drawing numbers, BOM tags, quantities, and materials require exact transcription
- small local VLMs can help with routing, interpretation, and fallback reasoning, but are not reliable enough to be the primary authority for exact fields
- uncertain outputs needed to become `needs_review` items, not silent forced values

The second stable decision was to build around explicit contracts:

- `InputDocument`
- `PreprocessedDocument`
- `LayoutPlan`
- `OCRResult`
- `VLMResult`
- `StructuredDrawing`

That contract boundary made it possible to replace modules independently without rewriting the full pipeline.

## 3. How The Project Was Built

### Phase A: Modular skeleton

The project first became a runnable OCR pipeline:

- `M1` ingestion
- `M2` preprocessing
- `M3` ROI planning
- `M4` OCR extraction
- `M6` fusion

This phase produced schema-valid structured output without depending on a database or VLM.

### Phase B: Persistence and demo usability

The next step turned the parser into a traceability application:

- `M7` SQLite persistence
- `M9` export
- `M10` Streamlit UI

At that point the system could:

- upload a drawing
- parse it
- store the result
- search stored drawings
- export JSON and CSV

### Phase C: Review-first operations

Once real drawings entered the loop, missing or uncertain weld rows became a normal case rather than an exception.

That led to:

- manual weld registration
- bulk missing-weld intake
- review queue resolution and reopening
- append-only event logging
- weld photo evidence linking
- weld status and inspection status workflows

This was the point where the system became operationally useful even when parsing was incomplete.

### Phase D: Classification before detailed parsing

As more drawing types appeared, the pipeline needed a routing step before detailed ROI extraction.

That led to a dedicated drawing-classification stage based on OCR keywords.

It enabled:

- `simple_spool`
- `fabrication_weld_map`
- `pipeline_isometric`
- `dual_isometric`
- `weld_log`

It also created a clean reject/manual path for unsupported or uncertain sheets.

### Phase E: Bounded M5 integration

`M5` started as an interface and later became a real bounded helper.

Instead of using the VLM as a free-form parser, it was constrained to tasks such as:

- title-block fallback
- weld-list assistance
- weld-location descriptions
- review-item explanation

Hard timeouts and output caps were added because the available local Ollama runtime was CPU-bound.

This kept the architecture aligned with the customer direction without sacrificing system stability.

### Phase F: Evaluation and hardening

Once the first few real samples were stable, the project added:

- a curated local ground-truth file
- a benchmark command
- per-sample reports
- micro-aggregated metrics

That changed progress from "it seems better" to "we can measure what improved and what regressed."

## 4. Key Pipelines That Exist Today

### Parsing pipeline

```text
input file
  -> ingestion
  -> preprocessing
  -> preview OCR
  -> drawing classification
  -> ROI planning / routing
  -> OCR extraction
  -> optional bounded VLM assistance
  -> fusion + normalization + review items
  -> structured output
```

### Operational traceability pipeline

```text
structured drawing
  -> SQLite persistence
  -> UI search / inspection
  -> manual weld intake if needed
  -> status updates
  -> inspection updates
  -> photo evidence linking
  -> append-only event history
  -> export
```

### Evaluation pipeline

```text
sample drawing
  -> parse
  -> compare against local ground truth
  -> per-sample report
  -> aggregate metrics
```

## 5. What We Learned From Real Samples

### 1.jpg

This compact spool card was useful for the first end-to-end parsing loop.

It taught us:

- OCR-first extraction works for simple drawings
- not every labeled object on the page is a weld
- explicit ground truth matters because a valve/material tag can look like a weld candidate

### 2.jpeg / 6.jpeg

These fabrication sheets exposed BOM and weld-box normalization challenges.

They drove:

- semantic BOM column alignment
- weld-box extraction
- duplicate sample handling

### 3.png

This pipeline isometric drawing showed that weld-list based drawings behave differently from distributed weld-label drawings.

It drove:

- dedicated `pipeline_isometric` classification
- welding-list logic
- review-first numeric weld inference

### 4.webp

This low-resolution stacked isometric sheet showed that some inputs should not be "forced" into fake confidence.

It reinforced:

- explicit fallback
- manual intervention paths
- honest metric exclusion when truth quality is not good enough

### 11.png

This clean spool drawing became the most important late-stage benchmark because it exposed a missing capability:

- alphabetic weld IDs
- grouped BOM structure
- imperial quantity formatting

Adding `11.png` caused the BOM benchmark to drop sharply at first, which was useful because it revealed a real structural weakness rather than hiding it.

### hjrz.webp

This WELD LOG style sample changed the project in two ways:

- it became a target export format
- it became a UI reference for a more operator-friendly weld workspace

## 6. How Progress Was Measured

The main benchmark metrics were aligned with the original target intent:

- drawing number accuracy
- drawing type accuracy
- weld precision
- weld recall
- BOM field accuracy

The important turning point was not only reaching high numbers, but making the numbers meaningful:

- first by adding ground truth
- then by adding more diverse samples
- then by accepting temporary metric drops as evidence of real coverage expansion

Example of this process:

- early small-sample benchmark numbers looked unrealistically perfect
- adding `11.png` dropped BOM accuracy and exposed grouped-BOM weakness
- grouped-BOM fixes then raised the metric again to an honest stronger baseline

## 7. Final Measured State

On the currently available labeled local regression set:

- `drawing_number_accuracy = 1.0`
- `drawing_type_accuracy = 1.0`
- `weld_precision_micro = 1.0`
- `weld_recall_micro = 1.0`
- `bom_field_accuracy_micro = 0.8154`

Those results mean:

- the main acceptance goals are satisfied on the current local benchmark
- the system is no longer only a parser prototype
- it is a usable local traceability workflow with measurable quality

## 8. Why The Current State Is A Good Pause Point

The project is at a natural milestone because:

- all major modules `M1-M10` are implemented and running
- the benchmark meets the practical targets on the available sample set
- the UI supports operational review and traceability workflows
- the remaining bottlenecks now depend more on more customer drawings and stronger VLM runtime options than on missing basic architecture

## 9. What Is Still Not Finished

The project is in a good close-out state, not in a "nothing left to improve" state.

Current known limitations:

- broader customer validation still needs more real images
- `pipeline_isometric` weld-list extraction still needs stronger true cell-level parsing on harder sheets
- low-resolution stacked pages still rely on review-first/manual flows
- local bounded M5 is architecturally useful but runtime-limited on the current machine

## 10. Recommended Future Resume Path

When more data or stronger hardware becomes available, the clean restart path is:

1. add new labeled customer samples
2. keep the current benchmark and expand the truth set
3. harden the remaining weld-list parser for more difficult pipeline drawings
4. improve domain-specific BOM normalization
5. test the same bounded M5 architecture with a stronger 24GB-class local model or a cloud VLM adapter

That path preserves the current architecture and extends it, rather than replacing it.
