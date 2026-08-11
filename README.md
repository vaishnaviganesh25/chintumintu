# FinGuard — Real-Time UPI Fraud Detection and Explainable AI

| Module | Script | Output |
| --- | --- | --- |
| 1. Synthetic data | `generate_upi_dataset.py` | `upi_synthetic_data.csv` |
| 2. ML engine | `train_model.py` | `models/`, `reports/` |
| 3. Explainable AI | `explain_model.py` | `reports/explanations/` |
| 4. REST API | `main.py` | FastAPI service on port 8080 |
| 5. Dashboard | `finguard-dashboard/` | React + Vite UI on port 5173 |
| — serving check | `predict_example.py` | console demo of the scoring path |

```bash
pip install -r requirements.txt
python generate_upi_dataset.py    # ~30 s
python train_model.py             # ~110 s
python explain_model.py           # ~100 s
python predict_example.py         # verifies the saved artifacts round-trip
python main.py                    # serves the API on http://localhost:8080
```

> **Environment warning.** The numpy and pandas bounds in `requirements.txt` are
> load-bearing. SHAP needs numba, numba caps numpy below 2.5, and pandas 3.x with
> numpy 2.4 **segfaults** on ordinary `.loc` indexing — a hard process crash rather
> than an exception. pandas 2.3 + numpy 2.4 is the coherent combination. Do not
> raise those upper bounds without rerunning all three modules end to end.

---

# Module 1 — Synthetic UPI Transaction Dataset

A seeded generator that produces 100,000 realistic Indian UPI transactions with 0.5%
fraud, injected as three scam patterns actually seen in the Indian payments ecosystem.

Real UPI data is confidential, so this stands in as a faithful substitute for
model development, threshold tuning, and SHAP/LIME explainability work.

## Setup

```bash
python generate_upi_dataset.py
```

Runtime is roughly 30 seconds and the output is `upi_synthetic_data.csv` (~13 MB).
`SEED = 42` makes every run byte-identical; change it for a fresh sample.

## Schema

| Column | Type | Description |
| --- | --- | --- |
| `transaction_id` | str | Unique UUID4. |
| `timestamp` | datetime | Rows are sorted ascending, so the file can be replayed as a stream. |
| `sender_vpa` | str | Payer handle: `firstname.lastname@okicici` or `9876543210@ybl`. |
| `receiver_vpa` | str | Payee handle: QR terminals (`q53337100@icici`), businesses (`raju.kirana@okbizaxis`), billers, or peers. |
| `sender_city` | str | Home city of the payer, constant per sender (Faker `en_IN`, weighted towards metros). |
| `amount` | float | INR. |
| `receiver_vpa_age_days` | int | Age of the payee VPA **at transaction time**, 0–1000. Derived from a per-VPA creation date, so a VPA correctly ages across the window. |
| `time_since_last_txn_sec` | int | Seconds since that sender's previous transaction; `-1` for their first row in the dataset. |
| `is_fraud` | int | Target: 0 legitimate, 1 fraud. |
| `fraud_pattern` | str | Which scam produced the row (`none` for legitimate). |

> **Drop `fraud_pattern` before training.** It is a label-derived column, kept only
> so you can score recall per scam type and check what the explainer attributes to each.

## Legitimate behaviour (99,500 rows)

- **70% micro-payments, ₹10–₹500** — chai, autos, kirana stores; clustered on round
  values (₹10/₹20/₹50/₹100/₹200) the way real UPI spending is.
- **30% higher value, ₹1,000–₹15,000** — rent, utilities, EMIs, dining.
- **Hour-of-day intensity curve** peaking 09:00–21:00 and nearly flat 01:00–04:00,
  which is what gives the odd-hour fraud signature its contrast (~1.2% of legitimate
  traffic falls in the 01:00–04:00 window).
- Senders and receivers are drawn with gamma-distributed weights, so a few accounts
  are much busier than the rest instead of everything being uniform.
