# v1.3.1 Validation

- 59 Python tests cover sampling, history retention, client membership, billing-cycle summaries, hourly traffic, group preferences, and security/configuration checks.
- JavaScript syntax checked. Browser verification covers tile/group layouts, multi-card expansion, group summaries, 14-column overview calendars, per-card locks and refresh persistence, reset-day dots, current-day lines, and desktop/mobile layouts.
- Installer/uninstaller sandbox checks cover fresh installation, retained-config upgrades, failed-initialization rollback, ownership guards and purge confirmation.
- Public source, Git history and release assets are scanned for production credentials and identifiers before upload. Both README images use example IP addresses, names and usage; ancillary image metadata is removed.
- Acceptance covers the existing Tailnet deployment. Other access modes need target-specific certificate and browser acceptance.
- Original screenshots, production configuration, history databases, keys, logs, caches and temporary preview tools are excluded from the release.

- README previews are captured directly from the dashboard with a local synthetic-data fixture; reset-day dots are verified beneath day 8 in tile and group modes.
