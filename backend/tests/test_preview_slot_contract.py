from __future__ import annotations

import unittest

from app.core.preview_slot_contract import (
    assert_preview_slot_database_binding,
    expected_preview_db_name,
    normalize_slot_id,
)


class PreviewSlotContractTests(unittest.TestCase):
    def test_normalize_slot_id_accepts_aliases(self) -> None:
        self.assertEqual(normalize_slot_id("preview1"), "preview-1")
        self.assertEqual(normalize_slot_id("preview-2"), "preview-2")

    def test_expected_preview_db_name(self) -> None:
        self.assertEqual(expected_preview_db_name("preview-1"), "app_preview_1")
        self.assertEqual(expected_preview_db_name("preview3"), "app_preview_3")

    def test_assert_binding_accepts_matching_database(self) -> None:
        db_name = assert_preview_slot_database_binding(
            "preview-2",
            "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/app_preview_2",
        )
        self.assertEqual(db_name, "app_preview_2")

    def test_assert_binding_rejects_non_preview_database(self) -> None:
        with self.assertRaisesRegex(ValueError, "non_preview_database_target"):
            assert_preview_slot_database_binding(
                "preview-1",
                "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/builder_control",
            )

    def test_assert_binding_rejects_wrong_slot_database(self) -> None:
        with self.assertRaisesRegex(ValueError, "slot_database_mismatch"):
            assert_preview_slot_database_binding(
                "preview-1",
                "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/app_preview_2",
            )


if __name__ == "__main__":
    unittest.main()
