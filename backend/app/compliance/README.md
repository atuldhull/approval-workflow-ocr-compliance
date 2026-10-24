# compliance (Person 2)

Planned:
- `approval_letter`, `obligation`, `evidence`, `verification` tables (schema `cmp`)
- `CompliancePort.register_letter` is called by the workflow when a letter is issued
- EOA_DEFICIENCY_6M applies only to officer-confirmed LETTER_CONDITION obligations from letters that list deficiencies
- Acknowledged is not the same as met; verification is human only, with a reason on rejection
- APIs: `GET /obligations`, `POST /obligations/{id}/evidence`, `POST /evidence/{id}/verify`
