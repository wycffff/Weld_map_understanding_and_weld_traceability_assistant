from __future__ import annotations

import unittest

from weld_assistant.contracts import OCRToken
from weld_assistant.modules.ocr import build_table_from_tokens


class TableBuilderTest(unittest.TestCase):
    def test_build_table_infers_missing_columns_from_body_rows(self) -> None:
        tokens = [
            OCRToken(text="PARTSLIST", bbox=[420, 10, 560, 28], confidence=0.99, roi_id="parts_list"),
            OCRToken(text="ITBM", bbox=[20, 40, 70, 58], confidence=0.95, roi_id="parts_list"),
            OCRToken(text="PARTNUMBER", bbox=[210, 40, 330, 58], confidence=0.95, roi_id="parts_list"),
            OCRToken(text="HEAT_NO", bbox=[760, 40, 840, 58], confidence=0.95, roi_id="parts_list"),
            OCRToken(text="PO_NO", bbox=[900, 40, 970, 58], confidence=0.95, roi_id="parts_list"),
            OCRToken(text="3", bbox=[30, 70, 45, 88], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="1", bbox=[120, 70, 135, 88], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="261-02", bbox=[180, 70, 250, 88], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="NAMEPLATE-30", bbox=[360, 70, 520, 88], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="18C846", bbox=[760, 70, 830, 88], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="6043-00", bbox=[900, 70, 990, 88], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="4", bbox=[30, 100, 45, 118], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="2", bbox=[120, 100, 135, 118], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="265-03", bbox=[180, 100, 250, 118], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="SUPPORTBRACKET", bbox=[360, 100, 560, 118], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="18C847", bbox=[760, 100, 830, 118], confidence=0.94, roi_id="parts_list"),
            OCRToken(text="6044-00", bbox=[900, 100, 990, 118], confidence=0.94, roi_id="parts_list"),
        ]

        table = build_table_from_tokens("parts_list", tokens)

        row_indices = sorted({cell.row for cell in table.cells})
        self.assertEqual(row_indices, [0, 1, 2, 3])

        second_body_row = [cell for cell in table.cells if cell.row == 2]
        text_to_column = {cell.text: cell.col for cell in second_body_row}
        self.assertEqual(len({cell.col for cell in second_body_row}), 5)
        self.assertNotEqual(text_to_column["NAMEPLATE-30"], text_to_column["261-02"])


if __name__ == "__main__":
    unittest.main()
