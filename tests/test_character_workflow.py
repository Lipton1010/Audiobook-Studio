import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
sys.modules.setdefault("fitz", types.ModuleType("fitz"))

import character_discovery as cd
import server


def valid_plan(blocks):
    turns = cd.find_dialogue_candidates(blocks)
    character_id = cd._stable_character_id("Mara Vale")
    for turn in turns:
        turn.update({
            "status": "attributed",
            "speaker_id": character_id,
            "confidence": "high",
            "evidence_type": "explicit",
        })
    characters = [{
        "id": character_id,
        "role": "character",
        "display_name": "Mara Vale",
        "aliases": ["Mara"],
        "evidence_turn_ids": [turns[0]["id"]],
        "turn_count": len(turns),
        "confidence_counts": {"high": len(turns), "medium": 0, "low": 0},
        "voice_name": None,
        "invalid": False,
        "user_edited": False,
    }]
    plan = {
        "schema_version": cd.SCHEMA_VERSION,
        "source_sha256": cd.source_hash(blocks),
        "model": "synthetic-model",
        "analysis": {"num_ctx": 8192, "window_chars": 18000, "window_count": 1, "created_at": 1.0},
        "narrator": {"id": "narrator", "role": "narrator", "display_name": "Narrator", "voice_name": None},
        "characters": characters,
        "turns": turns,
        "edits": [],
    }
    plan["summary"] = cd.summarize_cast_plan(plan)
    cd.validate_cast_plan(plan, blocks)
    return plan


class CharacterWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs = Path(self.temp.name) / "jobs"
        self.jobs.mkdir()
        self.jobs_patch = mock.patch.object(server, "JOBS_DIR", self.jobs)
        self.jobs_patch.start()

    def tearDown(self):
        self.jobs_patch.stop()
        self.temp.cleanup()

    def test_discovery_state_needs_no_voice_format_or_engine(self):
        state = server.build_job_state({
            "pdf_path": "novel.pdf",
            "path": "A",
            "workflow": "cast_discovery",
            "page_from": 2,
            "page_to": 100,
        }, 80, "job-1")
        self.assertEqual(state["workflow"], "cast_discovery")
        self.assertEqual(state["page_to"], 80)
        self.assertNotIn("voice", state)
        self.assertNotIn("format", state)
        self.assertNotIn("engine", state)

    def test_ordinary_job_keeps_existing_defaults(self):
        state = server.build_job_state({
            "pdf_path": "novel.pdf", "path": "A"
        }, 20, "job-2")
        self.assertEqual(state["workflow"], "narrate")
        self.assertEqual(state["voice"], server.DEFAULT_VOICE)
        self.assertEqual(state["format"], "m4b")
        self.assertEqual(state["engine"], server.DEFAULT_ENGINE)

    def test_discovery_rejects_path_b(self):
        with self.assertRaisesRegex(ValueError, "Path A"):
            server.build_job_state({
                "pdf_path": "rulebook.pdf",
                "path": "B",
                "workflow": "cast_discovery",
            }, 10, "job-3")

    def test_discovery_writes_cast_and_stops_before_narration_files(self):
        job_id = "job-4"
        job_dir = self.jobs / job_id
        job_dir.mkdir()
        blocks = [{
            "type": "body",
            "text": "Mara Vale smiled. “We made it,” Mara said.",
            "source_page": 7,
        }]
        (job_dir / "blocks.json").write_text(
            json.dumps({"blocks": blocks}), encoding="utf-8"
        )
        state = {
            "id": job_id,
            "title": "Synthetic Novel",
            "pdf_path": "novel.pdf",
            "path": "A",
            "text_mode": "prose",
            "workflow": "cast_discovery",
            "status": "queued",
        }
        server.save_state(state)
        plan = valid_plan(blocks)

        with mock.patch.object(server.cd, "OllamaJSONClient") as client_cls, \
             mock.patch.object(server.cd, "analyze_blocks", return_value=plan):
            finished = server.run_character_discovery(state)

        client_cls.assert_called_once()
        self.assertEqual(finished["status"], "cast_ready")
        self.assertTrue((job_dir / "cast_plan.json").exists())
        self.assertFalse((job_dir / "config.json").exists())
        self.assertFalse((job_dir / "segments").exists())
        view = server.cast_plan_view(job_id)
        self.assertEqual(view["summary"]["speaking_characters"], 1)
        self.assertEqual(view["characters"][0]["example"], "“We made it,”")
        self.assertEqual(view["characters"][0]["example_page"], 7)

    def test_cast_edit_persists_without_changing_blocks(self):
        job_id = "job-5"
        job_dir = self.jobs / job_id
        job_dir.mkdir()
        blocks = [{
            "type": "body", "text": "Mara said, “Hello.”", "source_page": 1
        }]
        original_blocks = json.dumps({"blocks": blocks})
        (job_dir / "blocks.json").write_text(original_blocks, encoding="utf-8")
        plan = valid_plan(blocks)
        (job_dir / "cast_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        server.save_state({"id": job_id, "status": "cast_ready", "cast_summary": plan["summary"]})

        character_id = plan["characters"][0]["id"]
        view = server.edit_cast_plan(job_id, {
            "action": "rename", "character_id": character_id,
            "display_name": "Mara V.",
        })
        self.assertEqual(view["characters"][0]["display_name"], "Mara V.")
        self.assertEqual(
            (job_dir / "blocks.json").read_text(encoding="utf-8"), original_blocks
        )


if __name__ == "__main__":
    unittest.main()
