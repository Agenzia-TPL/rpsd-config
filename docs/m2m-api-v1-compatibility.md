# M2M API v1 compatibility contract

This document records the `rpsd-config` endpoints currently consumed by the
ingest service. The v1 API remains available while the configuration data model
evolves. Compatibility is enforced by versioned golden tests contained entirely
in this repository.

All endpoints use a Keycloak client-credentials bearer token. The token resolves
an active `IntegrationPrincipal`; access to a contract additionally requires an
active `ingest:write` grant belonging to the contractor company.

| Endpoint | Success | Stable response fields | Observable failures |
| --- | --- | --- | --- |
| `GET /exchange_agreement/api/m2m/v1/contracts/{contract_code}/flow-profile` | `200` | `contract_code`, `flow_profile.code`, `name`, `schema_version`, `is_active`, `description`, `options` | `401` missing/invalid authentication; `403` missing or inactive grant; `404` unknown or invisible contract |
| `GET /exchange_agreement/api/m2m/v1/contracts/{contract_code}/required-inputs` | `200` | `contract_code`, grouped `required_inputs`, dataset identity, structures, indicator codes | `401` missing/invalid authentication; `403` missing or inactive grant; `404` unknown or invisible contract |
| `GET /exchange_agreement/api/m2m/v1/contracts/{contract_code}/ingest-authorization?data_category={what}` | `200` | `allowed`, `contract_code`, `data_category`, `flow_profile_code`, `flow`, `grant_id` | `400` invalid/inactive flow profile or category; `401` missing/invalid authentication; `403` missing or inactive grant; `404` unknown or invisible contract; `422` missing query parameter |

The legacy-shaped fields are compatibility projections; the removed
`FlowProfile` and `OperationalFlow` tables are not read. Config resolves the
contract's current approved revision, then projects its
`ProcessingProfileVersion` and `InputFlowVersion` records. The public `flow`
field contains the selected `InputFlowVersion.deployment_name`, which is the
runtime descriptor expected by the consumer.

No endpoint accepts a client-supplied reference date. Historic and future
revisions cannot be selected through the operational API. Any future semantic
change to these stable fields requires explicit review and a corresponding
golden-fixture update.

The golden contract is stored in
`tests_integration/exchange_agreement/fixtures/m2m_api_v1_contract.json` and is
verified by `test_m2m_api_v1_contract.py`. Dynamic database identifiers are
normalised before comparison; every other field is compared exactly.

These tests mock token authentication inside Django and use only the config
database. They do not start or modify ingest, Prefect, Keycloak, or a message
broker.
