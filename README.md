# MACchanger for macOS

Native macOS app for temporarily changing a network interface MAC address. It includes a Wi-Fi strategy tested on an M4 MacBook where the usual single `ifconfig en0 ether ...` command can fail.

## Highlights

- Native Tkinter macOS app with a compact dark interface
- Random or manual MAC address input
- Automatic backup of the original hardware MAC in `~/.macchanger_backup.json`
- One-click restore to the saved original MAC address
- AppleScript administrator prompt, so users do not need to launch the app from Terminal
- M-series Wi-Fi flow for `en0`: disconnect first, then try a radio-on strategy and a power-cycle fallback
- Debug log at `~/macchanger_debug.log`

## Compatibility

Tested on:

- Apple Silicon MacBook, including M4
- macOS Sequoia 15.x
- Wi-Fi interface `en0`

macOS behavior varies by hardware, driver, SIP state, and interface type. Some internal Wi-Fi interfaces reject custom MAC addresses even when the command is valid. External Ethernet adapters usually allow MAC changes more reliably.

## How The Wi-Fi Method Works

For Wi-Fi interfaces, MACchanger does not only run a plain `ifconfig` command. It tries two strategies:

1. Disconnect Wi-Fi with Apple80211 `airport -z`, keep the radio on, then apply `ifconfig <iface> ether <mac>`.
2. If the first strategy fails, power-cycle Wi-Fi with `networksetup -setairportpower`, then apply the MAC and run `networksetup -detectnewhardware`.

The app verifies the result by reading the interface MAC after the command finishes. If macOS rejects the change, the real system error is shown in the UI and written to the debug log.

## Install From Source

```bash
git clone https://github.com/ikoloper/MACchanger.git
cd MACchanger
```

Install dependencies with `uv`:

```bash
uv sync
```

Or use Python directly:

```bash
python3 -m pip install pyinstaller
```

## Build The App

```bash
chmod +x build.sh
./build.sh
```

The app is generated at:

```text
dist/MACchanger.app
```

To install it into Applications:

```bash
rm -rf /Applications/MACchanger.app
cp -R dist/MACchanger.app /Applications/
```

## Usage

1. Open `MACchanger.app`.
2. Select the interface, for example `en0` for Wi-Fi.
3. Enter a MAC address or click `Random`.
4. Click `Change MAC`.
5. Approve the macOS administrator prompt.
6. Use `Restore Original` to restore the saved original MAC.

The change is temporary. A reboot or restore action returns the interface to its hardware MAC in normal conditions.

## Troubleshooting

### The app says macOS rejected the Wi-Fi change

This means the privileged command ran, but the macOS Wi-Fi driver rejected the requested address. Try:

- Disconnecting from the Wi-Fi network before changing the MAC
- Trying again with a freshly generated random MAC
- Testing an external Ethernet adapter
- Checking `~/macchanger_debug.log` for the exact system response

### The app stays on "Changing MAC address..."

Recent versions include a timeout and a main-thread result queue. If this still happens, quit the app, rebuild, and check:

```bash
tail -80 ~/macchanger_debug.log
```

### The Applications version is older than the build

Replace the installed copy:

```bash
rm -rf /Applications/MACchanger.app
cp -R dist/MACchanger.app /Applications/
```

## Project Structure

```text
MACchanger/
├── MACchanger/
│   └── main.py
├── resources/
│   ├── MACchanger.icns
│   └── make_icon.py
├── MACchanger.spec
├── build.sh
├── pyproject.toml
└── README.md
```

## Safety Notes

MACchanger does not modify the hardware ROM address. It only requests a temporary link-layer address change from macOS. Use it only on networks and devices you own or are authorized to test.

## Legal / Responsible Use

MACchanger is intended for privacy, troubleshooting, testing, and authorized network administration on devices and networks you own or have permission to use.

Do not use this tool to bypass network access controls, impersonate another device, evade bans, avoid payment, disrupt networks, or access systems without authorization. You are responsible for complying with local laws, network policies, and terms of service.

## License

MIT License. See `LICENSE`.
