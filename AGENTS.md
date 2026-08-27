# AGENTS.md

Orientation for coding agents and automated reviewers. Humans want [README.md](README.md);
this file is the short, structural version, plus the things about this repository that
are surprising enough to get wrong on a first pass.

## What this is

A merchant-side payment fraud engine: it scores a UPI/card payment, prices the three
actions a gateway can take, explains the decision, records it, and keeps working when
the model is unavailable. Python 3.13 + FastAPI on the backend, React 19 + Vite for the
console.

There is no package layout. The modules sit at the repository root and import each
other flatly; `pyproject.toml` therefore carries tool configuration only, with no
`[project]` table and no build backend, because `pip install .` would not work and
should not look like it might.

## Commands

```bash
# Everything, in containers
docker compose up --build            # dashboard :5173, API :8080

# Python, from source
pip install -r requirements.txt -r requirements-dev.txt
python generate_upi_dataset.py       # ~30 s   -> upi_synthetic_data.csv
python train_model.py                # ~110 s  -> models/, reports/
python explain_model.py              # ~100 s  -> reports/explanations/
python main.py                       # serves on :8080

# Checks
pytest                               # full suite
pytest -m "not slow"                 # the part that needs no model artifacts
ruff check .                         # lint; must be clean
python verify_claims.py              # README numbers vs shipped artifacts
python -m bandit -q -r . -x ./finguard-dashboard,./tests
python -m pip_audit -r requirements.txt

# Dashboard
cd finguard-dashboard
npm install && npm run dev           # :5173
npm run test:run && npm run lint && npm run build
```

## Layout

| Path | Role |
| --- | --- |
| `generate_upi_dataset.py` | Seeded synthetic generator. Deterministic - re-running reproduces the same CSV. |
| `train_model.py` | Feature engineering, model selection, threshold calibration, ablations. Writes `models/` and `reports/`. |
| `explain_model.py` | TreeSHAP, aggregated to concepts. Imported by the API for per-request explanations. |
| `merchant_policy.py` | The cost model. Prices ACCEPT / STEP_UP / HOLD; owns the step-up budget and the dispute covenant. |
| `graph_features.py` | Sliding-window fan-in/fan-out and exponentially decayed collection velocity. |
| `network_signals.py` | Cross-merchant reputation, applied as a runtime overlay - never a model feature. |
| `degradation.py` | Four-rung fallback ladder used when the model cannot answer. |
| `audit_store.py` | Append-only SQLite ledger of decisions, dispositions and disputes. |
| `razorpay_client.py` | Razorpay-shaped dispute entities and evidence; paise conversion. |
| `chargeback_agent.py` | Representment packets. LLM-drafted where a provider is configured, deterministic otherwise. |
| `main.py` | FastAPI app. The only module that wires the others together. |
| `verify_claims.py` | Re-derives README numbers from artifacts and fails on drift. |
| `tests/` | pytest, including Hypothesis property tests. |
| `finguard-dashboard/` | React 19 + Vite + Tailwind v4 console. Vitest + Testing Library. |

## Things that are easy to get wrong here

**The threshold does not choose the action.** `optimal_threshold` produces the legacy
block/allow `status` field. The action comes from `merchant_policy` pricing all three
options and taking the cheapest, which `network_signals` may then escalate. Code or copy
that treats the threshold as a "hold line" is wrong, and has been wrong here before.

**`engineer_features` is called from three places** - training, the explainer, and the
API scoring a single live row. If they ever disagree about what a column means, nothing
raises; the model just scores against a slightly different feature space than it was fit
on. This is why `tests/test_features.py` is as heavy as it is.

**Graph features must never read forward in time.** Every window is backward-looking.
`tests/test_graph_features.py` exists mostly to hold that line.

**The split is grouped on `ring_id`, deliberately.** Both legs of a ₹1 probe belong to
one incident and must land on the same side of the train/test boundary. Setting
`GROUP_AWARE_SPLIT = False` reproduces the leaky behaviour and flatters every metric.

**Fallbacks never invent a probability.** A degraded verdict carries `degraded: true`,
names its rung, and records `-1.0` rather than a plausible-looking score.

**Amounts are paise as integers** at the Razorpay boundary, rupees as floats internally.
`to_paise` / `to_rupees` are the only crossing points.

## Conventions

- **Comments say why, not what.** The existing density is deliberate - match it. A
  comment restating the line below it is worse than none.
- **Tests are named as sentences** describing the behaviour they pin, not
  `test_function_name_1`.
- **No emoji in product surfaces.** The console uses a hand-drawn icon set
  (`finguard-dashboard/src/components/Icon.tsx`, `Marks.tsx`); add to it rather than
  reaching for an emoji or a copied brand asset.
- **No hardcoded colours in the dashboard.** Everything resolves through CSS custom
  properties in `index.css` so both themes survive. `grep -rE "bg-(gray|red|green)-[0-9]" src/`
  must stay empty.
- **Line length 120**, enforced by ruff. The code habitually sits near 90; 120 is the
  ceiling, not the target.

## Before you claim you are done

1. `ruff check .` is clean.
2. `pytest` passes - the full suite, not just the fast half.
3. `npm run test:run && npm run build` pass in `finguard-dashboard/`.
4. `python verify_claims.py` passes if you touched the README or retrained.
5. If you changed `merchant_policy`, `train_model` or the feature code, retrain before
   quoting any number - `models/` and `reports/` are committed artifacts and the README
   is checked against them.

## Boundaries

- Do not commit `.env`, model binaries beyond what is already tracked, or anything under
  `data/`.
- Do not add a dependency without checking it against the bounds note in
  `requirements.txt`: SHAP needs numba, numba caps numpy, and pandas 3.x with numpy 2.4
  segfaults on `.loc`. That combination is load-bearing.
- The LLM is deliberately kept out of the retrieval and scoring paths. It drafts
  representment prose from a case file that was assembled deterministically. Keep it
  there.
