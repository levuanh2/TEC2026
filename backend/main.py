"""AgriCarbon backend - entrypoint.

Lop 1a (Walking Skeleton) + 1b/1c. Nguoi B phu trach.
Dac ta: docs/modules/02-carbon-engine.md, docs/SRS.md
"""

from fastapi import FastAPI

app = FastAPI(title="AgriCarbon API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# TODO(1a): POST /v1/sync  - nhan batch Activity offline tu app (FR-1a-07)
# TODO(1a): POST /v1/carbon/calculate - Activity Data x Emission Factor -> CO2e/kg (FR-1a-08)
# TODO(1a): nap emission factor tu config/emission_factors.yaml, KHONG hardcode (SRS RB-01)
# TODO(1b): GET /v1/plots/{id}/efficiency - nuoc/kg, phan/kg, carbon/kg, cost/kg (FR-1b-05)
# TODO(1c): GET /v1/reports/mrv - xuat bao cao 6 buoc MRV (FR-1c-05)
