#!/usr/bin/env python3
# Copyright 2024 The Link Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
link_cli.py — source-checkout entry point.

Thin shim that runs the packaged CLI (``thelink.cli:main``) without requiring
an install. Prefer ``link`` (installed console script) or ``python -m thelink``;
this file exists only so ``python link_cli.py "<query>"`` keeps working from a
bare clone.

The single implementation lives in ``thelink/``. This file holds no pipeline
logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make ``import thelink`` resolve when running from an un-installed checkout.
_REPO_ROOT = Path(__file__).parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from thelink.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
