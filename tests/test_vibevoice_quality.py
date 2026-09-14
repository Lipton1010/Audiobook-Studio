import unittest

from app.vibevoice_quality import assess


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


if __name__ == "__main__":
    unittest.main()
