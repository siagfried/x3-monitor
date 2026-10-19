# v1.1.0 Validation

- 42 Python tests: sampling, sanitization, manual accounting, reset boundaries, short months, persisted baselines, invalid values, API/manual isolation, GET/POST authentication and Tailnet route guards.
- Sandbox checks: fresh install, retained-config upgrade, failed-initialization rollback, safe uninstall and exact purge confirmation.
- Example browser: manual edits persist after reload; no provider/Tailscale required; README screenshot uses example data only.
- Production configuration and Tailnet-only exposure remain unchanged; no 3x-ui/Xray restart.
- Public proxy/direct TLS modes require target-specific certificates and acceptance. No public production deployment was performed.
