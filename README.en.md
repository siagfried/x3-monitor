# X3 Monitor

[简体中文](README.md)

View 3x-ui client activity, usage duration and traffic across different servers and access options.

![X3 Monitor dashboard preview](docs/images/dashboard.png)

*The screenshot uses example data.*

## Features

- Overview, client calendars and daily timelines with traffic details on hover.
- Client ordering, device icons, favorites and activity notifications.
- Chinese / English, light / dark themes and responsive layouts.
- Server status and up to one year of history.
- Optional BandwagonHost traffic integration or manual allowance and reset settings.

## Install

Download and launch the bilingual installer in one command:

```bash
curl -fL https://github.com/siagfried/x3-monitor/archive/refs/tags/v1.1.2.tar.gz -o x3-monitor.tar.gz && tar -xzf x3-monitor.tar.gz && cd x3-monitor-1.1.2 && sudo bash install.sh
```

Enter VEID and API Key when prompted during `install.sh`; no file editing is needed. API Key input is hidden. Leave VEID blank to skip the API and use manual traffic settings.

Alternatively, install from a source checkout:

```bash
git clone https://github.com/siagfried/x3-monitor.git
cd x3-monitor
sudo bash install.sh
```

Enter your existing 3x-ui URL and login details, then choose an access option. The installer displays the dashboard URL when finished.

Choose Tailnet, an existing HTTPS proxy, direct HTTPS or local access. Tailscale is optional; public access includes HTTPS and login protection. Existing 3x-ui and subscription settings stay unchanged.

## Traffic settings

**Manual mode:** Leave VEID blank. Open **System status** in the dashboard to edit the next reset time, current usage and total allowance. New client traffic adds to your usage baseline, with monthly resets at the selected time.

**BandwagonHost automatic mode:** Enter VEID and API Key for official usage and reset time, plus available audit, backup and issue records.

Find the credentials in the [BandwagonHost client area](https://bandwagonhost.com/clientarea.php) → Services → My Services → your VPS → KiwiVM → API. Copy VEID and select **Show API Key**. Secret input is hidden.

Manual usage covers clients monitored by the panel and may differ from whole-server provider billing.

## Notifications

Follow a client, then use the bell to enable notifications on your device. Background delivery depends on browser and OS settings. Local HTTP mode does not provide background notifications.

## Update and uninstall

Update the source and rerun the installer to keep your settings and history.

```bash
# Uninstall while keeping settings and history
sudo bash /opt/x3-monitor/uninstall.sh

# Remove everything after interactive confirmation
sudo bash /opt/x3-monitor/uninstall.sh --purge
```

[Releases](https://github.com/siagfried/x3-monitor/releases) · [Validation](VALIDATION.md)
