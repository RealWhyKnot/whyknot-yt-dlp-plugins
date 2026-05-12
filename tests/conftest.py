# Make the repo root importable so `import yt_dlp_plugins.extractor.nepu`
# works from a fresh checkout without first running `pip install -e .`.
# Without this, pytest's rootdir is `tests/` and the plugin namespace is
# not on sys.path.

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
