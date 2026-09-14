import unittest

from app.vibevoice_units import choose_repair_unit, parent_quality, repair_units


def parent(text, index=3, heading=False):
    value = {"index": index, "identity": "parent-identity", "text": text}
    if heading:
        value["heading"] = text
    return value


class VibeVoiceUnitsTests(unittest.TestCase):
    def test_preserves_normalized_prose_and_compatible_fields(self):
        text = "  First sentence.\nSecond sentence!  Third sentence? "
        source = parent(text)
        units = repair_units(source, target_words=2, max_words=10)
        self.assertEqual(" ".join(unit["text"] for unit in units), "First sentence. Second sentence! Third sentence?")
        self.assertEqual([unit["index"] for unit in units], [30000, 30001, 30002])
        self.assertTrue(all(unit["speaker_text"] == "Speaker 0: " + unit["text"] for unit in units))
        self.assertTrue(all(unit["parent_index"] == 3 for unit in units))

    def test_dialogue_and_common_abbreviation_stay_in_source_order(self):
        text = 'Dr. Vale said, "Wait here." Then she left. The value was 3.14. "Do not follow," he called.'
        units = repair_units(parent(text), target_words=4, max_words=8)
        self.assertEqual(" ".join(unit["text"] for unit in units), text)
        self.assertEqual(units[0]["text"], 'Dr. Vale said, "Wait here."')

    def test_oversize_sentence_uses_existing_safe_splitter(self):
        text = " ".join(f"word{index}" for index in range(181))
        units = repair_units(parent(text), target_words=120, max_words=180)
        self.assertEqual([len(unit["text"].split()) for unit in units], [180, 1])
        self.assertEqual(" ".join(unit["text"] for unit in units), text)

    def test_headings_remain_whole(self):
        text = "A Heading With More Than Three Words"
        units = repair_units(parent(text, heading=True), target_words=2, max_words=3)
        self.assertEqual([unit["text"] for unit in units], [text])

    def test_unit_identity_changes_with_parent_text_or_ordinal(self):
        text = "Same words. Same words."
        units = repair_units(parent(text), target_words=2, max_words=2)
        changed_parent = dict(parent(text)); changed_parent["identity"] = "other-parent"
        changed_text = repair_units(parent("Changed words. Same words."), target_words=2, max_words=2)[0]["identity"]
        self.assertNotEqual(units[0]["identity"], units[1]["identity"])
        self.assertNotEqual(units[0]["identity"], repair_units(changed_parent, target_words=2, max_words=2)[0]["identity"])
        self.assertNotEqual(units[0]["identity"], changed_text)

    def test_parent_gate_uses_concatenated_unit_transcripts(self):
        source = parent("one two three four five six. seven eight nine ten eleven twelve.")
        units = repair_units(source, target_words=6, max_words=12)
        reports = [{"unit_index": unit["unit_index"], "transcript": unit["text"]} for unit in units]
        reports[0]["transcript"] = "one two"
        result = parent_quality(source, reports)
        self.assertFalse(result["ok"])
        self.assertGreaterEqual(result["missing_words"], 4)


    def test_parent_quality_uses_explicit_validated_unit_manifest(self):
        source = parent("one two. three four. five six. seven eight.")
        units = repair_units(source, target_words=2, max_words=2)
        reports = [{"unit_index": unit["unit_index"], "transcript": unit["text"]} for unit in units]
        self.assertTrue(parent_quality(source, reports, units)["ok"])
        stale = [dict(unit) for unit in units]
        stale[0]["identity"] = "wrong"
        with self.assertRaisesRegex(ValueError, "identity"):
            parent_quality(source, reports, stale)

    def test_choose_repair_unit_prefers_largest_then_first(self):
        units = repair_units(parent("one two. three four. five six."), target_words=2, max_words=2)
        reports = [
            {"unit_index": 0, "transcript": units[0]["text"], "missing_words": 1, "inserted_words": 1, "differences": [{}]},
            {"unit_index": 1, "transcript": units[1]["text"], "missing_words": 3, "inserted_words": 0, "differences": [{}]},
            {"unit_index": 2, "transcript": units[2]["text"], "missing_words": 3, "inserted_words": 0, "differences": [{}]},
        ]
        self.assertEqual(choose_repair_unit(units, reports)["unit_index"], 1)
        self.assertEqual(choose_repair_unit(units, reports, exclude={1})["unit_index"], 2)
        with self.assertRaisesRegex(ValueError, "no repairable"):
            choose_repair_unit(units, reports, exclude={0, 1, 2})
        for report in reports:
            report.update(missing_words=0, inserted_words=0, differences=[])
        with self.assertRaisesRegex(ValueError, "no repairable"):
            choose_repair_unit(units, reports)


if __name__ == "__main__":
    unittest.main()
