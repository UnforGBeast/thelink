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
Composable relevance scoring for The Link.

A file is ranked by summing the *weighted* output of several independent
**signals**. Each signal is a pure function ``(FileDoc, ScoreContext) -> float``
returning a non-negative raw contribution; the registry pairs it with a default
weight. Adding a new signal (git recency, import-graph proximity, …) is a
``@signal(...)`` decorator plus an entry in ``DEFAULT_SIGNALS`` — no change to
``score_documents`` or to ``graph.extract_relevant_files``.

Public API:
    tokenize(text)                       -> list[str]
    FileDoc                              — normalized per-file scoring input
    ScoreContext                         — query/history/corpus/graph state
    signal(name, weight)                 — register a per-document signal
    propagator(name, weight)             — register a corpus-global pass
    score_documents(docs, ctx, ...)      -> list[ScoredDoc]  (ranked, best first)

Everything here is deterministic and stdlib-only.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# ── Tokenisation ─────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")

# Very small stop list — identifiers and path fragments only, no prose stemming.
_STOP = frozenset({
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "are",
    "be", "this", "that", "it", "with", "as", "at", "by", "from",
    "py", "js", "ts", "tsx", "jsx", "go", "rs", "java", "rb", "md", "txt",
    "src", "lib", "test", "tests", "spec",
})

_MIN_STEM_LEN = 4
_STEM_TAIL = 3  # keep at least this many chars when trimming a suffix


def _stem(tok: str) -> str:
    """Light inflection trim so ``charge``/``charges`` and
    ``authenticating``/``authenticated`` collapse to a shared form.

    Deliberately crude: plural ``-s``/``-ies`` and verb ``-ing``/``-ed`` only,
    no derivational rules, no vowel or double-consonant handling. Tokens
    shorter than ``_MIN_STEM_LEN`` are returned unchanged. Cross-family
    matching (``auth`` ↔ ``authentication``) is handled at query time by
    :meth:`_Bm25Index.expand`, not here.
    """
    if len(tok) < _MIN_STEM_LEN:
        return tok
    if tok.endswith("ies") and len(tok) > 4:
        tok = tok[:-3] + "y"
    elif tok.endswith(("sses", "shes", "ches", "xes", "zes", "ses")):
        tok = tok[:-2]
    elif tok.endswith("s") and not tok.endswith(("ss", "us", "is", "as")):
        tok = tok[:-1]
    if tok.endswith("ing") and len(tok) - 3 >= _STEM_TAIL:
        tok = tok[:-3]
    elif tok.endswith("ed") and len(tok) - 2 >= _STEM_TAIL:
        tok = tok[:-2]
    return tok


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def tokenize(text: str, *, stem: bool = True) -> list[str]:
    """Split *text* into lowercase identifier tokens.

    Splits on non-alphanumerics and on camelCase / PascalCase boundaries, so
    ``AuthMiddleware`` → ``auth``, ``middleware``. Drops a small stop list and
    (by default) applies :func:`_stem`. Order preserved; duplicates kept (BM25
    needs term frequencies).
    """
    out: list[str] = []
    for chunk in _TOKEN_RE.findall(text or ""):
        parts = _CAMEL_RE.findall(chunk) or [chunk]
        for p in parts:
            p = p.lower()
            if len(p) < 2 or p in _STOP:
                continue
            out.append(_stem(p) if stem else p)
    return out


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FileDoc:
    """One scannable file, with its text fields already tokenised.

    ``fields`` maps a field name (``path``, ``symbols``, ``keywords``,
    ``summary``) to its token list. Signals read from here rather than
    re-parsing the raw graph node.
    """
    path: str
    fields: dict[str, list[str]]
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def all_tokens(self) -> list[str]:
        out: list[str] = []
        for toks in self.fields.values():
            out.extend(toks)
        return out


@dataclass
class ScoreContext:
    """Everything the signals may need beyond a single :class:`FileDoc`."""
    query: str
    history: str
    project_path: Path
    edges: list[dict] = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    # Derived — filled in by score_documents(). Present here so signals can rely
    # on them without recomputing per document.
    query_terms: list[str] = field(default_factory=list)
    history_terms: list[str] = field(default_factory=list)
    bm25: "_Bm25Index | None" = field(default=None, repr=False)


