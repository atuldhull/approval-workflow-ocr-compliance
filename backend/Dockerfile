FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONPATH=/srv:/srv/backend \
    PYTHONUNBUFFERED=1

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY contracts contracts
COPY rulesets rulesets
COPY generator generator

EXPOSE 8000
CMD ["sh", "-c", "alembic -c backend/alembic.ini upgrade heads && python generator/cases/seed_demo.py && uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload --reload-dir backend --reload-dir contracts --reload-dir rulesets"]
