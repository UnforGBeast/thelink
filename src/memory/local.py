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
#
# Derived from EGC (Extended Global Context) — original Apache 2.0 license retained.
"""
Local filesystem implementation of the Cognitive Memory Provider.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from memory.base import CognitiveMemoryProvider, MemoryEntry


class LocalFileProvider(CognitiveMemoryProvider):
    def __init__(self, workspace_root: str, namespace: str = "EGC"):
        self.root = Path(workspace_root) / ".sessions" / "memory" / namespace
        self.namespace = namespace

    def initialize(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            for sub in ["Sessions", "Archaeology", "Governance", "Traces"]:
                (self.root / sub).mkdir(exist_ok=True)
            return True
        except Exception:
            return False

    def write_note(self, entry: MemoryEntry) -> bool:
        try:
            target_dir = self.root / entry.category
            target_dir.mkdir(exist_ok=True)
            safe_title = entry.title.replace(" ", "_").replace("/", "-")
            file_path = target_dir / f"{safe_title}.md"
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("---\n")
                f.write(f"title: {entry.title}\n")
                f.write(f"category: {entry.category}\n")
                f.write(f"tags: [{', '.join(entry.tags)}]\n")
                f.write(f"timestamp: {entry.timestamp.isoformat()}\n")
                for k, v in entry.metadata.items():
                    f.write(f"{k}: {v}\n")
                f.write("---\n\n")
                f.write(entry.content)
            return True
        except Exception:
            return False

    def append_journal(self, category: str, content: str) -> bool:
        try:
            journal_path = self.root / category / "Journal.md"
            with open(journal_path, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"\n### {timestamp}\n\n{content}\n")
            return True
        except Exception:
            return False

    def search_memory(self, query: str) -> List[MemoryEntry]:
        return []

    def get_session_summary(self, session_id: str) -> Optional[str]:
        summary_path = self.root / "Sessions" / f"session_{session_id}.md"
        if summary_path.exists():
            with open(summary_path, "r", encoding="utf-8") as f:
                return f.read()
        return None