@dataclass(frozen=True)
class SignalScore:
    name: str
    raw: float
    weight: float

    @property
    def weighted(self) -> float:
        return self.raw * self.weight


@dataclass
class ScoredDoc:
    doc: FileDoc
    signals: list[SignalScore]

    @property
    def path(self) -> str:
        return self.doc.path

    @property
    def total(self) -> float:
        return sum(s.weighted for s in self.signals)

    def breakdown(self) -> dict[str, float]:
        return {s.name: s.weighted for s in self.signals}


Signal = Callable[[FileDoc, ScoreContext], float]

_REGISTRY: dict[str, tuple[Signal, float]] = {}


def signal(name: str, weight: float) -> Callable[[Signal], Signal]:
    """Register *fn* as a scoring signal under *name* with a default *weight*."""
    def _register(fn: Signal) -> Signal:
        _REGISTRY[name] = (fn, float(weight))
        return fn
    return _register


def registered_signals() -> dict[str, float]:
    """``{name: default_weight}`` for every registered signal (for --explain / docs)."""
    return {n: w for n, (_, w) in _REGISTRY.items()}


# ── BM25 index ───────────────────────────────────────────────────────────────

# Field multipliers: a hit in a file's own name/symbols counts for more than a
# hit buried in its generated summary.
_FIELD_WEIGHTS = {
    "path": 3.0,
    "symbols": 2.5,
    "keywords": 1.5,
    "summary": 1.0,
}
_BM25_K1 = 1.5
_BM25_B = 0.75
_HISTORY_TERM_WEIGHT = 0.4  # history terms count, but less than the live query


@dataclass
class _Bm25Index:
    """Field-weighted BM25 over the current corpus. Rebuilt per ranking call."""
    doc_tf: list[Counter]           # weighted term frequency per doc
    doc_len: list[float]            # weighted length per doc
    avgdl: float
    idf: dict[str, float]
    vocab: frozenset[str]

    @classmethod
    def build(cls, docs: list[FileDoc]) -> "_Bm25Index":
        doc_tf: list[Counter] = []
        doc_len: list[float] = []
        df: Counter = Counter()
        for d in docs:
            tf: Counter = Counter()
            for fname, toks in d.fields.items():
                fw = _FIELD_WEIGHTS.get(fname, 1.0)
                for t in toks:
                    tf[t] += fw
            doc_tf.append(tf)
            doc_len.append(sum(tf.values()))
            for t in tf:
                df[t] += 1
        n = len(docs)
        avgdl = (sum(doc_len) / n) if n else 0.0
        idf = {
            t: math.log(1 + (n - c + 0.5) / (c + 0.5))
            for t, c in df.items()
        }
        return cls(doc_tf, doc_len, avgdl, idf, frozenset(df))

    def expand(self, terms: Iterable[str]) -> list[tuple[str, float]]:
        """Map query terms onto corpus vocabulary.

        - Exact vocab hit → weight 1.0.
        - Prefix hit: query term (length ≥ 4) that starts a longer vocab term,
          e.g. ``auth`` → ``authentication`` → weight 0.5.
        - Stem-family hit: query term and vocab term share a prefix of ≥ 5 and
          differ only in a short (≤ 3 char) suffix, e.g. ``authentication`` ↔
          ``authenticate`` → weight 0.5.
        Unknown terms are dropped.
        """
        out: list[tuple[str, float]] = []
        for t in terms:
            if t in self.vocab:
                out.append((t, 1.0))
                continue
            if len(t) < _MIN_STEM_LEN:
                continue
            for v in self.vocab:
                if len(v) > len(t) and v.startswith(t):
                    out.append((v, 0.5))
                    continue
                cpl = _common_prefix_len(t, v)
                if cpl >= 5 and (len(t) - cpl) <= 3 and (len(v) - cpl) <= 3:
                    out.append((v, 0.5))
        return out

    def score(self, doc_i: int, weighted_terms: list[tuple[str, float]]) -> float:
        tf = self.doc_tf[doc_i]
        dl = self.doc_len[doc_i]
        if not tf:
            return 0.0
        denom_norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * (dl / self.avgdl if self.avgdl else 0.0))
        total = 0.0
        for term, qw in weighted_terms:
            f = tf.get(term, 0.0)
            if not f:
                continue
            idf = self.idf.get(term, 0.0)
            total += qw * idf * (f * (_BM25_K1 + 1)) / (f + denom_norm)
        return total


