# analytics (Person 3)

Planned:
- Projection tables rebuilt from `plat.domain_event` (schema `an`); replay diff must be zero
- Pendency by regional office and stage, workload, obligation status
- Scorecard against the generator's answer key (missed and duplicate alerts, escalation, OCR accuracy)
- APIs: `GET /dashboards/pendency`, `GET /reports/{type}`, `POST /exports`
