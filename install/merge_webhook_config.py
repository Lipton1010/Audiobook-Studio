"""Merge-safe config.json writer, run once by the patch installer.

Adds or updates ONLY error_webhook_url. Every other key in an existing
config.json -- especially chatterbox_python, which setup.py writes at
initial install and which this machine's app depends on to find its
narration environment -- is read back and preserved untouched. A missing
or unparsable existing file just means starting from an empty object,
never a hard failure: this script backs a nice-to-have (crash reporting),
never the app's ability to run.

Usage: python merge_webhook_config.py <config_json_path> <webhook_url>
"""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
url = sys.argv[2]

data = {}
if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}

data["error_webhook_url"] = url
path.write_text(json.dumps(data, indent=2), encoding="utf-8")
