import unittest

from app import generation_settings as settings
from app import vibevoice_plan


class GenerationSettingsTests(unittest.TestCase):
    def test_defaults_preserve_recommended_values(self):
        self.assertEqual(settings.default_settings("chatterbox", "A")["block_gap_ms"], 650)
        self.assertEqual(settings.default_settings("chatterbox", "B")["gap_ms"], 50)
        self.assertEqual(settings.default_settings("vibevoice", "A")["cfg_scale"], 2.0)
        self.assertEqual(settings.default_settings("vibevoice", "A")["ddpm_steps"], 20)

    def test_rejects_invalid_values_and_unknown_fields(self):
        for value in (True, float("nan"), float("inf"), -1, 5001):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    settings.normalize_settings("vibevoice", "A", {"passage_gap_ms": value})
        for value in (True, float("nan"), 0.5, 101):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    settings.normalize_settings("vibevoice", "A", {"ddpm_steps": value})
        with self.assertRaisesRegex(ValueError, "unknown"):
            settings.normalize_settings("chatterbox", "A", {"model_path": "nope"})
        with self.assertRaises(ValueError):
            settings.normalize_settings("vibevoice", "A", {"performance_mode": True})

    def test_runtime_mapping_keeps_batching_out_of_audio_settings(self):
        mapped = settings.runtime_settings("vibevoice", "A", {"performance_mode": "conservative"})
        self.assertEqual(mapped["batch_preference"], "conservative")
        self.assertFalse(mapped["cross_parent_render_ahead"])
        self.assertEqual(mapped["cfg_scale"], 2.0)
        self.assertTrue(settings.runtime_settings("vibevoice", "A")["cross_parent_render_ahead"])

    def test_vibevoice_synthesis_changes_identity_but_pauses_do_not(self):
        defaults = settings.default_settings("vibevoice", "A")
        paused = settings.normalize_settings("vibevoice", "A", {
            "passage_gap_ms": 400, "heading_lead_ms": 500,
        })
        changed = settings.normalize_settings("vibevoice", "A", {
            "cfg_scale": 3.0, "ddpm_steps": 30,
        })
        runtime = {
            **vibevoice_plan.RUNTIME,
            "cfg_scale": defaults["cfg_scale"],
            "ddpm_steps": defaults["ddpm_steps"],
        }
        paused_runtime = {
            **vibevoice_plan.RUNTIME,
            "cfg_scale": paused["cfg_scale"],
            "ddpm_steps": paused["ddpm_steps"],
        }
        self.assertEqual(
            vibevoice_plan.passage_identity("Same words.", "a" * 64, runtime),
            vibevoice_plan.passage_identity("Same words.", "a" * 64, paused_runtime),
        )
        changed_runtime = {**runtime, "cfg_scale": changed["cfg_scale"], "ddpm_steps": changed["ddpm_steps"]}
        self.assertNotEqual(
            vibevoice_plan.passage_identity("Same words.", "a" * 64, runtime),
            vibevoice_plan.passage_identity("Same words.", "a" * 64, changed_runtime),
        )
        self.assertEqual(defaults["cfg_scale"], paused["cfg_scale"])


if __name__ == "__main__":
    unittest.main()