- **~6% of legitimate traffic goes to newly onboarded receivers** — 1,000 VPAs created
  *during* the window (a friend who just installed the app, a vendor registering a QR
  code). Payments cluster in the first days after signup, so roughly 4,500 legitimate
  rows land on a receiver 2 days old or younger. See below for why this matters.

## Fraud signatures (500 rows, 0.5%)

| Pattern | Rows | Signature |
| --- | --- | --- |
| `rupee_1_test` | 200 (100 incidents × 2 legs) | Exactly ₹1 to "verify the account", then ₹10,000+ to the **same** receiver within 12–60 seconds. Both legs are labelled fraud. |
| `new_vpa_velocity` | 150 (30 mules × 5) | A mule VPA with `receiver_vpa_age_days = 0` collects 5 transfers of ₹15,000–₹90,000 from 3 victims inside minutes; two victims send twice ("the refund failed, send again"). |
| `odd_hour_phishing` | 150 | ₹20,000+ between 01:00 and 04:00 to a recently created VPA — credential compromise or a screen-sharing scam draining an account overnight. |

## Deliberate class overlap

The generator plants legitimate rows that *look* suspicious on a single feature, so
the labels are not separable by one threshold:

- ~290 genuine ₹1–₹5 test transfers with **no** high-value follow-up. Only the
  ₹1-then-₹10,000 *pair* is fraudulent, not the ₹1 itself.
- ~1,110 genuine payments at or above ₹15,000 (deposits, college fees, jewellery),
  overlapping the fraud amount range.
- ~2,490 legitimate payments to VPAs that are 0 days old, ~4,515 to VPAs 2 days or
  younger.
- ~235 of those new-VPA payments are also ₹15,000+ — a deposit to a landlord who just
  opened a VPA, a second-hand bike off a classifieds listing.
- ~90 legitimate bursts under 60 seconds apart.

Tune with `LEGIT_TINY_PROBE_SHARE`, `LEGIT_BIG_TICKET_SHARE`, `NEW_ADOPTER_TXN_SHARE`
and `NEW_ADOPTER_BIG_TICKET_SHARE`; set them to `0.0` for a strictly clean split.

### Why the new-VPA overlap is sized the way it is

The first version of this generator made `receiver_vpa_age_days` a giveaway: every
fraudulent receiver was 0–20 days old and almost every legitimate one was 150+, so
"the receiver is new" was close to a complete answer. SHAP confirmed the model had
noticed, and the ablation showed how much of the headline score rested on that one
column. A model trained that way learns the artefact rather than the behaviour.

Two layers fix it, and the run report measures both:

| Rule a lazy model might learn | Precision on this data |
| --- | --- |
| receiver ≤ 20 days old | 7.1% |
| receiver ≤ 2 days old | 6.3% |
| receiver ≤ 20 days old **and** amount ≥ ₹15,000 | 62.4% |

The first layer is volume — enough ordinary micro-payment traffic to new accounts
that age alone is a hint, not a verdict. The second is the big-ticket tail, without
which closing the age gap merely moves the shortcut to "new receiver *and* large
amount". What still separates the classes is shape rather than any single value: a
burst of transfers to one fresh account, a ₹1 probe followed by a large leg seconds
later, ₹20,000 moving at 3 AM.

Every run prints a validation report covering row counts, the fraud rate, per-pattern
integrity checks, these overlap counts, and the precision table above.

## Notes and limitations

- Amounts are capped at ₹99,999 for fraud and ₹200,000 for legitimate big-ticket
  payments, in line with UPI per-transaction limits.
- Because fraud is injected by construction, a model trained here learns *these three*
  patterns. Treat strong metrics as a check that the pipeline and explanations work,
  not as evidence of real-world detection performance.
- Fraud is spread uniformly across the 30 days; there is no campaign burstiness,
  device/IP context, or transaction-declined history yet — natural next extensions.

---

# Module 2 — Predictive ML Engine

`train_model.py` engineers features, trains and compares XGBoost against Random
Forest, calibrates a decision threshold, and serialises the winner for real-time
scoring. Everything it prints is also written to `reports/evaluation_report.txt`.

