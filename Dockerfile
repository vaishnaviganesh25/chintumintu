# FinGuard API - multi-stage so the runtime image carries trained artifacts rather
# than the toolchain that produced them.
#
# The model is trained at *build* time, not first-request time. A container whose
# first call takes two minutes while it fits 400 trees is a container that fails its
# own health check and gets restarted mid-training, forever. Building the artifacts
# in is the difference between `docker compose up` working and appearing to hang.

# --------------------------------------------------------------------------- #
# Stage 1 - generate the dataset and train
# --------------------------------------------------------------------------- #
FROM python:3.13-slim AS builder

WORKDIR /build

# Dependencies first, so a code change does not invalidate the wheel cache.
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

ENV PATH="/install/bin:$PATH" PYTHONPATH="/install/lib/python3.13/site-packages"

COPY generate_upi_dataset.py train_model.py explain_model.py merchant_policy.py ./

# ~30 s + ~110 s + ~100 s. Cached unless one of the three scripts changes.
RUN python generate_upi_dataset.py \
 && python train_model.py \
 && python explain_model.py

# --------------------------------------------------------------------------- #
# Stage 2 - runtime
# --------------------------------------------------------------------------- #
FROM python:3.13-slim AS runtime

# Non-root: the API takes untrusted input from the internet and has no reason to
# hold root inside its own container.
RUN useradd --create-home --shell /usr/sbin/nologin finguard

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --from=builder /build/models  ./models
COPY --from=builder /build/reports ./reports

COPY main.py train_model.py explain_model.py merchant_policy.py \
     audit_store.py chargeback_agent.py degradation.py ./

# The ledger lives on a volume - a decision record that vanishes when the container
# is replaced is not an audit trail.
RUN mkdir -p /app/data && chown -R finguard:finguard /app
VOLUME ["/app/data"]

USER finguard

ENV FINGUARD_AUDIT_DB=/app/data/finguard_audit.db \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# The deep probe, not the shallow one: a container serving on the fallback rung is
# up but not healthy, and an orchestrator should know the difference.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,json,sys; \
d=json.load(urllib.request.urlopen('http://localhost:8080/api/v1/health/deep',timeout=4)); \
sys.exit(0 if d['serving'] else 1)"

CMD ["python", "main.py"]
