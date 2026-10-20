# v1.2.0 Validation

- 52 Python tests covering sampling, retained history, client membership changes, recreated-client baselines, inbound names, billing-cycle summaries, hourly/month and daily/year occupancy, and existing security/configuration checks.
- JavaScript syntax checked; browser verification covers calendar expansion, independent columns, loading text, year/month/day modes, timeline clipping and padding, hidden deleted clients, and inbound labels for duplicate names.
- Installer/uninstaller sandbox checks cover fresh installation, retained-config upgrades, failed-initialization rollback, ownership guards and purge confirmation.
- Public source/package scanned against production secrets and identifiers; README screenshot contains example data only.
- Production monitor updated and checked. Existing 3x-ui/Xray processes and access settings remain unchanged.
- Browser acceptance covers the existing Tailnet deployment. Other access modes require target-specific certificates and acceptance.
