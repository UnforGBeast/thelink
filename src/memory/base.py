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
Base interface for Cognitive Memory Providers.
Ensures clean boundaries between the repository and external memory stores.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class MemoryEntry:
    title: str
    content: str
    category: str  # e.g. 'Sessions', 'Archaeology', 'Governance'
    tags: List[str]
    metadata: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)


class CognitiveMemoryProvider(ABC):
    """Abstract base class for all cognitive memory providers."""

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the provider and ensure the storage backend is ready."""

    @abstractmethod
    def write_note(self, entry: MemoryEntry) -> bool:
        """Write a new note to the memory store."""

    @abstractmethod
    def append_journal(self, category: str, content: str) -> bool:
        """Append a snippet to a continuous journal/log file."""

    @abstractmethod
    def search_memory(self, query: str) -> List[MemoryEntry]:
        """Search the memory store for existing entries."""

    @abstractmethod
    def get_session_summary(self, session_id: str) -> Optional[str]:
        """Retrieve a summary of a specific session."""
