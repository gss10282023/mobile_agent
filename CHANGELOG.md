# Changelog

All notable changes to this project will be documented in this file.
This project follows the Keep a Changelog format.

## [0.1.0] - 2025-12-30
### Added
- Initial open-source release.
- Core UI-TARS pipeline (screenshot -> model -> parser -> executor).
- CLI support for dry-run and device execution modes.
- Run artifact capture via `--save-runs` (screenshots + model outputs).
- Action parser unit tests.

### Known Issues
- Device/OS variability can cause coordinate drift or layout mismatches.
- Screenshot capture depends on adb/uiautomator2 and may fail if the device is offline.
- Model outputs can occasionally violate the Action format and need retry or prompt tuning.
