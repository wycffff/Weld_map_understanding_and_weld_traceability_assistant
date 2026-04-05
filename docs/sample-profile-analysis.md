# Sample Profile Analysis

## Current Real Samples

- `samples/real/1.jpg`
  - Profile: `simple_spool`
  - Role: first compact spool-card baseline
  - Main truth anchors: `4-N1-101`, `W01`

- `samples/real/2.jpeg`
  - Profile: `fabrication_weld_map`
  - Role: main fabrication-sheet BOM and weld-box benchmark
  - Main truth anchors: `C-52`, `W01..W11`, 11 labeled BOM rows

- `samples/real/3.png`
  - Profile: `pipeline_isometric`
  - Role: numeric weld-list / welding-map benchmark
  - Main truth anchors: `N-30-P-22009-AA1`, welds `1..17`

- `samples/real/4.webp`
  - Profile: `dual_isometric`
  - Role: low-resolution fallback and review-first benchmark
  - Main truth anchors: repeated `ISOMETRIC DRAWING`, low OCR trust

- `samples/real/6.jpeg`
  - Profile: `fabrication_weld_map`
  - Role: duplicate-stability sample
  - Note: byte-identical to `2.jpeg`

- `samples/real/11.png`
  - Profile: `simple_spool`
  - Role: clean grouped-BOM and alphabetic-weld benchmark
  - Main truth anchors: `SG-3-HWS-SP-0001A`, welds `A..G`, 8 grouped BOM rows

- `samples/real/hjrz.webp`
  - Profile: `weld_log`
  - Role: WELD LOG import/export and UI reference
  - Main truth anchors: WELD LOG layout, weld rows `1..9`

## Current Parsing Strategy

The system now uses:

- OCR preview classification before detailed ROI planning
- profile-based ROI routing
- OCR-first extraction with review-first conflict handling
- bounded VLM only as secondary assistance
- manual and bulk weld-intake paths for incomplete recognition

Current supported profiles:

- `simple_spool`
- `fabrication_weld_map`
- `pipeline_isometric`
- `dual_isometric`
- `weld_log`

## Ground Truth Snapshot

Current machine-readable truth set:

- [eval/sample_ground_truth.json](../eval/sample_ground_truth.json)

Included local truth today:

- `1.jpg`
  - drawing number: `4-N1-101`
  - drawing type: `simple_spool`
  - weld IDs: `W01`
  - note: `F-9-4` is not treated as a weld

- `2.jpeg`
  - drawing number: `C-52`
  - drawing type: `fabrication_weld_map`
  - weld IDs: `W01..W11`
  - field-level BOM truth: 11 rows

- `3.png`
  - drawing number: `N-30-P-22009-AA1`
  - drawing type: `pipeline_isometric`
  - weld IDs: `1..17`

- `4.webp`
  - drawing type: `dual_isometric`
  - excluded from quantitative metrics because the currently available source is too low-resolution for reliable truth labeling

- `6.jpeg`
  - duplicate of `2.jpeg`
  - excluded from aggregate metrics

- `11.png`
  - drawing number: `SG-3-HWS-SP-0001A`
  - drawing type: `simple_spool`
  - weld IDs: `A..G`
  - field-level BOM truth: 8 rows

`hjrz.webp` is currently used as a functional reference sample for `weld_log` import/export behavior and routing, but it is not yet part of the field-level aggregate benchmark.

## Current Evaluation Snapshot

Latest aggregate metrics on the included labeled benchmark set:

- `drawing_number_accuracy = 1.0`
- `drawing_type_accuracy = 1.0`
- `weld_precision_micro = 1.0`
- `weld_recall_micro = 1.0`
- `bom_field_accuracy_micro = 0.8154`

Reference:

- [data/final/evaluation_report.json](../data/final/evaluation_report.json)

## Sample-By-Sample Status

- `1.jpg`
  - drawing number and weld truth are matched
  - BOM remains review-heavy and is not part of field-level truth scoring

- `2.jpeg`
  - drawing number matched
  - weld IDs matched
  - BOM row recall is `1.0`
  - BOM field accuracy is `0.9091`

- `3.png`
  - drawing number matched
  - weld IDs `1..17` matched
  - current route is still more brittle than desired because harder cases still depend on weld-list fallback logic

- `4.webp`
  - still handled as a review-first low-resolution case
  - intentionally excluded from quantitative scoring

- `6.jpeg`
  - remains a duplicate-stability sample only

- `11.png`
  - drawing number matched
  - alphabetic weld IDs `A..G` matched
  - grouped BOM now parses as 8 rows
  - current BOM field accuracy is `0.7188`
  - this sample was the key trigger for the grouped-BOM fix

- `hjrz.webp`
  - now classifies as `weld_log`
  - table-only route is active
  - functional output contains 9 weld rows

## Most Important Lessons From The Sample Set

1. Small sample sets can make metrics look better than reality.
2. Adding a new realistic sample that hurts metrics is useful because it exposes missing capability.
3. Grouped BOMs, alphabetic weld IDs, and weld-log layouts are materially different formats and need explicit routing or normalization logic.
4. Low-resolution sheets should prefer explicit fallback and manual guidance over false confidence.

## Next Resume Targets

If the project is resumed later with more customer drawings, the highest-value next steps are:

1. expand the labeled truth set
2. harden `pipeline_isometric` weld-list cell parsing
3. improve domain-specific BOM normalization for fabrication and spool variants
4. test the same bounded M5 architecture with a stronger local or cloud VLM runtime