## Pipeline

1. **Feature engineering** — 33 features from 6 raw columns: temporal
   (`hour_of_day`, `day_of_week`, `is_night_txn`, cyclical hour encoding), amount
   (raw, log, micro-payment and round-number flags), receiver reputation (VPA age,
   new/recent flags), velocity (`time_since_last_txn_sec`, `is_rapid_txn`,
   `is_first_txn`), VPA structure (bank handle, mobile-number VPA, merchant-like
   pattern, suspicious keywords, digit ratio), and backward-looking lags
   (`prev_amount`, `same_receiver_as_prev`) that let the model see the ₹1-test *pair*.
2. **Preprocessing** — a `ColumnTransformer` with median imputation plus
   `RobustScaler` for numerics (UPI amounts are heavy-tailed; `StandardScaler` would
   let a few ₹2 lakh transfers squash the entire ₹10–500 cluster), passthrough for
   binaries, and `OneHotEncoder(min_frequency=50)` for handles and cities.
3. **Models** — XGBoost with `scale_pos_weight ≈ 199` and `aucpr` early stopping;
   Random Forest with `class_weight='balanced_subsample'`.
4. **Selection** — 5-fold cross-validated PR-AUC. A single split holds only ~80–100
   positives, where both models score a saturated 1.0000 and the comparison is a
   coin flip; cross-validation pools ~400 positives and separates them cleanly.
5. **Threshold calibration** — on out-of-fold probabilities, never the test set.
6. **Artifacts** — `models/` and `reports/`.

## Splits

Stratified **64 / 16 / 20** train / validation / test. The validation slice does the
two jobs that must never touch the test set: XGBoost early stopping and threshold
calibration. Calibrating a threshold on the rows you then report it on is the most
common way fraud projects overstate their precision.

## Results

Random Forest wins on cross-validated PR-AUC and is the shipped model.

| Model | PR-AUC (CV) | PR-AUC (test) | ROC-AUC (test) | F1 (test) |
| --- | --- | --- | --- | --- |
| Random Forest | **0.9873 ± 0.0043** | 0.9955 | 1.0000 | 0.9495 |
| XGBoost | 0.9872 ± 0.0046 | 0.9946 | 1.0000 | 0.9596 |

The two models are now within one standard deviation of each other, which is the
honest picture; the earlier run separated them only because the data was easy enough
that Random Forest scored a literal 1.0000 in every fold.

Recall by scam signature at the shipped threshold: 100% on all four legs (new-VPA
velocity, odd-hour phishing, and both legs of the ₹1 test), at 67% precision.

## Three findings worth reading before trusting those numbers

**Account age is a strong feature, but no longer a shortcut.** `receiver_vpa_age_days`
and its derivatives are still the largest single block of importance, and they should
be — every fraudulent receiver in this data really is 0–20 days old. What changed is
that Module 1 now routes ~6% of legitimate traffic to brand-new VPAs, so the rule
"receiver is new" is only ~7% precise on its own and the amount-plus-age pair tops out
at 62%. The built-in ablation retrains without the age features: PR-AUC falls
0.9955 → 0.9520 and recall 1.00 → 0.92. **That lower number is the better guide to
real-world behaviour**, where account age is noisy and often missing.

**Scam incidents straddle the train/test boundary.** A stratified random split cuts
through incidents: the ₹1 probe can land in train while its large follow-up lands in
test, and one mule VPA gets scattered across both. 59% of test fraud rows share a
receiver with training fraud. Recall is currently 100% on both warm and cold
receivers, so the effect is not visible in this run — but it is a property of the
split, not of the model, and a `GroupKFold` on `receiver_vpa` would remove it.

**The obvious threshold policy is not the profitable one here.** "Maximise precision
subject to recall ≥ 90%" is the natural reading of the requirement, but the 90% floor
sits below what this model achieves, so the rule is free to climb the threshold and
trade fraud for precision. Out-of-fold it buys +27 points of precision and 168 fewer
alarms by letting **35 of 400 fraud rows through**. Charging each missed fraud its
actual amount and each false alarm a ₹150 review, that is ₹824,550 of expected loss
against ₹27,450 for the cost-minimising point — a 30× difference.