# ── Built-in signals ─────────────────────────────────────────────────────────

@signal("bm25", weight=1.0)
def _signal_bm25(doc: FileDoc, ctx: ScoreContext) -> float:
    """Field-weighted BM25 of (query + discounted history) against the file."""
    if ctx.bm25 is None:
        return 0.0
    idx = ctx.bm25
    doc_i = ctx.extras["_doc_index"][doc.path]
    weighted = [(t, w) for t, w in idx.expand(ctx.query_terms)]
    weighted += [(t, w * _HISTORY_TERM_WEIGHT) for t, w in idx.expand(ctx.history_terms)]
    return idx.score(doc_i, weighted)


@signal("path_hit", weight=1.5)
def _signal_path_hit(doc: FileDoc, ctx: ScoreContext) -> float:
    """High-precision boost when a query term *is* a path segment / file stem.

    ``link "fix payments"`` should pin ``billing/payments.py`` even if BM25
    spreads weight across a dozen files that mention payments in passing.
    """
    path_terms = set(doc.fields.get("path", ()))
    stem = set(tokenize(Path(doc.path).stem))
    q = set(ctx.query_terms)
    return float(len(q & path_terms) + len(q & stem))


DEFAULT_SIGNALS: tuple[str, ...] = ("bm25", "path_hit")


# ── Propagators ──────────────────────────────────────────────────────────────
# A *propagator* runs after the per-document signals, once, over the whole
# ranked list. It exists for signals that are inherently corpus-global — the
# score of a document depends on the scores of *other* documents. Each
# propagator appends one SignalScore to every ScoredDoc.

Propagator = Callable[["list[ScoredDoc]", ScoreContext, float], None]

_PROPAGATORS: dict[str, tuple[Propagator, float]] = {}


def propagator(name: str, weight: float) -> Callable[[Propagator], Propagator]:
    def _register(fn: Propagator) -> Propagator:
        _PROPAGATORS[name] = (fn, float(weight))
        return fn
    return _register


DEFAULT_PROPAGATORS: tuple[str, ...] = ("import_graph",)

_GRAPH_SEED_COUNT = 5      # how many top-scored docs seed the walk
_GRAPH_HOP_DECAY = 0.5     # contribution multiplier per extra hop
_GRAPH_DEFAULT_HOPS = 2


def _resolve_import_target(target: str, paths_by_key: dict[str, str]) -> str | None:
    """Best-effort map an ``imports`` edge target onto a corpus file path.

    graperoot emits raw import tokens — ``hashlib``, ``src.db``, ``./util`` —
    that are not resolved to node ids. Try exact path, dotted-module → path,
    and bare-stem lookups against the known corpus.
    """
    if target in paths_by_key:
        return paths_by_key[target]
    dotted = target.replace(".", "/").strip("/")
    for cand in (dotted, dotted + "/__init__", target.replace("\\", "/").lstrip("./")):
        if cand in paths_by_key:
            return paths_by_key[cand]
    stem = re.split(r"[./\\]", target.strip("./\\"))[-1]
    return paths_by_key.get("stem:" + stem)


