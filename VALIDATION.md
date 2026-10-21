# v1.4.0 Validation

- 65 Python tests cover sampling, history retention, client membership, billing summaries, exact hourly spans, group preferences, security/configuration, response-cache expiry, concurrent requests, and invalidation after sampling or layout changes.
- JavaScript checks cover exact short/reconnected/cross-hour sessions, partial first/last hours, group traffic, calendar thresholds, interval-average colors, and dashboard syntax.
- Browser checks cover numeric 3-by-4 month pickers, light/dark floating panels, overview/client calendar details, daily interval colors and year/month/day switching. Orange dates were previewed with fictional data before deployment.
- Installer/uninstaller sandbox checks cover fresh installation, retained-config upgrades, failed-initialization rollback, ownership guards and purge confirmation.
- Current source, Git history and packaged assets are scanned against live private identifiers and generic secret patterns before upload. README screenshots contain fictional data.
- Only source, documentation, tests and example configuration are packaged. Production configuration, databases, credentials, logs, caches, backups and preview tools are excluded.
- Live acceptance covers the existing Tailnet deployment. 3x-ui and Xray are not restarted by this update.
