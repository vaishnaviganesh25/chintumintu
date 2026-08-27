"""The image has to carry every module the thing it runs actually imports.

The Dockerfile enumerates its `COPY` lists rather than globbing `*.py`, so that editing
the API does not invalidate the four-minute train in the builder stage. That is a
deliberate trade, and it failed in the obvious way: `graph_features`, `network_signals`
and `razorpay_client` each joined the import graph in a later commit, none was added to
the Dockerfile, and `docker build` died on `import graph_features` for three commits
before anyone looked at the red tick.

Nothing in the fast suite could catch it, because the only thing that exercised the
COPY lists was a Docker build that takes minutes and only runs on main. These tests
walk the import graph statically instead, so the failure lands in the same second as
the omission.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"

#: Modules that live at the repository root - anything else is a third-party package
#: installed from requirements.txt and is not our problem here.
FIRST_PARTY = {p.stem for p in ROOT.glob("*.py")}


def _first_party_imports(module: str) -> set[str]:
    """The first-party modules `module` imports directly."""
    tree = ast.parse((ROOT / f"{module}.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        # `level` guards against relative imports, which cannot reach a root module.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names & FIRST_PARTY


def _closure(*entrypoints: str) -> set[str]:
    """Every first-party module reachable from `entrypoints`, including themselves."""
    seen: set[str] = set()
    stack = list(entrypoints)
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        stack.extend(_first_party_imports(module) - seen)
    return seen


def _copied_per_stage() -> dict[str, set[str]]:
    """Root-level Python modules each build stage copies in.

    A `COPY *.py` is recorded as the sentinel `"*"`, which satisfies any requirement -
    a glob cannot fall behind the import graph.
    """
    text = DOCKERFILE.read_text(encoding="utf-8")
    # Fold line continuations so a multi-line COPY reads as one instruction.
    text = re.sub(r"\\s*\n\s*", " ", text)

    stages: dict[str, set[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.upper().startswith("FROM "):
            match = re.search(r"\bAS\s+(\S+)", line, re.IGNORECASE)
            current = match.group(1).lower() if match else None
            if current:
                stages.setdefault(current, set())
        elif line.upper().startswith("COPY ") and current:
            # Drop flags (--from=builder) and the trailing destination.
            parts = [p for p in line.split()[1:] if not p.startswith("--")]
            for source in parts[:-1]:
                if source == "*.py":
                    stages[current].add("*")
                elif source.endswith(".py"):
                    stages[current].add(Path(source).stem)
    return stages


def _assert_stage_is_complete(stage: str, *entrypoints: str) -> None:
    copied = _copied_per_stage().get(stage)
    assert copied is not None, f"no `AS {stage}` stage in the Dockerfile"
    if "*" in copied:
        return
    missing = _closure(*entrypoints) - copied
    assert not missing, (
        f"the `{stage}` stage runs {', '.join(entrypoints)} but never copies "
        f"{', '.join(sorted(missing))} - `docker build` will fail on the import. "
        f"Add the file(s) to that stage's COPY list."
    )


def test_builder_stage_carries_what_it_trains_with():
    # These three are the RUN line in the builder stage.
    _assert_stage_is_complete(
        "builder", "generate_upi_dataset", "train_model", "explain_model"
    )


def test_runtime_stage_carries_what_the_api_imports():
    # `CMD ["python", "main.py"]`.
    _assert_stage_is_complete("runtime", "main")


def test_the_guard_would_have_caught_the_bug_it_was_written_for():
    """A stage missing a transitive import must fail, not pass quietly.

    Without this, a bug in the parser above would make both tests vacuously green -
    which is exactly the failure mode that let the original omission through.
    """
    assert "graph_features" in _closure("train_model"), (
        "train_model no longer imports graph_features; this guard needs rewriting "
        "against whatever replaced it."
    )
    assert _first_party_imports("main") >= {"graph_features", "network_signals",
                                            "razorpay_client"}


@pytest.mark.parametrize("stage", ["builder", "runtime"])
def test_every_copied_module_actually_exists(stage):
    """A COPY naming a deleted module fails the build just as hard as a missing one."""
    copied = _copied_per_stage()[stage] - {"*"}
    absent = {m for m in copied if not (ROOT / f"{m}.py").exists()}
    assert not absent, f"the `{stage}` stage copies files that no longer exist: {absent}"
