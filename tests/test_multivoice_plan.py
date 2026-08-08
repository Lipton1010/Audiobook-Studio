import re
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

import character_discovery as cd
import multivoice_plan as mvp


PROFILE = {
    "gap_ms": 150,
    "block_gap_ms": 650,
    "heading_before_ms": 200,
    "heading_after_ms": 150,
}


def make_plan(blocks, speaker_names, narrator_voice="Narrator Voice"):
    turns = cd.find_dialogue_candidates(blocks)
    character_ids = {
        name: cd._stable_character_id(name)
        for name in sorted({name for name in speaker_names if name})
    }
    evidence = {name: [] for name in character_ids}
    for turn, name in zip(turns, speaker_names):
        if name:
            turn.update({
                "status": "attributed",
                "speaker_id": character_ids[name],
                "confidence": "high",
                "evidence_type": "explicit",
            })
            evidence[name].append(turn["id"])
        else:
            turn.update({
                "status": "unknown",
                "speaker_id": None,
                "confidence": "low",
                "evidence_type": "unknown",
            })
    characters = []
    for name, character_id in character_ids.items():
        count = len(evidence[name])
        characters.append({
            "id": character_id,
            "role": "character",
            "display_name": name,
            "aliases": [],
            "evidence_turn_ids": evidence[name],
            "turn_count": count,
            "confidence_counts": {"high": count, "medium": 0, "low": 0},
            "voice_name": f"{name} Voice",
            "invalid": False,
            "user_edited": False,
        })
    plan = {
        "schema_version": cd.SCHEMA_VERSION,
        "source_sha256": cd.source_hash(blocks),
        "model": "synthetic-model",
        "analysis": {
            "num_ctx": 8192,
            "window_chars": 18000,
            "window_count": 1,
            "created_at": 1.0,
        },
        "narrator": {
            "id": "narrator",
            "role": "narrator",
            "display_name": "Narrator",
            "voice_name": narrator_voice,
        },
        "characters": characters,
        "turns": turns,
        "edits": [],
    }
    plan["summary"] = cd.summarize_cast_plan(plan)
    cd.validate_cast_plan(plan, blocks)
    return plan


class MultiVoicePlanTests(unittest.TestCase):
    def test_dialogue_and_narration_use_exact_attributed_voices(self):
        blocks = [{
            "type": "body",
            "text": "“Go now,” Mara said. “Wait,” Jon replied.",
            "source_page": 4,
        }]
        cast = make_plan(blocks, ["Mara", "Jon"])

        plan = mvp.build_plan(blocks, cast, PROFILE)

        self.assertEqual(
            [(item["role"], item["voice_name"]) for item in plan],
            [
                ("character", "Mara Voice"),
                ("narrator", "Narrator Voice"),
                ("character", "Jon Voice"),
                ("narrator", "Narrator Voice"),
            ],
        )
        self.assertEqual([item["after_ms"] for item in plan], [0, 0, 0, 0])
        self.assertEqual(
            "".join(
                re.sub(r"\s+", "", blocks[0]["text"][item["source_start"]:item["source_end"]])
                for item in plan
            ),
            re.sub(r"\s+", "", blocks[0]["text"]),
        )

    def test_unknown_quote_falls_back_to_narrator_without_text_loss(self):
        blocks = [{
            "type": "body",
            "text": "A sign read “East Gate.” Beyond it, the road narrowed.",
        }]
        cast = make_plan(blocks, [None])

        plan = mvp.build_plan(blocks, cast, PROFILE)

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["speaker_id"], "narrator")
        self.assertEqual(plan[0]["voice_name"], "Narrator Voice")
        self.assertEqual(plan[0]["text"], blocks[0]["text"])

    def test_common_dialogue_turn_stays_whole_and_long_turn_splits_safely(self):
        common = "A" * 480 + "."
        long = ("A" * 320 + ". ") * 2
        blocks = [{"type": "body", "text": f"“{common}”"},
                  {"type": "body", "text": f"“{long}”"}]
        cast = make_plan(blocks, ["Mara", "Mara"])

        chunks = mvp.compile_chunks(blocks, cast)
        first = [item for item in chunks if item["block_index"] == 0]
        second = [item for item in chunks if item["block_index"] == 1]

        self.assertEqual(len(first), 1)
        self.assertGreater(len(second), 1)
        self.assertTrue(all(item["speaker_id"] == cast["characters"][0]["id"] for item in chunks))
        mvp.validate_compiled_chunks(chunks, blocks)

    def test_missing_required_voice_is_rejected_before_tts(self):
        blocks = [{"type": "body", "text": "“Hello,” Mara said."}]
        cast = make_plan(blocks, ["Mara"], narrator_voice=None)

        with self.assertRaisesRegex(mvp.MultiVoicePlanError, "Narrator"):
            mvp.compile_chunks(blocks, cast)

    def test_stale_cast_is_rejected_inside_shared_worker_compiler(self):
        blocks = [{"type": "body", "text": "“Hello,” Mara said."}]
        cast = make_plan(blocks, ["Mara"])
        changed = [{"type": "body", "text": "“Goodbye,” Mara said."}]

        with self.assertRaisesRegex(mvp.MultiVoicePlanError, "source hash"):
            mvp.compile_chunks(changed, cast)

    def test_generation_groups_are_stable_by_voice(self):
        plan = [
            {"voice_path": "narrator.wav"},
            {"voice_path": "mara.wav"},
            {"voice_path": "narrator.wav"},
            {"voice_path": "jon.wav"},
        ]

        groups = mvp.group_indices_by_voice(plan, [0, 1, 2, 3], "default.wav")

        self.assertEqual(groups, [
            ("narrator.wav", [0, 2]),
            ("mara.wav", [1]),
            ("jon.wav", [3]),
        ])


if __name__ == "__main__":
    unittest.main()