`train_model.py` therefore implements both rules and ships the cost-minimising one
(`THRESHOLD_POLICY = "cost"`). Set it to `"precision_at_recall"` for the literal
policy; the report prints both either way, so the trade-off is always visible.
Raising `TARGET_RECALL` closer to what the model can actually deliver has much the
same effect as switching policy.

## Artifacts

| File | Contents |
| --- | --- |
| `models/finguard_xgboost.joblib` | XGBoost pipeline (preprocessor + classifier) |
| `models/finguard_random_forest.joblib` | Random Forest pipeline |
| `models/finguard_best_model.joblib` | The selected winner — load this one |
| `models/preprocessor.joblib` | Fitted `ColumnTransformer` on its own |
| `models/model_config.json` | Threshold, feature names, all metrics, environment versions, timestamp |
| `reports/evaluation_report.txt` | The full printed report |
| `reports/pr_roc_curves.png` | PR and ROC curves, both models |
| `reports/threshold_calibration.png` | Precision/recall/F1 against threshold |
| `reports/confusion_matrices.png` | Default versus calibrated |
| `reports/feature_importance.png` | Top 20 features |

## Scoring a transaction (Module 3)

`engineer_features` is a pure, label-free function and everything else sits behind a
`__main__` guard, so importing the module does not retrain anything.

```python
import json, joblib, pandas as pd
from train_model import engineer_features

pipeline = joblib.load("models/finguard_best_model.joblib")
config = json.load(open("models/model_config.json"))

probability = pipeline.predict_proba(engineer_features(txn_df))[:, 1]
blocked = probability >= config["optimal_threshold"]
```

`predict_example.py` runs exactly this path and checks the reloaded artifact
reproduces training-time behaviour.

Two of the features (`time_since_last_txn_sec`, `prev_amount`) need the sender's
previous transaction, so a live deployment needs a sender-history lookup — a feature
store or a keyed cache. They are strictly backward-looking, so they are valid in a
streaming context; they are not free.

---

# Module 3 — Explainable AI

`explain_model.py` turns the classifier from a score into a defensible decision, at
three levels of audience.

**Concept aggregation.** The feature matrix contains `amount` and `log_amount`, and
four separate encodings of receiver VPA age. Raw SHAP splits credit between
correlated columns, which understates the true importance of the underlying fact and
produces output like *"flagged because of the amount, and the amount"*. This module
sums contributions within a concept first — valid precisely because SHAP is additive
— so each real-world fact speaks exactly once.

**1. Global.** Which concepts drive the model, and in which direction:

| Concept | Mean abs SHAP | Direction |
| --- | --- | --- |
| age of the receiving UPI ID | 0.180 | higher → safer |
| transaction amount | 0.178 | higher → riskier |
| gap since the sender's previous payment | 0.028 | higher → safer |
| jump in size versus the previous payment | 0.025 | higher → riskier |
| time of day | 0.025 | higher → safer |
| receiver looks like a registered merchant | 0.025 | higher → safer |

**2. Per scam signature.** The check that matters most for this project — is each
Indian scam caught *for the reason it is supposed to be*? Average contributions say
yes, and each pattern has a distinct fingerprint:

- **new-VPA velocity** → receiver age (+0.26), amount (+0.17), repeat receiver (+0.03)
- **odd-hour phishing** → amount (+0.19), time of day (+0.11), 1–4 AM flag (+0.09)
- **₹1-test large leg** → receiver age (+0.15), gap since previous payment (+0.13),
  repeat receiver (+0.08), amount (+0.07)
- **₹1-test probe leg** → receiver age (+0.25), amount (+0.12), non-merchant receiver (+0.04)

