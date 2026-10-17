# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# LightGBM and XGBoost use the OpenMP runtime. All other solver dependencies
# are distributed as Python wheels for this image.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
COPY coalitions/requirements.txt coalitions/requirements-solver.txt ./coalitions/
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        --requirement requirements.txt \
        --requirement coalitions/requirements.txt \
        --requirement coalitions/requirements-solver.txt

COPY . .

# The default is the data-free, deterministic verification workflow.
CMD ["python", "coalitions/scripts/verify_release.py"]
