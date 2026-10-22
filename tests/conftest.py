"""Tests never touch the real Parley folder. The speech models are borrowed from it when installed."""

import os
import tempfile
from pathlib import Path

_installed_models = Path.home() / ".parley" / "models"
os.environ["PARLEY_HOME"] = tempfile.mkdtemp(prefix="parley-test-")
if _installed_models.exists():
    os.environ.setdefault("PARLEY_MODELS", str(_installed_models))
