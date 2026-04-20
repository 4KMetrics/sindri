"""Local vs remote benchmark mode detection.

Two signals - either triggers remote:
  1. Script content references external tools (`gh`, `aws`, `gcloud`, etc.)
     that imply network/third-party cost. Localhost-whitelisted for `curl`/`wget`.
  2. Observed coefficient of variation > 15% across non-warmup baseline runs.

Default is `local`; remote requires positive evidence.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from sindri.core.noise import NoiseComputationError, coefficient_of_variation

# Tools that imply external-service calls (networked, cost-bearing, rate-limited).
_REMOTE_TOOLS = [
    r"\bgh\b",
    r"\baws\b",
    r"\bgcloud\b",
    r"\bkubectl\b",
    r"\bssh\b",
    r"\brsync\b",
    r"\bterraform\b",
    r"\bansible\b",
    r"\baz\b",
]

# `curl` and `wget` are only remote if pointing at a non-localhost URL on the
# same line. Separator between the tool and URL may be quotes, spaces, commas,
# etc. Both tools are commonly used for localhost health probes in benchmarks,
# so keeping local-mode for those cases preserves measurement quality.
_NON_LOCALHOST_URL = (
    r"(https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])[^\s'\"]+)"
)
_CURL_WITH_REMOTE_URL = re.compile(
    r"\bcurl\b[^\n]*?" + _NON_LOCALHOST_URL, re.IGNORECASE
)
_WGET_WITH_REMOTE_URL = re.compile(
    r"\bwget\b[^\n]*?" + _NON_LOCALHOST_URL, re.IGNORECASE
)

_COMBINED_REMOTE_RE = re.compile("|".join(_REMOTE_TOOLS), re.IGNORECASE)

# CV threshold above which observed noise triggers remote mode.
CV_REMOTE_THRESHOLD = 0.15


def script_content_signal(script_path: Path) -> Literal["local", "remote"]:
    """Scan script content for external-tool references."""
    # Cap at 1 MiB — we're scanning for keywords, not loading bundles.
    text = script_path.read_text()[: 1 << 20]
    # Check always-remote tools first (cheap regex).
    if _COMBINED_REMOTE_RE.search(text):
        return "remote"
    # curl/wget — only remote if they point at a non-localhost URL.
    if _CURL_WITH_REMOTE_URL.search(text) or _WGET_WITH_REMOTE_URL.search(text):
        return "remote"
    return "local"


def detect_mode(
    script_path: Path,
    baseline_samples: list[float],
) -> Literal["local", "remote"]:
    """Combine script-content signal with observed CV to decide local vs remote.

    Baseline samples: all recorded baseline runs (may include warmup at index 0).
    The CV is computed over samples[1:] (post-warmup).
    """
    if script_content_signal(script_path) == "remote":
        return "remote"

    # Observed-noise signal - discard warmup run
    post_warmup = baseline_samples[1:]
    if len(post_warmup) >= 2:
        try:
            cv = coefficient_of_variation(post_warmup)
        except NoiseComputationError:
            cv = 0.0
        if cv > CV_REMOTE_THRESHOLD:
            return "remote"

    return "local"
