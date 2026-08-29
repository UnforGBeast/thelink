# Copyright 2024 The Link Authors — Apache 2.0
"""
The Link — Test Suite
=====================

Five test modules covering every layer of the pipeline:

  tests/test_crusher.py      — Token Crusher unit tests
  tests/test_memory.py       — Memory reader + paths unit tests
  tests/test_graph.py        — Graph wrapper unit tests (graperoot-free)
  tests/test_cli.py          — CLI integration tests (subprocess)
  tests/test_e2e.py          — End-to-end pipeline test (requires graperoot)

Run all tests:
    python -m pytest tests/          (if pytest is installed)
    python -m unittest discover tests/   (stdlib only, no deps)

Run a single module:
    python -m unittest tests.test_crusher -v

Run a specific test:
    python -m unittest tests.test_crusher.TestReduceRows.test_dedup_identical_rows -v
"""
