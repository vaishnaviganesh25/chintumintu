# Security

FinGuard scores payments and stores decisions about them, so the security posture is
part of the product rather than a footnote to it. This is what the project does and does
not defend against, and how to report something.

## Reporting

Open a private security advisory through GitHub's **Security → Report a vulnerability**
on this repository. Please do not open a public issue for anything exploitable.

## What is checked, and where

| Check | Tool | Runs |
| --- | --- | --- |
| Source security lint | `bandit`, plus ruff's `S` ruleset | every push |
| Dependency vulnerabilities | `pip-audit`, `npm audit` | every push |
| Secrets in the tree | `.gitignore` + review | every push |

```bash
python -m bandit -q -r . -x ./finguard-dashboard,./tests
python -m pip_audit -r requirements.txt
ruff check .                      # the S rules are part of the selected set
```

Two `bandit` findings are suppressed deliberately, both with the reasoning recorded at
the call site:

- **B608 / S608 in `audit_store.py`** — the alert-queue query interpolates a *generated
  run of `?` placeholders* and a constant `WHERE` clause. No value is interpolated; the
  decision literals, the limit and the offset are all parameter-bound. Suppressed per
  file in `pyproject.toml` because the query spans several lines and an inline `# noqa`
  would land inside the SQL string itself.
- **B104 / S104 in `main.py`** — binding `0.0.0.0` is intentional. A container that binds
  loopback is unreachable from outside itself. Override with `FINGUARD_HOST` when running
  on a host directly.

## Data handling

- **The dataset is synthetic.** `generate_upi_dataset.py` produces every VPA, name and
  amount from a seeded generator. No real payment data is in this repository, and none
  should be added to it.
- **The ledger is append-only.** `audit_store.py` has no update or delete path for a
  recorded decision; a disposition is a new row, not an edit. That is deliberate: an
  audit trail that can be rewritten is not one.
- **Decisions are retained indefinitely** in `data/finguard_audit.db`, which is
  gitignored and mounted as a named volume in `docker-compose.yml`. A real deployment
  needs a retention policy matched to its jurisdiction; this project does not impose one.
- **Explanations quote transaction fields** — VPAs, amounts, timestamps. Anything that
  reads the ledger or the representment packets is handling payment data.

## Secrets

- Configuration is environment-only. `.env.example` documents the variables; `.env` is
  gitignored and has never been committed — verified against the full object history.
- **No key is required to run anything.** The chargeback responder falls back to a
  deterministic packet when no LLM provider is configured, so the whole system works with
  an empty environment.
- If you set `GEMINI_API_KEY` (or another provider key), it is read at call time and
  never logged, never written to the ledger, and never included in a representment
  packet.

## The threat model this does not cover

Worth stating plainly, because a fraud-detection project invites the assumption that it
is hardened:

- **No authentication or authorisation.** Every endpoint is open. This is a demonstrable
  engine, not a multi-tenant service; putting it on a public network without a gateway in
  front would expose the ledger and the kill switch to anyone.
- **No rate limiting.** The scoring endpoint will happily be used as an oracle to probe
  the model's decision boundary.
- **`/api/v1/chaos` and the model kill switch are unguarded** and exist to demonstrate
  the degradation ladder. They are gated behind `FINGUARD_ENABLE_CHAOS` and must stay off
  anywhere real.
- **Adversarial robustness is out of scope.** The model is not defended against evasion
  by an attacker who can query it repeatedly; the graph and reputation layers raise the
  cost of evasion but do not close it.
- **Cross-merchant reputation is simulated.** `network_signals.py` reads a local store,
  not a real consortium feed. A real one carries its own privacy and data-sharing
  obligations that this project does not model.
