# Examples

These commands assume you have set `OPENROUTER_API_KEY` and connected a device
or emulator via `adb`.

## Dry-run examples
```bash
mobile-agent --dry-run 1 -i "Open Settings and turn on Wi-Fi"
mobile-agent --dry-run 1 -i "Open Chrome and search for weather"
mobile-agent --dry-run 1 -i "Open Messages and start a new chat"
```

## Real device execution
```bash
mobile-agent --dry-run 0 --serial "<device_serial>" -i "Open Settings and turn on Wi-Fi"
```