@propagator("import_graph", weight=1.2)
def _propagate_import_graph(ranked: list[ScoredDoc], ctx: ScoreContext, weight: float) -> None:
    """Boost files within N import-edge hops of a high-scoring seed file.

    Hop count comes from ``ctx.extras["graph_hops"]`` (default
    ``_GRAPH_DEFAULT_HOPS``); 0 disables. Edges are treated as undirected —
    relevance flows both from a caller to its imports and back.
    """
    hops = int(ctx.extras.get("graph_hops", _GRAPH_DEFAULT_HOPS))
    by_path = {sd.doc.path: sd for sd in ranked}

    def _emit_zero() -> None:
        for sd in ranked:
            sd.signals.append(SignalScore("import_graph", 0.0, weight))

    if hops <= 0 or not ctx.edges:
        _emit_zero()
        return

    # Index every doc path by the keys an import target might use.
    paths_by_key: dict[str, str] = {}
    for p in by_path:
        norm = p.replace("\\", "/")
        paths_by_key.setdefault(norm, p)
        paths_by_key.setdefault(norm.rsplit(".", 1)[0], p)  # drop extension
        stem = re.split(r"[/\\]", norm)[-1].rsplit(".", 1)[0]
        paths_by_key.setdefault("stem:" + stem, p)

    adj: dict[str, set[str]] = {p: set() for p in by_path}
    for e in ctx.edges:
        if not isinstance(e, dict) or e.get("rel") != "imports":
            continue
        src = str(e.get("from", "")).replace("\\", "/")
        src_path = paths_by_key.get(src) or paths_by_key.get(src.rsplit(".", 1)[0])
        dst_path = _resolve_import_target(str(e.get("to", "")), paths_by_key)
        if src_path and dst_path and src_path != dst_path:
            adj[src_path].add(dst_path)
            adj[dst_path].add(src_path)

    seeds = [sd.doc.path for sd in ranked[:_GRAPH_SEED_COUNT] if sd.total > 0]
    if not seeds:
        _emit_zero()
        return

    # Multi-source BFS: best (smallest) hop distance from any seed.
    dist: dict[str, int] = {s: 0 for s in seeds}
    frontier = list(seeds)
    for d in range(1, hops + 1):
        nxt: list[str] = []
        for p in frontier:
            for q in adj.get(p, ()):
                if q not in dist:
                    dist[q] = d
                    nxt.append(q)
        frontier = nxt
        if not frontier:
            break

    for sd in ranked:
        d = dist.get(sd.doc.path)
        raw = _GRAPH_HOP_DECAY ** (d - 1) if d and d >= 1 else 0.0
        sd.signals.append(SignalScore("import_graph", float(raw), weight))


# ── Ranking entry point ──────────────────────────────────────────────────────

def score_documents(
    docs: list[FileDoc],
    ctx: ScoreContext,
    *,
    signals: Iterable[str] | None = None,
    propagators: Iterable[str] | None = None,
    weights: dict[str, float] | None = None,
) -> list[ScoredDoc]:
    """Rank *docs* against *ctx*, best first.

    Fills the derived fields on *ctx* (``query_terms``, ``history_terms``,
    ``bm25``), evaluates each per-document signal, sorts, then runs the
    corpus-global propagators (which append their own contribution) and
    re-sorts. ``weights`` overrides individual signal/propagator weights;
    weight 0 skips a signal. Ties break on path for determinism.
    """
    active = tuple(signals) if signals is not None else DEFAULT_SIGNALS
    active_props = tuple(propagators) if propagators is not None else DEFAULT_PROPAGATORS

    ctx.query_terms = tokenize(ctx.query)
    ctx.history_terms = tokenize(ctx.history)
    ctx.bm25 = _Bm25Index.build(docs)
    ctx.extras["_doc_index"] = {d.path: i for i, d in enumerate(docs)}

    ranked: list[ScoredDoc] = []
    for d in docs:
        sscores: list[SignalScore] = []
        for name in active:
            fn, default_w = _REGISTRY[name]
            w = default_w if weights is None else weights.get(name, default_w)
            if w == 0:
                continue
            raw = float(fn(d, ctx))
            sscores.append(SignalScore(name, raw, w))
        ranked.append(ScoredDoc(d, sscores))

    ranked.sort(key=lambda sd: (-sd.total, sd.doc.path))

    for name in active_props:
        fn_p, default_w = _PROPAGATORS[name]
        w = default_w if weights is None else weights.get(name, default_w)
        if w == 0:
            continue
        fn_p(ranked, ctx, w)

    ranked.sort(key=lambda sd: (-sd.total, sd.doc.path))
    return ranked
