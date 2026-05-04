#!/usr/bin/env python3
"""
MACchanger — native macOS app
Temporary MAC address changer. The hardware MAC address is preserved.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess, re, json, os, random, sys, time, shlex
from pathlib import Path
import threading
import queue

BACKUP_FILE = Path.home() / ".macchanger_backup.json"
LOG_FILE = Path.home() / "macchanger_debug.log"
APP_VERSION = "1.0.0"

# ── Core Logic ─────────────────────────────────────────────────────────────

def log_debug(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {message}\n")

def run_cmd(cmd, check=False, timeout=30):
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=timeout,
        )
        log_debug(
            f"CMD: {cmd!r} -> rc={r.returncode} "
            f"stdout={r.stdout.strip()!r} stderr={r.stderr.strip()!r}"
        )
        return r
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout if isinstance(e.stdout, str) else ""
        stderr = e.stderr if isinstance(e.stderr, str) else ""
        msg = (
            f"The command did not finish within {timeout} seconds. "
            "The macOS network service may be unresponsive or the privileged command may be stuck."
        )
        log_debug(f"TIMEOUT: {cmd!r} stdout={stdout!r} stderr={stderr!r}")
        return subprocess.CompletedProcess(cmd, 124, stdout, stderr or msg)

def get_interfaces():
    r = run_cmd(["networksetup", "-listallhardwareports"])
    return re.findall(r"Device:\s+(\S+)", r.stdout)

def get_interface_ports():
    r = run_cmd(["networksetup", "-listallhardwareports"])
    ports = {}
    for block in r.stdout.split("\n\n"):
        port = re.search(r"Hardware Port:\s+(.+)", block)
        device = re.search(r"Device:\s+(\S+)", block)
        if port and device:
            ports[device.group(1)] = port.group(1)
    return ports

def is_wifi_interface(iface):
    return get_interface_ports().get(iface, "").lower() == "wi-fi"

def get_current_mac(iface):
    r = run_cmd(["ifconfig", iface])
    m = re.search(r"ether\s+([0-9a-f:]{17})", r.stdout)
    return m.group(1) if m else None

def get_hardware_mac(iface):
    r = run_cmd(["networksetup", "-getmacaddress", iface])
    m = re.search(r"([0-9a-fA-F:]{17})", r.stdout)
    return m.group(1).lower() if m else None

def generate_random_mac():
    first = (random.randint(0, 255) & 0xFE) | 0x02
    rest = [random.randint(0, 255) for _ in range(5)]
    return ":".join(f"{b:02x}" for b in [first] + rest)

def validate_mac(mac):
    return bool(re.match(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", mac))

def load_backup():
    if BACKUP_FILE.exists():
        with open(BACKUP_FILE) as f:
            return json.load(f)
    return {}

def save_backup(data):
    with open(BACKUP_FILE, "w") as f:
        json.dump(data, f, indent=2)

def backup_original(iface):
    backup = load_backup()
    if iface not in backup:
        mac = get_hardware_mac(iface) or get_current_mac(iface)
        if mac:
            backup[iface] = mac
            save_backup(backup)
    return backup.get(iface)

def escape_applescript_string(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')

def admin_shell(command):
    script = f'do shell script "{escape_applescript_string(command)}" with administrator privileges'
    log_debug(f"ADMIN SHELL: {command}")
    return run_cmd(["osascript", "-e", script], timeout=45)

def run_wifi_mac_strategy(iface, new_mac, strategy_name, command):
    r = admin_shell(command)
    if r.returncode == 0:
        time.sleep(1)
        current = get_current_mac(iface)
        if current and current.lower() == new_mac.lower():
            return True, ""
        return False, f"{strategy_name}: command completed, but the MAC address did not change."

    msg = (r.stderr or r.stdout or "Command failed.").strip()
    return False, f"{strategy_name}: {msg}"

def apply_mac_with_sudo(iface, new_mac):
    """Change the MAC address through AppleScript admin privileges for the GUI app."""
    quoted_iface = shlex.quote(iface)
    quoted_mac = shlex.quote(new_mac)

    if is_wifi_interface(iface):
        disconnect = (
            "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport "
            "-z >/dev/null 2>&1 || true"
        )
        strategy_connected_radio = (
            f"{disconnect}; "
            "sleep 1; "
            f"/sbin/ifconfig {quoted_iface} ether {quoted_mac}; "
            "/usr/sbin/networksetup -detectnewhardware >/dev/null 2>&1 || true"
        )
        ok, detail = run_wifi_mac_strategy(
            iface,
            new_mac,
            "Wi-Fi radio-on disconnected strategy",
            strategy_connected_radio,
        )
        if ok:
            return True, ""

        strategy_power_cycle = (
            "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -z >/dev/null 2>&1; "
            f"/usr/sbin/networksetup -setairportpower {quoted_iface} off; "
            "sleep 1; "
            f"/usr/sbin/networksetup -setairportpower {quoted_iface} on; "
            "sleep 1; "
            f"change_output=$(/sbin/ifconfig {quoted_iface} ether {quoted_mac} 2>&1); "
            "change_status=$?; "
            "/usr/sbin/networksetup -detectnewhardware >/dev/null 2>&1 || true; "
            'if [ "$change_status" -ne 0 ]; then echo "$change_output"; fi; '
            'exit "$change_status"'
        )
        ok, second_detail = run_wifi_mac_strategy(
            iface,
            new_mac,
            "Wi-Fi power-cycle strategy",
            strategy_power_cycle,
        )
        if ok:
            return True, ""
        msg = f"{detail}\n\n{second_detail}"
    else:
        command = (
            f"/sbin/ifconfig {quoted_iface} down && "
            f"/sbin/ifconfig {quoted_iface} lladdr {quoted_mac} && "
            f"/sbin/ifconfig {quoted_iface} up"
        )
        r = admin_shell(command)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout or "Command failed.").strip()
            return False, msg

        time.sleep(1)
        current = get_current_mac(iface)
        if current and current.lower() == new_mac.lower():
            return True, ""
        return False, "Command completed, but the new MAC address is not visible on the interface."

    if "Can't assign requested address" in msg:
        return False, (
            "macOS rejected MAC address changes on this Wi-Fi interface. "
            f"System responses:\n\n{msg}"
        )
    return False, msg

def change_mac(iface, new_mac):
    backup_original(iface)
    return apply_mac_with_sudo(iface, new_mac.lower())

def restore_mac(iface):
    backup = load_backup()
    if iface not in backup:
        return False, "No saved original MAC address was found."
    ok = apply_mac_with_sudo(iface, backup[iface])
    if ok[0]:
        return True, backup[iface]
    return False, ok[1]

# ── GUI ────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MACchanger")
        self.resizable(False, False)
        self.configure(bg="#1c1c1e")

        # macOS window chrome
        try:
            self.tk.call("::tk::unsupported::MacWindowStyle", "style", self._w, "document", "closeBox")
        except Exception:
            pass

        self.result_queue = queue.Queue()
        self._build_ui()
        self._refresh()
        self.after(100, self._drain_results)

    def _build_ui(self):
        bg = "#1c1c1e"
        card = "#2c2c2e"
        accent = "#0a84ff"
        green = "#30d158"
        text = "#f5f5f7"
        sub = "#98989f"
        danger = "#ff453a"

        self.colors = dict(bg=bg, card=card, accent=accent, green=green,
                           text=text, sub=sub, danger=danger)

        # ── Header ──
        hdr = tk.Frame(self, bg=bg)
        hdr.pack(fill="x", padx=24, pady=(24, 0))

        tk.Label(hdr, text="⬡", font=("SF Pro Display", 32), fg=accent, bg=bg).pack(side="left")
        title_f = tk.Frame(hdr, bg=bg)
        title_f.pack(side="left", padx=10)
        tk.Label(title_f, text="MACchanger", font=("SF Pro Display", 20, "bold"),
                 fg=text, bg=bg).pack(anchor="w")
        tk.Label(title_f, text=f"v{APP_VERSION} — Temporary MAC changer",
                 font=("SF Pro Text", 11), fg=sub, bg=bg).pack(anchor="w")

        sep = tk.Frame(self, bg="#3a3a3c", height=1)
        sep.pack(fill="x", padx=24, pady=16)

        # ── Interface Card ──
        c1 = tk.Frame(self, bg=card, padx=16, pady=14)
        c1.pack(fill="x", padx=24, pady=(0, 10))

        tk.Label(c1, text="INTERFACE", font=("SF Mono", 9), fg=sub, bg=card).pack(anchor="w")

        iface_row = tk.Frame(c1, bg=card)
        iface_row.pack(fill="x", pady=(4, 0))

        self.ifaces = get_interfaces()
        self.iface_var = tk.StringVar(value=self.ifaces[0] if self.ifaces else "")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Dark.TCombobox",
                         fieldbackground="#3a3a3c",
                         background="#3a3a3c",
                         foreground=text,
                         selectbackground=accent,
                         selectforeground=text,
                         borderwidth=0)

        cb = ttk.Combobox(iface_row, textvariable=self.iface_var,
                          values=self.ifaces, width=10,
                          state="readonly", style="Dark.TCombobox",
                          font=("SF Mono", 13))
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _: self._refresh())

        refresh_btn = tk.Button(iface_row, text="↻", font=("SF Pro Text", 14),
                                bg=card, fg=sub, bd=0, cursor="hand2",
                                activebackground=card, command=self._refresh)
        refresh_btn.pack(side="left", padx=6)

        # MAC info rows
        info_f = tk.Frame(c1, bg=card)
        info_f.pack(fill="x", pady=(12, 0))

        self.current_mac_lbl = self._info_row(info_f, "CURRENT", "—", accent)
        self.original_mac_lbl = self._info_row(info_f, "HARDWARE", "—", green)
        self.status_badge = tk.Label(info_f, text="● Original",
                                     font=("SF Pro Text", 11), fg=green, bg=card)
        self.status_badge.pack(anchor="w", pady=(4, 0))

        sep2 = tk.Frame(self, bg="#3a3a3c", height=1)
        sep2.pack(fill="x", padx=24, pady=8)

        # ── MAC Input Card ──
        c2 = tk.Frame(self, bg=card, padx=16, pady=14)
        c2.pack(fill="x", padx=24, pady=(0, 10))

        tk.Label(c2, text="NEW MAC ADDRESS", font=("SF Mono", 9), fg=sub, bg=card).pack(anchor="w")

        mac_row = tk.Frame(c2, bg=card)
        mac_row.pack(fill="x", pady=(6, 0))

        self.mac_var = tk.StringVar()
        mac_entry = tk.Entry(mac_row, textvariable=self.mac_var,
                             font=("SF Mono", 14), bg="#3a3a3c", fg=text,
                             insertbackground=text, relief="flat", bd=0,
                             width=20)
        mac_entry.pack(side="left", ipady=6, ipadx=4)

        rand_btn = tk.Button(mac_row, text="Random",
                             font=("SF Pro Text", 12), bg="#3a3a3c", fg=accent,
                             bd=0, cursor="hand2", padx=10,
                             activebackground="#48484a", activeforeground=accent,
                             command=self._fill_random)
        rand_btn.pack(side="left", padx=(8, 0))

        # ── Action Buttons ──
        btn_f = tk.Frame(self, bg=bg)
        btn_f.pack(fill="x", padx=24, pady=(4, 0))

        self.change_btn = self._btn(btn_f, "Change MAC", accent, self._do_change)
        self.change_btn.pack(
            side="left", padx=(0, 8), pady=8, ipady=8, ipadx=20, fill="x", expand=True)
        self.restore_btn = self._btn(btn_f, "Restore Original", "#3a3a3c", self._do_restore,
                                     fg=green)
        self.restore_btn.pack(side="left", pady=8, ipady=8, ipadx=16, fill="x", expand=True)

        # ── Status Bar ──
        self.log_lbl = tk.Label(self, text="Ready.", font=("SF Pro Text", 11),
                                fg=sub, bg=bg, anchor="w")
        self.log_lbl.pack(fill="x", padx=24, pady=(0, 20))

    def _info_row(self, parent, label, value, color):
        f = tk.Frame(parent, bg=parent["bg"])
        f.pack(fill="x", pady=2)
        tk.Label(f, text=f"{label}:", font=("SF Mono", 9),
                 fg=self.colors["sub"], bg=parent["bg"], width=8, anchor="w").pack(side="left")
        lbl = tk.Label(f, text=value, font=("SF Mono", 12),
                       fg=color, bg=parent["bg"])
        lbl.pack(side="left")
        return lbl

    def _btn(self, parent, text, bg, cmd, fg="white"):
        return tk.Button(parent, text=text, font=("SF Pro Text", 13, "bold"),
                         bg=bg, fg=fg, bd=0, cursor="hand2",
                         activebackground=bg, activeforeground=fg,
                         command=cmd, relief="flat")

    def _refresh(self):
        iface = self.iface_var.get()
        curr = get_current_mac(iface) or "—"
        backup = load_backup()
        hw = backup.get(iface) or get_hardware_mac(iface) or "—"

        self.current_mac_lbl.config(text=curr)
        self.original_mac_lbl.config(text=hw)

        if curr != "—" and hw != "—" and curr.lower() != hw.lower():
            self.status_badge.config(text="● Changed", fg=self.colors["accent"])
        elif curr == "—":
            self.status_badge.config(text="● Inactive", fg=self.colors["sub"])
        else:
            self.status_badge.config(text="● Original", fg=self.colors["green"])

    def _fill_random(self):
        self.mac_var.set(generate_random_mac())

    def _set_log(self, msg, color=None):
        self.log_lbl.config(text=msg, fg=color or self.colors["sub"])

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.change_btn.config(state=state)
        self.restore_btn.config(state=state)

    def _drain_results(self):
        try:
            while True:
                result = self.result_queue.get_nowait()
                if result[0] == "change":
                    _, ok, mac, detail = result
                    self._after_change(ok, mac, detail)
                elif result[0] == "restore":
                    _, ok, mac = result
                    self._after_restore(ok, mac)
        except queue.Empty:
            pass
        self.after(100, self._drain_results)

    def _do_change(self):
        iface = self.iface_var.get()
        mac = self.mac_var.get().strip()
        if not mac:
            messagebox.showwarning("Missing MAC", "Enter a MAC address or click Random.")
            return
        if not validate_mac(mac):
            messagebox.showerror("Invalid Format",
                                 "The MAC address must use the XX:XX:XX:XX:XX:XX format.")
            return

        self._set_busy(True)
        self._set_log("Changing MAC address...", self.colors["accent"])
        self.update()

        def worker():
            ok, detail = change_mac(iface, mac)
            self.result_queue.put(("change", ok, mac, detail))

        threading.Thread(target=worker, daemon=True).start()

    def _after_change(self, ok, mac, detail=""):
        if ok:
            self._set_log(f"MAC address changed -> {mac}", self.colors["green"])
        else:
            self._set_log(f"❌ {detail}", self.colors["danger"])
            messagebox.showerror("MAC Change Failed", detail)
        self._refresh()
        self._set_busy(False)

    def _do_restore(self):
        iface = self.iface_var.get()
        self._set_busy(True)
        self._set_log("Restoring original MAC address...", self.colors["accent"])
        self.update()

        def worker():
            ok, mac = restore_mac(iface)
            self.result_queue.put(("restore", ok, mac))

        threading.Thread(target=worker, daemon=True).start()

    def _after_restore(self, ok, mac):
        if ok:
            self._set_log(f"Original MAC address restored -> {mac}", self.colors["green"])
        else:
            self._set_log(f"❌ {mac}", self.colors["danger"])
            messagebox.showerror("Restore Failed", mac)
        self._refresh()
        self._set_busy(False)


def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