The large leg is the interesting one: gap-since-previous-payment and repeat-receiver
together now outweigh both age and amount, meaning the model reconstructs the *pair* —
₹13,500 landing 43 seconds after a ₹1 payment to the same receiver — rather than
reacting to the size of the transfer. That is the scam's actual definition, learned
rather than hard-coded, and it is the behaviour that survived hardening Module 1.

**3. Local, with plain-English reason codes.** Every flagged transaction gets a
waterfall chart for the audit trail and a text explanation for humans, both generated
from one explanation so they cannot drift apart:

```
odd_hour_phishing   8266605706@ibl -> girindra.bhat@ybl
Rs.25,393.08 at 25 Jul 2026, 03:45 | receiver VPA 9 days old
Fraud probability 0.9922 -> BLOCK
Flagged because:
  + transaction amount (Rs.25,393)
  + time of day (03:45)
  + sent between 1 AM and 4 AM (03:45)
Argued against by:
  - size of the sender's previous payment (Rs.87)
  - repeat payment to the same receiver (no)
```

Only risk-*increasing* factors are narrated — a customer told their payment was held
"because the amount was small" would rightly be baffled — with mitigating factors
listed separately. The same output renders a customer notification:

> We have paused a payment of Rs.25,393 from your account for your safety. It looked
> unusual because of the transaction amount (Rs.25,393) and time of day (03:45). If
> you recognise this payment, approve it in the app.

**False positives are explained too.** The report walks through a legitimate payment
the model flagged (₹35,334 to a VPA six days old, following a much smaller payment).
A wrong alert an analyst can interrogate is cleared in seconds; an unexplained score
has to be taken on faith.

## Module 3 artifacts

| File | Contents |
| --- | --- |
| `reports/explainability_report.txt` | The full printed report |
| `reports/explanations/shap_beeswarm.png` | Global distribution of contributions |
| `reports/explanations/shap_importance_bar.png` | Concept-level importance ranking |
| `reports/explanations/waterfall_*.png` | One worked case per scam signature, plus a false positive |
| `reports/explanations/global_shap_ranking.csv` | Concept ranking with directions |
| `reports/explanations/case_files.json` | Machine-readable reason codes per case |

---

# Module 4 — REST API

`main.py` serves the Module 2 classifier and the Module 3 explanation layer over HTTP
for the React dashboard.

```bash
pip install fastapi "uvicorn[standard]"
python main.py
```

