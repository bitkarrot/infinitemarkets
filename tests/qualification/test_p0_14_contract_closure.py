"""P0-14: contract-closure gate (QUAL-14).

Reads docs/technical-specification.md at test time and diffs it BOTH
directions against harness/registry.py, harness/schema.py, and
harness/state.py:

- spec <-> registry: §5 routes, §7 state machines, §5.7 error codes,
  §10 task names, §12 settings, §21.25 identifiers, §6.8 NIP-32 namespace;
- registry <-> implementation: every registered field/state/transition is
  what the executable models actually declare, and neither schema.py nor
  state.py declares anything outside the registry;
- registry <-> fixtures: every Phase-1-required event kind has a golden
  fixture;
- §18 release gates: Release A carries no Release-B/C protocol kind;
- evidence closure: P0-01..P0-14 all carry recorded passing evidence —
  asserted over the plugin's LIVE in-session accumulator (never the
  serialized manifest, which is written only at session end), and only on
  unfiltered complete-profile runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from harness import authprobe, evidence, registry, schema, state

pytestmark = [pytest.mark.protocol, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (REPO_ROOT / "docs" / "technical-specification.md").read_text()
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "golden"


def _section(start: str, end: str) -> str:
    return SPEC[SPEC.index(start) : SPEC.index(end)]


SEC4 = _section("## 4.", "## 5.")
SEC5 = _section("## 5.", "## 6.")
SEC7 = _section("## 7.", "## 8.")
SEC10 = _section("## 10.", "## 11.")
SEC12 = _section("## 12.", "## 13.")
SEC18 = _section("## 18.", "## 19.")

#: registry machine name -> spec §7 subsection number.
MACHINE_SECTION = {"order": 1, "shipping": 2, "reservation": 3, "outbox": 4, "inbox": 5}

#: Transitions whose spec basis is prose rather than arrow notation; each is
#: gated on evidence substrings that MUST appear in the machine's §7 text.
PROSE_TRANSITIONS: dict[str, tuple[tuple[tuple[str, ...], frozenset], ...]] = {
    "shipping": (
        (
            ("`exception` is reachable", "`processing|shipped`"),
            frozenset({("processing", "exception"), ("shipped", "exception")}),
        ),
        (
            ("`exception` to `processing|shipped`",),
            frozenset({("exception", "processing"), ("exception", "shipped")}),
        ),
    ),
    "outbox": (
        (
            ("may become `superseded`",),
            frozenset(
                (s, "superseded")
                for s in registry.OUTBOX_SUPERSEDABLE_STATES
            ),
        ),
        (
            ("`pending` or `partially_published`", "fencing-token compare-and-swap"),
            frozenset({("claimed", "pending"), ("claimed", "partially_published")}),
        ),
    ),
}

_ROUTE_RE = re.compile(r"^([A-Z]+(?:\|[A-Z]+)*)\s+(/\S*)")
_ARROW_CHAIN_RE = re.compile(
    r"[a-z_]+(?:\s*[|,]\s*[a-z_]+)*(?:\s*→\s*[a-z_]+(?:\s*[|,]\s*[a-z_]+)*)+"
)
_CONT_RE = re.compile(r"[;`]\s*→\s*([a-z_|, ]+)")


def _spec_routes() -> set[str]:
    """Routes declared by §5's fenced ``text`` blocks.

    ``METHOD|METHOD /path[/{id}]`` expands per the REST convention the
    explicit §5.2 catalog/product lines establish: the bare collection path
    carries GET|POST, the ``/{id}`` member path carries GET|PATCH|DELETE.
    Query strings are not part of the route identity.
    """
    routes: set[str] = set()
    for block in re.findall(r"```text\n(.*?)```", SEC5, re.S):
        for line in block.splitlines():
            m = _ROUTE_RE.match(line.strip())
            if not m:
                continue
            methods = m.group(1).split("|")
            path = m.group(2).split("?", 1)[0]
            if "[/{id}]" in path:
                bare = path.replace("[/{id}]", "")
                item = path.replace("[/{id}]", "/{id}")
                for method in methods:
                    if method in ("GET", "POST"):
                        routes.add(f"{method} {bare}")
                    if method in ("GET", "PATCH", "DELETE"):
                        routes.add(f"{method} {item}")
            else:
                for method in methods:
                    routes.add(f"{method} {path}")
    return routes


def _names(segment: str) -> set[str]:
    return {
        n
        for n in (p.strip() for p in re.split(r"[|,]", segment))
        if n and n != "terminal"
    }


def _extract_transitions(subsection: str, *, fenced_only: bool) -> set[tuple[str, str]]:
    """Parse §7 arrow notation: ``a | b → c | d``, chains, and ``→ x``
    continuations that inherit the previous expression's head sources.
    ``terminal`` targets yield no edge (terminal states are already keyed
    with empty transition sets in the registry).
    """
    if fenced_only:
        text = "\n".join(re.findall(r"```text\n(.*?)```", subsection, re.S))
    else:
        text = subsection.replace("`", "")
    extracted: set[tuple[str, str]] = set()
    prev_sources: set[str] = set()
    for m in _ARROW_CHAIN_RE.finditer(text):
        segs = [_names(s) for s in m.group(0).split("→")]
        if not segs or not segs[0]:
            continue
        prev_sources = segs[0]
        for left, right in zip(segs, segs[1:]):
            extracted |= {(s, t) for s in left for t in right}
    for m in _CONT_RE.finditer(subsection):
        extracted |= {(s, t) for s in prev_sources for t in _names(m.group(1))}
    return extracted


def _machine_subsections() -> dict[int, str]:
    subs: dict[int, str] = {}
    for part in re.split(r"(?=### 7\.\d)", SEC7):
        m = re.match(r"### 7\.(\d)", part)
        if m:
            subs[int(m.group(1))] = part
    return subs


def _ddl_columns(table: str) -> set[str]:
    """Column names declared for ``table`` by the harness DDL."""
    cols: set[str] = set()
    for stmt in schema.ddl("sqlite", None):
        lines = stmt.splitlines()
        if not any(
            re.match(rf"\s*CREATE TABLE {re.escape(table)}\b", ln)
            for ln in lines
        ):
            continue
        inside = False
        for ln in lines:
            if "CREATE TABLE" in ln:
                inside = True
                continue
            if inside:
                if ln.strip().startswith(")"):
                    break
                tok = ln.strip().split(" ", 1)[0].rstrip(",")
                if re.fullmatch(r"[a-z_][a-z0-9_]*", tok):
                    cols.add(tok)
    return cols


# --- (a) spec <-> registry parity -----------------------------------------------


def test_routes_match_spec_bidirectional():
    spec_routes = _spec_routes()
    declared = set(registry.HTTP_ROUTES)
    assert not (spec_routes - declared), (
        f"spec routes missing from registry: {sorted(spec_routes - declared)}"
    )
    assert not (declared - spec_routes), (
        f"registry routes not declared by spec §5: {sorted(declared - spec_routes)}"
    )


def test_state_machines_match_spec_bidirectional():
    subs = _machine_subsections()
    for name, (states, transitions) in registry.STATE_MACHINES.items():
        sub = subs[MACHINE_SECTION[name]]
        extracted = _extract_transitions(sub, fenced_only=(name == "order"))
        declared = {
            (s, t) for s, tgts in transitions.items() for t in tgts
        }
        prose: set[tuple[str, str]] = set()
        for evidence_strings, edges in PROSE_TRANSITIONS.get(name, ()):
            for ev in evidence_strings:
                assert ev in sub, (
                    f"{name}: spec prose evidence missing for "
                    f"{sorted(edges)}: {ev!r}"
                )
            prose |= set(edges)
        spec_edges = extracted | prose
        assert not (spec_edges - declared), (
            f"{name}: spec transitions missing from registry: "
            f"{sorted(spec_edges - declared)}"
        )
        assert not (declared - spec_edges), (
            f"{name}: registry transitions without spec basis: "
            f"{sorted(declared - spec_edges)}"
        )
        for st in states:
            assert re.search(rf"\b{re.escape(st)}\b", sub), (
                f"{name}: registered state {st!r} absent from spec §7"
            )
        extracted_names = {n for edge in extracted for n in edge}
        assert extracted_names <= set(states), (
            f"{name}: undeclared states in spec arrows: "
            f"{sorted(extracted_names - set(states))}"
        )


def test_registered_literals_appear_in_spec():
    for code in registry.ERROR_CODES:
        assert code in SEC5, f"error code {code!r} not declared in §5.7"
    for task in registry.TASK_NAMES:
        if task == f"{registry.PACKAGE_NAME}_invoice_listener":
            # The host names registered invoice listeners
            # "<name>_invoice_listener" — verified against the pinned host in
            # P0-03; the spec carries the registration call, not the derived name.
            assert "register_invoice_listener" in SPEC
            assert f'name="{registry.PACKAGE_NAME}"' in SPEC
            continue
        assert task.startswith(f"{registry.PACKAGE_NAME}.")
        assert task.removeprefix(f"{registry.PACKAGE_NAME}.") in SEC10, (
            f"task {task!r} not declared in §10"
        )
    assert f"{registry.PACKAGE_NAME}.<task>" in SEC10
    for setting in registry.SETTINGS:
        assert setting in SEC12, f"setting {setting!r} not declared in §12"
    for ident in registry.FROZEN_IDENTIFIERS:
        assert ident in SPEC, f"frozen identifier {ident!r} absent from spec"
    assert registry.NIP32_NAMESPACE in _section("### 6.8", "### 6.9")


# --- (b) registry <-> schema/state parity ----------------------------------------


def test_section4_table_classification_complete():
    spec_tables: set[str] = set()
    for line in SEC4.splitlines():
        if re.match(r"### 4\.", line):
            spec_tables.update(re.findall(r"`([a-z_]+)`", line))
            continue
        m = re.match(r"^\s*-?\s*`([a-z_0-9]+)`\s*\((.*)", line)
        if m and re.search(r"\b(PK|FK|UNIQUE)\b", m.group(2)):
            # Table introductions carry key constraints; field enumerations
            # like "`state` (`pending|claimed|…`)" do not.
            spec_tables.add(m.group(1))
        spec_tables.update(re.findall(r"`([a-z_0-9]+)`:", line))
    declared = set(registry.TABLE_CLASSIFICATION)
    assert not (spec_tables - declared), (
        f"§4 tables missing from registry classification: "
        f"{sorted(spec_tables - declared)}"
    )
    legal = {
        registry.TABLE_MODELED,
        registry.TABLE_FK_SUBSET,
        registry.TABLE_NOT_MODELED,
    }
    assert set(registry.TABLE_CLASSIFICATION.values()) <= legal
    for table in declared:
        assert f"`{table}`" in SEC4, (
            f"registry table {table!r} has no §4 declaration"
        )


def test_schema_fields_match_registry_bidirectional():
    modeled = {
        t
        for t, c in registry.TABLE_CLASSIFICATION.items()
        if c == registry.TABLE_MODELED
    }
    assert set(schema.MODEL_TABLES) == modeled
    assert set(registry.SCHEMA_FIELDS) <= modeled
    for table in modeled:
        cols = _ddl_columns(table)
        declared = set(registry.SCHEMA_FIELDS[table])
        assert cols == declared, (
            f"{table}: ddl-only {sorted(cols - declared)} "
            f"registry-only {sorted(declared - cols)}"
        )


def test_state_tables_match_registry():
    for name, (states, transitions) in registry.STATE_MACHINES.items():
        assert tuple(getattr(state, f"{name.upper()}_STATES")) == tuple(states)
        assert getattr(state, f"{name.upper()}_TRANSITIONS") == transitions
    assert tuple(state.ORDER_TERMINAL_STATES) == tuple(
        registry.ORDER_TERMINAL_STATES
    )
    assert tuple(state.BUYER_CANCELLABLE_STATES) == tuple(
        registry.BUYER_CANCELLABLE_STATES
    )
    assert state.REASON_REQUIRED_TRANSITIONS == registry.REASON_REQUIRED_TRANSITIONS
    assert tuple(state.OUTBOX_SUPERSEDABLE_STATES) == tuple(
        registry.OUTBOX_SUPERSEDABLE_STATES
    )
    assert tuple(state.OUTBOX_NON_SUPERSEDABLE_AGGREGATES) == tuple(
        registry.OUTBOX_NON_SUPERSEDABLE_AGGREGATES
    )


# --- (c) transition completeness --------------------------------------------------


def test_transitions_classified_exhaustively():
    for name, (states, transitions) in registry.STATE_MACHINES.items():
        state_set = set(states)
        assert set(transitions) == state_set, (
            f"{name}: transition table is not total over declared states"
        )
        for src, targets in transitions.items():
            assert targets <= state_set, (
                f"{name}: {src} targets undeclared states "
                f"{sorted(targets - state_set)}"
            )
        legal = {(s, t) for s, tgts in transitions.items() for t in tgts}
        illegal = {
            (s, t) for s in state_set for t in state_set
        } - legal
        # every cell of the state x state matrix is classified
        assert len(legal) + len(illegal) == len(state_set) ** 2


# --- (d) fixture coverage ---------------------------------------------------------


def test_fixture_coverage_for_required_kinds():
    for kind, info in registry.EVENT_KINDS.items():
        if not info["phase1_required"]:
            continue
        path = FIXTURES / info["fixture"]
        assert path.is_file(), (
            f"kind {kind} requires golden fixture {info['fixture']}"
        )
    rec = json.loads(
        (FIXTURES / "nip89" / "recommendation_31989.json").read_text()
    )
    hdl = json.loads((FIXTURES / "nip89" / "handler_31990.json").read_text())
    d_rec = [t[1] for t in rec["tags"] if t[0] == "d"]
    d_hdl = [t[1] for t in hdl["tags"] if t[0] == "d"]
    # §6.5: 31989's d is the supported kind "30402"; the pair's d values
    # are intentionally different and golden fixtures must catch it.
    assert d_rec == ["30402"]
    assert d_hdl and set(d_rec).isdisjoint(d_hdl)


# --- (e) release scoping ------------------------------------------------------------


def test_release_gates_scope_event_kinds():
    release_a = registry.RELEASE_GATES["A"]
    assert release_a.isdisjoint(registry.RELEASE_A_EXCLUDED_KINDS)
    later = registry.RELEASE_GATES["B"] | registry.RELEASE_GATES["C"]
    assert later <= set(registry.EVENT_KINDS)
    assert registry.RELEASE_A_EXCLUDED_KINDS <= later
    assert release_a <= set(registry.EVENT_KINDS)
    for anchor in (
        "Release A",
        "Release B",
        "Release C",
        "kind-10050",
        "kind-17",
        "30017/30018",
        "NIP-04",
        "NIP-17",
        "30402/30405/30406",
    ):
        assert anchor in SEC18, f"§18 release-gate anchor {anchor!r} missing"


# --- (f) identifier closure ---------------------------------------------------------


def test_identifier_closure():
    harness_src = "\n".join(
        p.read_text() for p in sorted((REPO_ROOT / "harness").glob("*.py"))
    )
    qual_src = harness_src + "\n" + "\n".join(
        p.read_text()
        for p in sorted((REPO_ROOT / "tests" / "qualification").glob("*.py"))
    )
    # frozen identifiers are exercised by the harness, not just declared
    assert registry.PAYMENT_CORRELATION_PREFIX in harness_src
    assert registry.ROUTE_PREFIX in harness_src
    assert registry.ENV_PREFIX in harness_src
    # no undeclared variant spelling of the frozen runtime identifier
    # (post-rebrand only the canonical spelling may appear in these trees)
    variants = {
        m.lower()
        for m in re.findall(r"(?i)(?:gamma|infinite)[-_ ]?markets?", qual_src)
    }
    assert variants == {"infinitemarkets"}, (
        f"variant runtime-identifier spellings present: {sorted(variants)}"
    )


# --- (h) topology ---------------------------------------------------------------------


def test_topology_refusal_registered():
    sec14_normalized = " ".join(_section("## 14.", "## 15.").split())
    assert "CockroachDB and multi-process SQLite" in sec14_normalized
    evaluate = authprobe.evaluate_production_topology
    assert evaluate("sqlite", 1).allowed
    assert evaluate("postgresql", 4).allowed
    assert not evaluate("sqlite", 2).allowed
    assert not evaluate("cockroachdb", 1).allowed
    assert not evaluate("", 1).allowed


# --- (g) evidence closure — complete-profile runs only ---------------------------------
#
# This MUST remain the last test in the module: collection order places it
# after every other test here (and this module sorts after every other
# qualification module), so the live accumulator is complete when it runs.
# Any -m/-k selection means the accumulator cannot hold complete P0
# coverage, so the assertion self-skips — reported as skipped, never as
# passed.


def test_p0_evidence_closure(evidence_results):
    selection = evidence_results["selection"]
    beyond_defaults = set(selection["file_or_dir"]) - set(selection["testpaths"])
    if selection["markexpr"] or selection["keyword"] or beyond_defaults:
        pytest.skip(
            "subset run: complete P0-01..P0-14 evidence is only assertable "
            "on the unfiltered complete profile"
        )
    coverage = dict(evidence_results["p0_coverage"])
    node = evidence_results["current_nodeid"]
    p14 = dict(coverage["P0-14"])
    if node not in p14["tests"]:
        p14["tests"] = p14["tests"] + [node]
        if p14["status"] == "pending":
            p14["status"] = "pass"
        coverage["P0-14"] = p14
    not_passing = {
        p0: info["status"] for p0, info in coverage.items() if info["status"] != "pass"
    }
    assert not not_passing, (
        f"P0 criteria without complete passing evidence: {not_passing}"
    )
    results = evidence_results["results"] + [
        {"nodeid": node, "outcome": "passed", "p0": "P0-14"}
    ]
    for p0 in evidence.P0_IDS:
        p0_results = [r for r in results if r["p0"] == p0]
        assert any(r["outcome"] == "passed" for r in p0_results), (
            f"{p0} has no recorded passing test in this session"
        )
