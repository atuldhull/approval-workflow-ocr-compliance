# evc (Person 1)

Planned:
- `evc_request`, `expert`, `availability`, `coi`, `slot`, `assignment`, `schedule_run` tables (schema `evc`)
- Panels come from a labelled stand-in for the authorised selector (APH 1.8(a): automated, not random)
- CP-SAT chooses **dates only**; EDF baseline for comparison; explanations for unavailable slots
- APIs: `GET /evc/queue`, `POST /evc/schedule:propose`, `POST /evc/schedule:publish`
- Opens the EVC clock through `DeadlinePort`
