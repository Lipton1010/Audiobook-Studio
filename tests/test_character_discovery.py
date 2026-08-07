import copy
import json
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

import character_discovery as cd


class FakeClient:
    def __init__(self):
        self.calls = []
        self.unloaded = False

    def call_json(self, prompt):
        self.calls.append(prompt)
        if "Allowed cast:" not in prompt:
            return {
                "characters": [
                    {
                        "display_name": "Alice Vale",
                        "aliases": ["Alice"],
                        "evidence_turn_ids": ["turn_000001"],
                    },
                    {
                        "display_name": "Bob Reed",
                        "aliases": ["Bob"],
                        "evidence_turn_ids": ["turn_000002"],
                    },
                ]
            }
        return {
            "attributions": [
                {
                    "turn_id": "turn_000001",
                    "is_speech": True,
                    "speaker_id": cd._stable_character_id("Alice Vale"),
                    "confidence": "high",
                    "evidence_type": "explicit",
                },
                {
                    "turn_id": "turn_000002",
                    "is_speech": True,
                    "speaker_id": cd._stable_character_id("Bob Reed"),
                    "confidence": "medium",
                    "evidence_type": "context",
                },
            ]
        }

    def unload(self):
        self.unloaded = True


class CharacterDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            {
                "type": "body",
                "text": "Alice Vale opened the door. “Come inside,” Alice said.",
                "source_page": 4,
            },
            {
                "type": "body",
                "text": "Bob Reed shook his head. “Not tonight,” he replied.",
                "source_page": 4,
            },
        ]

    def make_plan(self):
        client = FakeClient()
        plan = cd.analyze_blocks(
            self.blocks,
            client,
            model_name="synthetic-model",
            window_chars=5000,
        )
        self.assertTrue(client.unloaded)
        return plan

    def test_quote_candidates_anchor_exact_source_without_copying_text(self):
        turns = cd.find_dialogue_candidates(self.blocks)
        self.assertEqual([turn["id"] for turn in turns], ["turn_000001", "turn_000002"])
        first = turns[0]
        source = self.blocks[first["block_index"]]["text"]
        self.assertEqual(source[first["start"]:first["end"]], "“Come inside,”")
        self.assertEqual(first["source_page"], 4)
        self.assertEqual(first["block_sha256"], cd.block_text_hash(self.blocks[0]))

    def test_multi_paragraph_open_quote_keeps_one_group(self):
        blocks = [
            {"type": "body", "text": "“First paragraph without a closing mark"},
            {"type": "body", "text": "Second paragraph closes here.” Mara sat down."},
        ]
        turns = cd.find_dialogue_candidates(blocks)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["group_id"], turns[1]["group_id"])
        self.assertTrue(turns[0]["continues"])
        self.assertFalse(turns[1]["continues"])

    def test_source_hash_ignores_provenance_but_not_spoken_text(self):
        with_pages = cd.source_hash(self.blocks)
        without_pages = copy.deepcopy(self.blocks)
        for block in without_pages:
            block.pop("source_page")
        self.assertEqual(with_pages, cd.source_hash(without_pages))
        without_pages[0]["text"] += " Changed."
        self.assertNotEqual(with_pages, cd.source_hash(without_pages))

    def test_two_pass_plan_is_valid_and_contains_no_book_passages(self):
        plan = self.make_plan()
        self.assertEqual(plan["summary"]["speaking_characters"], 2)
        self.assertEqual(plan["summary"]["attributed_turns"], 2)
        self.assertEqual(plan["summary"]["unknown_turns"], 0)
        persisted = json.dumps(plan, ensure_ascii=False)
        self.assertNotIn("Come inside", persisted)
        self.assertNotIn("Not tonight", persisted)
        cd.validate_cast_plan(plan, self.blocks)

    def test_source_change_invalidates_cast_plan(self):
        plan = self.make_plan()
        changed = copy.deepcopy(self.blocks)
        changed[0]["text"] = changed[0]["text"].replace("inside", "upstairs")
        with self.assertRaisesRegex(cd.CastPlanError, "source hash"):
            cd.validate_cast_plan(plan, changed)

    def test_rename_merge_and_invalidate_are_audited(self):
        plan = self.make_plan()
        alice, bob = [item["id"] for item in plan["characters"]]
        renamed = cd.apply_cast_edit(
            plan, self.blocks,
            {"action": "rename", "character_id": alice, "display_name": "Alice V."},
        )
        self.assertEqual(renamed["characters"][0]["display_name"], "Alice V.")
        self.assertIn("Alice Vale", renamed["characters"][0]["aliases"])

        merged = cd.apply_cast_edit(
            renamed, self.blocks,
            {"action": "merge", "character_id": bob, "target_character_id": alice},
        )
        self.assertEqual(len(merged["characters"]), 1)
        self.assertEqual(merged["summary"]["attributed_turns"], 2)
        self.assertTrue(all(turn["speaker_id"] == alice for turn in merged["turns"]))

        invalid = cd.apply_cast_edit(
            merged, self.blocks,
            {"action": "invalidate", "character_id": alice},
        )
        self.assertEqual(invalid["summary"]["speaking_characters"], 0)
        self.assertEqual(invalid["summary"]["unknown_turns"], 2)
        self.assertEqual(len(invalid["edits"]), 3)

    def test_model_must_return_every_target_turn_once(self):
        class MissingAttributionClient(FakeClient):
            def call_json(self, prompt):
                if "Allowed cast:" in prompt:
                    return {"attributions": []}
                return super().call_json(prompt)

        client = MissingAttributionClient()
        with self.assertRaisesRegex(cd.CastPlanError, "omitted target ids"):
            cd.analyze_blocks(
                self.blocks, client, model_name="synthetic-model", window_chars=5000
            )
        self.assertTrue(client.unloaded)

    def test_narration_only_prefix_does_not_overflow_first_window(self):
        blocks = [
            {"type": "body", "text": "Narration " * 300},
            {"type": "body", "text": "More narration " * 300},
            {"type": "body", "text": "Alice said, “Now we begin.”"},
        ]
        turns = cd.find_dialogue_candidates(blocks)
        windows = cd.build_windows(blocks, turns, char_limit=1000)
        self.assertEqual(windows[0].start_block, 2)
        self.assertEqual(windows[0].target_turn_ids, ("turn_000001",))

    def test_character_without_anchored_evidence_is_rejected(self):
        class UnanchoredClient(FakeClient):
            def call_json(self, prompt):
                if "Allowed cast:" not in prompt:
                    return {"characters": [{
                        "display_name": "Invented Person",
                        "aliases": [],
                        "evidence_turn_ids": ["turn_999999"],
                    }]}
                return super().call_json(prompt)

        with self.assertRaisesRegex(cd.CastPlanError, "no valid anchored"):
            cd.analyze_blocks(
                self.blocks, UnanchoredClient(), model_name="synthetic-model",
                window_chars=5000,
            )

    def test_is_speech_must_be_a_json_boolean(self):
        class StringBooleanClient(FakeClient):
            def call_json(self, prompt):
                response = super().call_json(prompt)
                if "attributions" in response:
                    response["attributions"][0]["is_speech"] = "false"
                return response

        with self.assertRaisesRegex(cd.CastPlanError, "JSON boolean"):
            cd.analyze_blocks(
                self.blocks, StringBooleanClient(), model_name="synthetic-model",
                window_chars=5000,
            )


if __name__ == "__main__":
    unittest.main()