The service listens on `http://localhost:8080`, with interactive docs at
[`/docs`](http://localhost:8080/docs) and a status probe at `/api/v1/health`. CORS is
open to `http://localhost:5173` and `http://127.0.0.1:5173` (both spellings, because a
browser sends whichever is in the address bar and they are different origins).

## `POST /api/v1/analyze-transaction`

Only three fields are required; the rest is optional context.

```json
{
  "sender_vpa": "9876543210@ybl",
  "receiver_vpa": "quickcash.help@paytm",
  "amount": 48500.0,
  "receiver_vpa_age_days": 0,
  "timestamp": "2026-08-01T03:12:00",
  "sender_city": "Pune",
  "time_since_last_txn_sec": 45
}
```

```json
{
  "transaction_id": "tx-0eb747b1709c",
  "status": "BLOCKED",
  "fraud_probability": 0.9823,
  "execution_time_ms": 82,
  "xai_explanation": "We have paused a payment of Rs.62,000 from your account for your safety...",
  "shap_features": [
    { "feature": "age of the receiving UPI ID", "importance": 0.2115 },
    { "feature": "transaction amount", "importance": 0.1321 },
    { "feature": "gap since the sender's previous payment", "importance": 0.0821 }
  ]
}
```

`importance` is signed: positive pushes towards fraud, negative towards legitimate,
and the list is ordered by absolute magnitude. Values are SHAP contributions summed
within a concept, so they are additive and the top entry is always the strongest
driver whichever way it points.

`status` uses the cost-calibrated threshold from Module 2 (currently **0.1230**), not
a naive 0.5. A payment can therefore be blocked at 20% probability — deliberate, since
a missed mule transfer costs its full value and a false alarm costs one ₹150 review.

## Two things about the design worth knowing

**The API keeps a short per-sender history, and it has to.** Four features are
backward-looking: the gap since the sender's last payment, that payment's size, the
ratio between them, and whether it went to the same receiver. They exist because the
₹1-test scam is invisible in one row — it is a ₹1 probe followed within seconds by a
large transfer to the *same* receiver. Score a row in isolation and `engineer_features`
sees no predecessor, fills `prev_amount = 0` and `prev_amount_ratio = amount`, and the
model reads that as an enormous spending jump.

So the two-request demo works:

```bash
# leg 1 — the probe
curl -X POST http://localhost:8080/api/v1/analyze-transaction -H "Content-Type: application/json" \
  -d '{"sender_vpa":"victim.suresh@okhdfcbank","receiver_vpa":"verify.acct@paytm","amount":1,"receiver_vpa_age_days":0}'

# leg 2 — same receiver, seconds later
curl -X POST http://localhost:8080/api/v1/analyze-transaction -H "Content-Type: application/json" \
  -d '{"sender_vpa":"victim.suresh@okhdfcbank","receiver_vpa":"verify.acct@paytm","amount":62000,"receiver_vpa_age_days":0}'
```

Leg 2 comes back at p=0.98 citing *gap since the sender's previous payment* (+0.08) and
*repeat payment to the same receiver* (+0.07) — the sequence, not just the size. The
store is an in-memory dict with a 24-hour TTL, which is honest about being
single-process; swapping it for Redis is what a second worker would require.

**Single-row scoring runs the forest single-threaded.** Module 2 fits with
`n_jobs=-1`, correct for 400 trees over 80,000 rows and wrong for scoring one:
joblib's per-call thread pool costs more than the traversal. Measured on this model,
`predict_proba` on one row is 156 ms parallel against 24 ms serial. `main.py` sets
`n_jobs = 1` on the in-memory copy at startup, taking the endpoint from ~164 ms to
~47 ms of compute (69–113 ms over HTTP). The artifact on disk is untouched.

## Other endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Model name, threshold, training timestamp, senders tracked |
| `GET` | `/docs` | Swagger UI |

If the `models/` artifacts are missing the service still starts, but `/health` reports
`degraded` and scoring returns **503** with instructions — better than dying at import
with a stack trace the frontend developer has to go find in a terminal.

CORS allows `localhost` and `127.0.0.1` on ports 5173–5175. The extra ports are not
padding: when 5173 is occupied Vite silently moves to 5174, and without them listed
that fallback presents as a CORS failure that looks like a broken backend.

---

# Dashboard — React frontend

`finguard-dashboard/` is a Vite + React + TypeScript app that calls the Module 4 API.

```bash
cd finguard-dashboard
npm install
npm run dev        # http://localhost:5173 (start `python main.py` first)
```

The base URL comes from `VITE_API_BASE_URL` and defaults to `http://localhost:8080`;
copy `.env.example` to `.env.local` to change it.

`src/services/fraudApi.ts` is the only place that talks to the backend. It shape-checks
every response before React sees it, and translates each failure into something
actionable — an unreachable API says so and names the command to start it, rather than
surfacing the browser's bare "Failed to fetch".

## Reading the SHAP chart

The chart is diverging, not a ranked list of percentages, because real SHAP values are
**signed**: red bars pushed the transaction towards fraud, green bars argued against.
They are additive contributions that sum to the model's output, which is what makes
them an audit trail rather than a popularity ranking. A chart on a 0–100% scale would
silently drop every mitigating factor.

Similarly, the risk gauge takes its colour from the decision, not from a fixed
percentage band. The shipped threshold is 0.1230, so a payment can be blocked at 20%
risk — a gauge that turned green below 40% would contradict the BLOCKED badge above it.

## Receiver VPA age

The form carries an optional **Receiver VPA Age (days)** field alongside the three core
inputs. It is worth filling in: account age is the model's strongest single feature,
and when it is absent the backend assumes an established account, so almost everything
comes back APPROVED. Set it to `0` to demo a mule account.
