import unittest

from app import vibevoice_plan as plan


class VibeVoicePlanTests(unittest.TestCase):
    def test_normalization_changes_only_layout_and_spaced_ellipsis(self):
        self.assertEqual(plan.normalize_text("  A\nB . . .  C  "), "A B ... C")

    def test_pack_keeps_small_paragraphs_intact_and_bounds_large_ones(self):
        blocks = [
            {"type": "body", "text": "one two three"},
            {"type": "body", "text": "four five six"},
            {"type": "body", "text": " ".join(f"w{i}" for i in range(12))},
        ]
        packed = plan.pack_passages(blocks, target_words=6, max_words=8)
        self.assertEqual([item["text"] for item in packed[:2]], ["one two three four five six", "w0 w1 w2 w3 w4 w5 w6 w7"])
        self.assertEqual(" ".join(item["text"] for item in packed), "one two three four five six " + " ".join(f"w{i}" for i in range(12)))

    def test_one_giant_sentence_stays_bounded(self):
        text = "Short. " + " ".join(f"w{i}" for i in range(12)) + "."
        packed = plan.pack_passages([{"type": "body", "text": text}], target_words=6, max_words=8)
        self.assertTrue(all(len(item["text"].split()) <= 8 for item in packed))

    def test_plan_identity_invalidates_voice_text_and_runtime(self):
        base = plan.passage_identity("Same words", "a" * 64)
        self.assertNotEqual(base, plan.passage_identity("Other words", "a" * 64))
        self.assertNotEqual(base, plan.passage_identity("Same words", "b" * 64))
        self.assertNotEqual(base, plan.passage_identity("Same words", "a" * 64, {**plan.RUNTIME, "cfg_scale": 3.0}))

    def test_heading_stays_its_own_chapter_passage(self):
        packed = plan.pack_passages([
            {"type": "heading", "text": "Chapter One"},
            {"type": "body", "text": "one two three"},
        ], target_words=10, max_words=20)
        self.assertEqual(packed[0]["heading"], "Chapter One")
        self.assertEqual(packed[1]["text"], "one two three")


    def test_identity_binds_exact_normalized_source_text(self):
        text = plan.normalize_text("Synthetic  sentence . . .")
        self.assertEqual(text, "Synthetic sentence ...")
        self.assertNotEqual(
            plan.passage_identity(text, "a" * 64),
            plan.passage_identity("Synthetic sentence...", "a" * 64),
        )


if __name__ == "__main__":
    unittest.main()
