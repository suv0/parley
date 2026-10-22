"""Tests never touch the real Utter folder. The speech models are borrowed from it when installed."""

import os
import tempfile
from pathlib import Path

_installed_models = Path.home() / ".utter" / "models"
os.environ["UTTER_HOME"] = tempfile.mkdtemp(prefix="utter-test-")
if _installed_models.exists():
    os.environ.setdefault("UTTER_MODELS", str(_installed_models))
