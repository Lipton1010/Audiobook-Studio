import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from narration_safety import RunawayGenerationError, repair_capped_sequences


class NarrationSafetyTests(unittest.TestCase):
    def test_rows_below_cap_are_unchanged(self):
        calls = []
        original = [[1, 2], [3]]

        repaired = repair_capped_sequences(
            original, 4, lambda row, attempt: calls.append((row, attempt))
        )

        self.assertEqual(repaired, original)
        self.assertEqual(calls, [])

    def test_capped_row_is_retried_in_isolation(self):
        calls = []

        def retry(row, attempt):
            calls.append((row, attempt))
            return [8, 9]

        repaired = repair_capped_sequences([[1, 2, 3, 4], [5]], 4, retry)

        self.assertEqual(repaired, [[8, 9], [5]])
        self.assertEqual(calls, [(0, 1)])

    def test_eos_on_final_step_is_not_misclassified(self):
        repaired = repair_capped_sequences(
            [[1, 2, 3]], 4, lambda *_: self.fail("unexpected retry")
        )
        self.assertEqual(repaired, [[1, 2, 3]])

    def test_repeated_cap_fails_instead_of_emitting_bad_audio(self):
        with self.assertRaisesRegex(RunawayGenerationError, "3 retries"):
            repair_capped_sequences(
                [[1, 2, 3, 4]],
                4,
                lambda *_: [5, 6, 7, 8],
                max_attempts=3,
            )


if __name__ == "__main__":
    unittest.main()
