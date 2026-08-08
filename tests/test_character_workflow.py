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
        "voice_type": "female",
        "voice_name": None,
        "invalid": False,
        "user_edited": False,
    }]
    plan = {
        "schema_version": cd.SCHEMA_VERSION,
        "source_sha256": cd.source_hash(blocks),
        "model": "synthetic-model",
        "analysis": {"num_ctx": 8192, "window_chars": 18000, "window_count": 1, "created_at": 1.0},
        "narrator": {"id": "narrator", "role": "narrator", "display_name": "Narrator", "voice_type": "unknown", "voice_name": None},
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
        self.voices = Path(self.temp.name) / "voices"
        self.voices.mkdir()
        self.voice_library = Path(self.temp.name) / "voice-library"
        self.voice_library.mkdir()
        self.voice_catalog = Path(self.temp.name) / "voice_catalog.json"
        self.default_voice = Path(self.temp.name) / "default.wav"
        self.default_voice.write_bytes(b"default-voice")
        self.jobs_patch = mock.patch.object(server, "JOBS_DIR", self.jobs)
        self.voices_patch = mock.patch.object(server, "VOICES_DIR", self.voices)
        self.reference_patch = mock.patch.object(
            server, "REFERENCE_WAV", str(self.default_voice)
        )
        self.voice_library_patch = mock.patch.object(
            server, "VOICE_LIBRARY_ROOTS", [self.voice_library]
        )
        self.voice_catalog_patch = mock.patch.object(
            server, "VOICE_CATALOG_PATH", self.voice_catalog
        )
        self.jobs_patch.start()
        self.voices_patch.start()
        self.reference_patch.start()
        self.voice_library_patch.start()
        self.voice_catalog_patch.start()

    def tearDown(self):
        self.voice_catalog_patch.stop()
        self.voice_library_patch.stop()
        self.reference_patch.stop()
        self.voices_patch.stop()
        self.jobs_patch.stop()
        self.temp.cleanup()

    def write_cast_job(self, job_id="cast-job"):
        job_dir = self.jobs / job_id
        job_dir.mkdir()
        blocks = [{
            "type": "body",
            "text": "Mara said, “Hello.”",
            "source_page": 1,
        }]
        (job_dir / "blocks.json").write_text(
            json.dumps({"blocks": blocks}), encoding="utf-8"
        )
        plan = valid_plan(blocks)
        (job_dir / "cast_plan.json").write_text(
            json.dumps(plan), encoding="utf-8"
        )
        state = {
            "id": job_id,
            "title": "Synthetic Novel",
            "pdf_path": "novel.pdf",
            "path": "A",
            "page_from": 1,
            "page_to": 1,
            "workflow": "cast_discovery",
            "status": "cast_ready",
            "cast_summary": plan["summary"],
        }
        server.save_state(state)
        return state, blocks, plan

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

    def test_voice_assignment_readiness_and_render_transition(self):
        state, blocks, plan = self.write_cast_job("job-6")
        (self.voices / "Mara Voice.wav").write_bytes(b"mara")
        character_id = plan["characters"][0]["id"]

        narrator_view = server.assign_cast_voice(
            state["id"], "narrator", server.DEFAULT_VOICE
        )
        self.assertFalse(narrator_view["render_readiness"]["can_start"])
        ready_view = server.assign_cast_voice(
            state["id"], character_id, "Mara Voice"
        )
        self.assertTrue(ready_view["render_readiness"]["can_start"])

        with mock.patch.object(server, "enqueue") as enqueue:
            queued = server.start_cast_narration(
                state["id"], {"format": "wav", "engine": "batched"}
            )

        self.assertEqual(queued["workflow"], "cast_narration")
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["format"], "wav")
        self.assertEqual(queued["cast_voice_count"], 2)
        enqueue.assert_called_once_with(state["id"])

    def test_external_voice_library_uses_filename_types_and_local_overrides(self):
        female = self.voice_library / "Female Ember.wav"
        male = self.voice_library / "Male Rowan.wav"
        mystery = self.voice_library / "Mystery Voice.wav"
        female.write_bytes(b"female")
        male.write_bytes(b"male")
        mystery.write_bytes(b"mystery")

        voices = {item["name"]: item for item in server.list_voices()}
        self.assertEqual(voices[server.DEFAULT_VOICE]["voice_type"], "unknown")
        self.assertEqual(voices["Female Ember"]["voice_type"], "female")
        self.assertEqual(voices["Male Rowan"]["voice_type"], "male")
        self.assertEqual(voices["Mystery Voice"]["voice_type"], "unknown")
        self.assertEqual(voices["Female Ember"]["source"], "library")
        self.assertFalse(voices["Female Ember"]["deletable"])
        self.assertEqual(
            Path(server.assigned_voice_wav_path("Female Ember")), female
        )

        server.set_voice_catalog_type("Mystery Voice", "female")
        updated = {item["name"]: item for item in server.list_voices()}
        self.assertEqual(updated["Mystery Voice"]["voice_type"], "female")
        catalog_text = self.voice_catalog.read_text(encoding="utf-8")
        self.assertNotIn(str(mystery), catalog_text)
        self.assertNotIn("mystery", catalog_text)

    def test_voice_type_mismatch_warns_but_does_not_block_render(self):
        state, _, plan = self.write_cast_job("job-types")
        (self.voices / "Male Rowan.wav").write_bytes(b"male")
        character_id = plan["characters"][0]["id"]
        server.assign_cast_voice(state["id"], "narrator", server.DEFAULT_VOICE)
        view = server.assign_cast_voice(
            state["id"], character_id, "Male Rowan"
        )

        readiness = view["render_readiness"]
        self.assertTrue(readiness["can_start"])
        self.assertEqual(
            readiness["voice_type_mismatches"][0]["display_name"], "Mara Vale"
        )

        corrected = server.set_cast_voice_type(
            state["id"], character_id, "male"
        )
        self.assertFalse(corrected["render_readiness"]["voice_type_mismatches"])
        self.assertEqual(corrected["characters"][0]["voice_type"], "male")

    def test_render_rejects_missing_character_voice(self):
        state, _, _ = self.write_cast_job("job-7")
        server.assign_cast_voice(
            state["id"], "narrator", server.DEFAULT_VOICE
        )

        with self.assertRaisesRegex(ValueError, "Mara Vale"):
            server.start_cast_narration(state["id"], {"format": "wav"})

    def test_multivoice_hash_changes_with_character_assignment(self):
        state, blocks, plan = self.write_cast_job("job-8")
        (self.voices / "Mara One.wav").write_bytes(b"mara-one")
        (self.voices / "Mara Two.wav").write_bytes(b"mara-two")
        character_id = plan["characters"][0]["id"]
        server.assign_cast_voice(state["id"], "narrator", server.DEFAULT_VOICE)
        server.assign_cast_voice(state["id"], character_id, "Mara One")
        state = server.load_state(state["id"])
        state["workflow"] = "cast_narration"
        first = server._plan_hash(self.jobs / state["id"], state)

        server.assign_cast_voice(state["id"], character_id, "Mara Two")
        second = server._plan_hash(self.jobs / state["id"], state)

        self.assertNotEqual(first, second)

    def test_missing_cast_voice_does_not_fall_back_to_narrator(self):
        requested = Path(server.assigned_voice_wav_path("Deleted Voice"))

        self.assertEqual(requested, self.voices / "Deleted Voice.wav")
        self.assertEqual(
            Path(server.voice_wav_path("Deleted Voice")), self.default_voice
        )


if __name__ == "__main__":
    unittest.main()
