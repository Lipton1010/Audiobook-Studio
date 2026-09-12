"""A patch must be self-contained for app-module imports on an old install."""
import ast
import re
import unittest
from pathlib import Path


class PatchDependencyTests(unittest.TestCase):
    def test_all_local_imports_of_shipped_modules_are_also_shipped(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / "install/AudiobookStudio_Patch.iss").read_text(encoding="utf-8")
        shipped = set(re.findall(r'Source: "\.\.\\app\\([^"\\]+\.py)"', installer))
        self.assertIn("server.py", shipped)
        self.assertIn("narrate_worker.py", shipped)
        missing = set()
        for filename in shipped:
            tree = ast.parse((root / "app" / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [name.name for name in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    local = module.split(".")[0] + ".py"
                    if (root / "app" / local).exists() and local not in shipped:
                        missing.add(f"{filename} needs {local}")
        self.assertEqual(missing, set())
