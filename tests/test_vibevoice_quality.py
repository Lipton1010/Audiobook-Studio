import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import vibevoice_quality as quality
from app.vibevoice_quality import assess, words


class VibeVoiceQualityTests(unittest.TestCase):
    def test_single_word_difference_is_recorded_but_not_a_failure(self):
        report = assess("Synthetic words stay here", "Synthetic word stay here")
        self.assertTrue(report["ok"])
        self.assertTrue(report["differences"])

    def test_large_missing_passage_fails(self):
        report = assess("one two three four five six seven eight", "one two")
        self.assertFalse(report["ok"])
        self.assertEqual(report["major"][0]["kind"], "delete")

    def test_large_nonsource_insertion_fails(self):
        report = assess("one two", "one two three four five six seven eight")
        self.assertFalse(report["ok"])
        self.assertEqual(report["major"][0]["kind"], "insert")

    def test_separated_small_omissions_fail_in_aggregate(self):
        report = assess("one two gap three four gap five six gap", "one gap three gap five gap", major_words=3)
        self.assertFalse(report["ok"])
        self.assertEqual(report["missing_words"], 3)

    def test_unsigned_integer_notation_is_semantically_equivalent(self):
        expected = "zero nineteen twenty one hundred five nine hundred ninety nine one thousand one million one billion one trillion"
        heard = "0 19 20 100 5 999 1,000 1,000,000 1000000000 1000000000000"
        self.assertTrue(assess(expected, heard)["ok"])

    def test_integer_equivalence_fixes_grouped_hundreds_without_relaxing_gate(self):
        expected = "one hundred surveyor's seven hundred marker"
        heard = "100 surveyor 700 marker"
        result = assess(expected, heard)
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing_words"], 1)
        self.assertEqual(result["inserted_words"], 1)

    def test_distinct_signed_decimal_fraction_and_leading_zero_forms_remain_different(self):
        for expected, heard in (("one hundred", "101"), ("minus one hundred", "-100"),
                                ("three fourteen", "3.14"), ("one two", "1/2"), ("one", "01"),
                                ("one thousand five", "1,000.5"), ("one thousand two", "1,000/2"),
                                ("minus one thousand", "-1,000"), ("five", ".5"), ("one hundred", "+100")):
            self.assertTrue(assess(expected, heard)["differences"], (expected, heard))
        self.assertEqual(words("R2D2"), ["r2d2"])

    def test_server_reuses_one_model_for_two_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            requests = [
                {"audio": str(root / "one.wav"), "expected": "one two", "report": str(root / "one.json"), "major_words": 5},
                {"audio": str(root / "two.wav"), "expected": "three four", "report": str(root / "two.json"), "major_words": 5},
            ]
            output = io.StringIO()
            model = object()
            with mock.patch.object(quality, "load_model", return_value=model) as load, \
                 mock.patch.object(quality, "transcribe_with_model", side_effect=["one two", "three four"]) as transcribe, \
                 mock.patch("sys.stdin", io.StringIO("".join(json.dumps(item) + "\n" for item in requests))), \
                 mock.patch("sys.stdout", output):
                quality.serve("synthetic-model")

            replies = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(replies[0], {"ready": True})
            self.assertEqual([reply["ok"] for reply in replies[1:]], [True, True])
            load.assert_called_once_with("synthetic-model")
            self.assertEqual(transcribe.call_count, 2)
            self.assertTrue((root / "one.json").exists())
            self.assertTrue((root / "two.json").exists())


if __name__ == "__main__":
    unittest.main()
