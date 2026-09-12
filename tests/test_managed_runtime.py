import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.managed_runtime import configure_managed_runtime


class ManagedRuntimeTests(unittest.TestCase):
    def test_launcher_mode_requires_existing_python(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(configure_managed_runtime(temp))
            self.assertNotIn("HF_HOME", os.environ)

    def test_setup_mode_creates_runtime_paths_and_sets_environment(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {}, clear=True):
            root = Path(temp)
            self.assertEqual(configure_managed_runtime(root, create_dirs=True), root.resolve())
            self.assertTrue((root / "cache").is_dir())
            self.assertTrue((root / "miniconda3" / "envs").is_dir())
            self.assertEqual(os.environ["CONDA_ENVS_PATH"], str(root / "miniconda3" / "envs"))
            self.assertEqual(os.environ["CONDA_NO_PLUGINS"], "true")


if __name__ == "__main__":
    unittest.main()
