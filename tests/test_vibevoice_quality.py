import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import vibevoice_quality as quality
from app.vibevoice_quality import assess, numbered_heading_assessment, words


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

    def test_conservative_compound_spacing_equivalence(self):
        for expected, heard in (("A fernlike pattern.", "A fern like pattern."),
                                ("Sea grass moves.", "Seagrass moves."),
                                ("A fernlike pattern.", "A fern-like pattern."),
                                ("A fern-like pattern.", "A fernlike pattern.")):
            result = assess(expected, heard)
            self.assertTrue(result["ok"], (expected, heard))
            self.assertEqual((result["missing_words"], result["inserted_words"]), (0, 0))
            self.assertTrue(result["differences"][0]["orthographic_equivalent"])

    def test_compound_spacing_rejects_meaning_and_punctuation_changes(self):
        for expected, heard in (("therapist", "the rapist"), ("nowhere", "now here"),
                                ("manslaughter", "mans laughter"), ("fernlike", "fern, like"),
                                ("fernlike", "fern. like"),
                                ("fernlike", "fern"), ("fernlike", "fern like extra")):
            result = assess(expected, heard)
            self.assertTrue(result["differences"], (expected, heard))
            self.assertFalse(any(item.get("orthographic_equivalent") for item in result["differences"]),
                             (expected, heard))

    def test_existing_hyphen_and_number_normalization_remain_equivalent(self):
        self.assertTrue(assess("twenty-one fern-like", "21 fern like")["ok"])

    def test_acknowledgment_spelling_variants_are_exact_one_word_equivalents(self):
        for expected, heard in (
            ("Acknowledgment", "acknowledgement"),
            ("acknowledgement", "ACKNOWLEDGMENT"),
            ("Acknowledgments", "acknowledgements"),
            ("acknowledgements", "ACKNOWLEDGMENTS"),
        ):
            result = assess(expected, heard)
            self.assertTrue(result["ok"], (expected, heard))
            self.assertTrue(result["differences"][0]["orthographic_equivalent"])

    def test_acknowledgment_variants_do_not_hide_real_or_identifier_differences(self):
        adjacent = assess("Acknowledgments Cooke", "acknowledgements Cook")
        self.assertEqual((adjacent["missing_words"], adjacent["inserted_words"]), (2, 2))
        self.assertFalse(any(item.get("orthographic_equivalent") for item in adjacent["differences"]))
        singular_plural = assess("acknowledgment", "acknowledgements")
        self.assertTrue(singular_plural["differences"])
        self.assertFalse(any(item.get("orthographic_equivalent") for item in singular_plural["differences"]))
        identifier = assess("acknowledgment_id", "acknowledgement_id")
        self.assertFalse(any(item.get("orthographic_equivalent") for item in identifier["differences"]))

    def test_acknowledgment_variants_do_not_relax_real_coverage_gate_or_names(self):
        five_missing = assess("acknowledgments one two three four five", "acknowledgements")
        self.assertFalse(five_missing["ok"])
        five_inserted = assess("acknowledgment", "acknowledgement one two three four five")
        self.assertFalse(five_inserted["ok"])
        names = assess("Cooke Ann Marks it's", "Cook Anne Mark's it")
        self.assertTrue(names["differences"])
        self.assertFalse(any(item.get("orthographic_equivalent") for item in names["differences"]))

    def test_numbered_heading_requires_number_and_exact_title_but_accepts_spoken_number_forms(self):
        for heard in ("01: INITIATION", "one Initiation", "zero one Initiation", "1 Initiation"):
            result = numbered_heading_assessment("01: INITIATION", heard)
            self.assertTrue(result["ok"], heard)
            self.assertIn("normalized_heading_assessment", result)
        self.assertFalse(numbered_heading_assessment("03: IMMOLATION", "three Immersion")["ok"])
        self.assertFalse(numbered_heading_assessment("03: IMMOLATION", "Immolation")["ok"])
        self.assertFalse(numbered_heading_assessment("03: IMMOLATION", "three Immolation extra")["ok"])
        self.assertTrue(numbered_heading_assessment("03: ACKNOWLEDGMENTS", "three acknowledgements")["ok"])
        for heard in ("009: NINE", "nine Nine", "zero zero nine Nine"):
            self.assertTrue(numbered_heading_assessment("009: NINE", heard)["ok"], heard)
        for heard in ("zero nine nine Ninety Nine", "zero ninety nine Ninety Nine"):
            self.assertTrue(numbered_heading_assessment("099: NINETY NINE", heard)["ok"], heard)

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
