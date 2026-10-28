FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONPATH=/srv:/srv/backend \
    PYTHONUNBUFFERED=1

# Tesseract for scanned documents (English, plus Hindi/Devanagari); PDF text layers are read with pypdf.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY contracts contracts
COPY rulesets rulesets
COPY generator generator

EXPOSE 8000
# The demo seeds refuse to run unless DEMO_MODE=true; that is not an error for startup. The case seed drives demo
# cases through the API in-process (about half a minute the first time, nothing on later starts); the compliance seed
# adds validity records and an undertaking to the approved ones.
CMD ["sh", "-c", "alembic -c backend/alembic.ini upgrade heads && python generator/cases/seed_demo.py && (python -m app.platform.demo_seed || echo 'platform demo seed skipped') && (python -m app.workflow.demo_seed && python -m app.compliance.demo_seed || echo 'case demo seed skipped') && uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload --reload-dir backend --reload-dir contracts --reload-dir rulesets"]
