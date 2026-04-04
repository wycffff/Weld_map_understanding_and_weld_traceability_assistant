# Sample Data Notes

This document tracks the real sample set currently used for local development and regression testing.

## Current Real Samples

- `samples/real/1.jpg`
- `samples/real/2.jpeg`
- `samples/real/3.png`
- `samples/real/4.webp`

## Origins

- `1.jpg` was provided from the local path `C:\Users\wycff\Pictures\1.jpg`
- `2.jpeg` was provided from the local path `C:\Users\wycff\Pictures\2.jpeg`
- `3.png` was provided from the local path `C:\Users\wycff\Pictures\3.png`
- `4.webp` was provided from the local path `C:\Users\wycff\Pictures\4.webp`

## Why These Samples Matter

- They represent different drawing styles instead of a single template.
- They are used to test layout profile selection.
- They provide the current baseline for OCR, BOM extraction, weld extraction, and DB import behavior.
- They are the main regression set used before adding more samples or ground-truth labels.

## Current Limitations

- The sample set is still small.
- Ground-truth annotations for every weld and every BOM row are not yet complete.
- Some low-resolution pages still fall back to a review-first workflow.

## Recommended Next Steps

1. Add more samples for each document profile.
2. Build ground-truth labels for drawing number, BOM rows, and weld IDs.
3. Track per-sample quality metrics in a structured evaluation report.
4. Use the batch sample set as the minimum regression gate for future parsing changes.
