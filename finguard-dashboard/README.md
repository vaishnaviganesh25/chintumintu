# FinGuard Dashboard

The operator-facing surface for the FinGuard risk engine. It posts a transaction to
the Module 4 API (`../main.py`), renders the decision, and shows the SHAP evidence
behind it.

```bash
npm install
npm run dev          # http://localhost:5173
```

Start `python main.py` in the repository root first — the dashboard has no mock mode
and no fallback data. If the API is down, the header badge says so and names the
command to start it, which is the behaviour we want: a blank panel that silently
invents a score is worse than an honest error.

`VITE_API_BASE_URL` overrides the backend origin (default `http://localhost:8080`).
Copy `.env.example` to `.env.local` to change it.

## Layout

| Path | Role |
| --- | --- |
| `src/services/fraudApi.ts` | The only module that talks to the backend. Shape-checks every response before React sees it. |
| `src/hooks/useFraudSimulation.ts` | Owns the request lifecycle; aborts an in-flight call when a newer one starts so a stale verdict cannot paint over a fresh one. |
| `src/hooks/useApiHealth.ts` | Polls `/api/v1/health` every 15 s for the model name and live threshold. |
| `src/components/SHAPChart.tsx` | Diverging bar chart of signed per-concept contributions. |
| `src/components/RiskGauge.tsx` | Risk dial, coloured by the decision rather than a fixed percentage band. |
| `src/utils/validation.ts` | Client-side field rules, kept in step with the API's Pydantic validators. |

## Two rendering decisions worth knowing

**The SHAP chart is diverging, not a ranked list of percentages.** Real SHAP values
are signed and additive: red bars pushed the transaction towards fraud, green bars
argued against it, and together they sum to the model's output. That additivity is
what makes the chart an audit trail instead of a popularity ranking. Rendering it on
a 0–100% scale would silently drop every mitigating factor.

**The risk gauge takes its colour from the decision, not from the number.** The
engine ships a cost-calibrated threshold near 0.12, not 0.50, so a payment can be
blocked at 20% risk. A gauge that turned green below 40% would contradict the
BLOCKED badge directly above it, so the colour follows the verdict and the threshold
is printed underneath.

## Checks

```bash
npm run test:run     # unit + property-based tests (Vitest, fast-check)
npm run lint         # oxlint
npm run build        # tsc -b && vite build
```

Accessibility is audited at runtime: in dev builds `@axe-core/react` reports WCAG
violations to the browser console (`src/main.tsx`).
