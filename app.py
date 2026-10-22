"""Opens the dashboard as its own desktop window (browser app mode: no tabs, no address bar).

    python3 app.py                       # start the server in the background if needed, open the window
    python3 app.py --status              # server, pid file and the browser that would be used
    python3 app.py --stop                # stop the background server
    python3 app.py --install-shortcut    # "Game of Claude" on the Windows Desktop and Start menu
    python3 app.py --uninstall-shortcut
    python3 app.py --dry-run [...]       # print what would be executed, launch nothing

The window is Edge (or Chrome) on Windows in --app mode with its own profile, started via WSL
interop, so it gets its own taskbar entry, notification permission and remembered window position.
Without a Windows browser it falls back to Chromium via WSLg, then to the default browser.
The server keeps running after the window closes (pid and log under ~/.local/state/claude-telemetry),
so the next open is instant; `--stop` ends it.
"""
from __future__ import annotations

import argparse
import base64
import os
import platform
import shutil
import signal
import struct
import subprocess
import sys
import time
import urllib.request
import webbrowser
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE / "server.py"
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "claude-telemetry"
NAME = "Game of Claude"
WIN_DIR = "ClaudeTelemetry"  # under %LOCALAPPDATA%: browser profile and icon (Windows side, fast and local)
WINDOW = "1440,960"
WIN_BROWSERS = [  # (name, Windows path), first match wins
    ("edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ("edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ("chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ("chrome", r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
LINUX_BROWSERS = ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge"]


class Fail(Exception):
    pass


# ---------- WSL interop ----------

def is_wsl() -> bool:
    return "microsoft" in platform.release().lower() and shutil.which("wslpath") is not None


def win_run(*cmd: str) -> str:
    """Run a Windows program and return stdout (cwd on C: avoids the 'UNC path' warning)."""
    r = subprocess.run(cmd, cwd="/mnt/c", capture_output=True, timeout=30)
    return r.stdout.decode("utf-8", "replace").replace("\0", "").strip()


def to_linux(win_path: str) -> Path:
    return Path(subprocess.run(["wslpath", "-u", win_path], capture_output=True, text=True).stdout.strip())


_env: dict[str, str] = {}


def win_env(var: str) -> str:
    if var not in _env:
        _env[var] = win_run("cmd.exe", "/d", "/c", f"echo %{var}%")
    return _env[var]


def powershell(script: str, dry: bool) -> str:
    """Runs a PowerShell script via -EncodedCommand (no quoting trouble)."""
    if dry:
        print(f"would run powershell.exe:\n{script}")
        return ""
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    return win_run("powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc)


def ps_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# ---------- server ----------

def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
            return r.read().strip() == b"ok"
    except OSError:
        return False


def pid_file(port: int) -> Path:
    return STATE / f"server-{port}.pid"


def log_file(port: int) -> Path:
    return STATE / f"server-{port}.log"


def our_pid(port: int) -> int | None:
    """Pid from the pid file, only if that process is still our server.py (pids get reused)."""
    try:
        pid = int(pid_file(port).read_text().strip())
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return None
    return pid if any(c.endswith(b"server.py") for c in cmd) else None


def start_server(port: int, timeout: float, dry: bool):
    cmd = [sys.executable, str(SERVER), "--no-browser", "--port", str(port)]
    if healthy(port):
        print(f"server already running on port {port}")
        return
    if dry:
        print(f"would start (detached, log {log_file(port)}): {' '.join(cmd)}")
        return
    STATE.mkdir(parents=True, exist_ok=True)
    with open(log_file(port), "ab") as log:
        log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)}\n".encode())
        log.flush()
        # own session: survives the terminal / wsl.exe that started it (nohup-style)
        p = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)
    pid_file(port).write_text(f"{p.pid}\n")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if healthy(port):
            print(f"server started on port {port} (pid {p.pid})")
            return
        if p.poll() is not None:
            pid_file(port).unlink(missing_ok=True)
            raise Fail(f"server exited with code {p.returncode}:\n{tail(log_file(port))}")
        time.sleep(0.2)
    raise Fail(f"server not healthy after {timeout:.0f}s on port {port} (still starting? log: {log_file(port)})\n"
               f"{tail(log_file(port))}")


def tail(path: Path, n: int = 15) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def stop_server(port: int, dry: bool):
    pid = our_pid(port)
    if pid is None:
        if not dry:
            pid_file(port).unlink(missing_ok=True)  # stale
        if healthy(port):
            raise Fail(f"a server answers on port {port} but was not started by app.py (no pid file); not stopping it")
        print(f"no server running on port {port}")
        return
    if dry:
        print(f"would send SIGTERM to pid {pid}")
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if our_pid(port) is None or not Path(f"/proc/{pid}").exists():
            break
        time.sleep(0.1)
    else:
        os.kill(pid, signal.SIGKILL)
    pid_file(port).unlink(missing_ok=True)
    print(f"stopped server on port {port} (pid {pid})")


# ---------- window ----------

def find_browser(choice: str) -> tuple[str, list[str], bool]:
    """Returns (label, command prefix incl. profile flags, is_windows)."""
    if choice in ("auto", "edge", "chrome") and is_wsl():
        for name, win in WIN_BROWSERS:
            if choice not in ("auto", name):
                continue
            if "%LOCALAPPDATA%" in win:
                win = win.replace("%LOCALAPPDATA%", win_env("LOCALAPPDATA"))
            exe = to_linux(win)
            if exe.exists():
                profile = rf"{win_env('LOCALAPPDATA')}\{WIN_DIR}\{name}-profile"
                return f"{name} (Windows)", [str(exe), f"--user-data-dir={profile}"], True
    if choice in ("auto", "wslg"):
        for b in LINUX_BROWSERS:
            exe = shutil.which(b)
            if exe and not snap_stub(exe):
                snap = Path(exe).resolve() == Path("/usr/bin/snap") or b"/snap/bin/" in head(exe)
                # snap confinement forbids hidden dirs like ~/.local, its own common dir is allowed
                profile = (Path.home() / "snap/chromium/common" if snap else STATE) / "claude-telemetry-profile"
                return f"{b} (Linux)", [exe, f"--user-data-dir={profile}", f"--class={NAME}"], False
    if choice in ("auto", "default"):
        return "default browser", [], False
    raise Fail(f"browser '{choice}' not found")


def snap_stub(exe: str) -> bool:
    """Ubuntu's chromium-browser is a script that only asks to install the snap."""
    h = head(exe)
    return not h or h.startswith(b"#!") and b"snap" in h and not Path("/snap/bin/chromium").exists()


def head(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(4096)
    except OSError:
        return b""


def open_window(port: int, choice: str, wait: bool, dry: bool):
    url = f"http://127.0.0.1:{port}/"
    label, prefix, windows = find_browser(choice)
    if not prefix:
        print(f"{'would open' if dry else 'opening'} {url} in the default browser")
        if not dry:
            webbrowser.open(url)
        return
    cmd = prefix + [f"--app={url}", f"--window-size={WINDOW}", "--no-first-run", "--no-default-browser-check"]
    if dry:
        print(f"would run ({label}): {' '.join(cmd)}")
        return
    p = subprocess.Popen(cmd, cwd="/mnt/c" if windows else HERE, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print(f"opened {url} with {label}")
    if wait:  # keeps wsl.exe (and so the distro with the server) alive while the window is open
        p.wait()


# ---------- icon ----------

def icon_rgba(size: int) -> bytes:
    """The favicon from index.html (16x16 viewBox) rasterised with 4x4 supersampling."""
    bars = [(3, 12, 8), (6.3, 12, 5), (9.7, 12, 7), (13, 12, 3)]  # x, y bottom, y top; stroke 2, round caps
    bg, fg, ss = (0x11, 0x11, 0x11), (0xFF, 0xD1, 0x00), 4
    out = bytearray()
    for py in range(size):
        for px in range(size):
            inside = on_bar = 0
            for sy in range(ss):
                for sx in range(ss):
                    x, y = (px + (sx + 0.5) / ss) * 16 / size, (py + (sy + 0.5) / ss) * 16 / size
                    cx, cy = min(max(x, 3), 13), min(max(y, 3), 13)  # rounded rect, rx 3
                    if (x - cx) ** 2 + (y - cy) ** 2 > 9:
                        continue
                    inside += 1
                    if any((x - bx) ** 2 + (y - min(max(y, top), bot)) ** 2 <= 1 for bx, bot, top in bars):
                        on_bar += 1
            if not inside:
                out += b"\0\0\0\0"
                continue
            f = on_bar / inside
            out += bytes(round(b + (c - b) * f) for b, c in zip(bg, fg)) + bytes([round(255 * inside / ss ** 2)])
    return bytes(out)


def png(size: int) -> bytes:
    rgba, row = icon_rgba(size), size * 4
    raw = b"".join(b"\0" + rgba[y * row:(y + 1) * row] for y in range(size))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(sizes=(16, 24, 32, 48, 64, 256)) -> bytes:
    """PNG-in-ICO (supported since Windows Vista)."""
    images = [png(s) for s in sizes]
    head, offset = struct.pack("<HHH", 0, 1, len(sizes)), 6 + 16 * len(sizes)
    for s, img in zip(sizes, images):
        head += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    return head + b"".join(images)


# ---------- shortcut ----------

def shortcut_paths() -> list[str]:
    out = powershell("[Environment]::GetFolderPath('Desktop'); [Environment]::GetFolderPath('Programs')", False)
    return [rf"{d}\{NAME}.lnk" for d in out.splitlines() if d.strip()]


def install_shortcut(port: int, dry: bool):
    if not is_wsl():
        raise Fail("--install-shortcut creates a Windows shortcut and needs WSL")
    distro = os.environ.get("WSL_DISTRO_NAME")
    if not distro:
        raise Fail("WSL_DISTRO_NAME is not set")
    win_dir = rf"{win_env('LOCALAPPDATA')}\{WIN_DIR}"
    icon = rf"{win_dir}\claude-telemetry.ico"
    # wslg.exe is a GUI-subsystem wsl.exe: no console window; plain wsl.exe as fallback (minimized)
    wslg = r"C:\Program Files\WSL\wslg.exe"
    target, style = (wslg, 1) if to_linux(wslg).exists() else (r"C:\Windows\System32\wsl.exe", 7)
    args = f"-d {distro} --cd ~ -- {sys.executable} {HERE / 'app.py'} --wait"
    if port != 8765:
        args += f" --port {port}"
    if dry:
        print(f"would write icon {icon}")
    else:
        to_linux(win_dir).mkdir(parents=True, exist_ok=True)
        to_linux(icon).write_bytes(ico())
    lines = ["$sh = New-Object -ComObject WScript.Shell"]
    for lnk in shortcut_paths():
        lines += [f"$l = $sh.CreateShortcut({ps_str(lnk)})", f"$l.TargetPath = {ps_str(target)}",
                  f"$l.Arguments = {ps_str(args)}", f"$l.IconLocation = {ps_str(icon + ',0')}",
                  f"$l.WindowStyle = {style}", f"$l.Description = {ps_str('Claude Code telemetry dashboard')}",
                  "$l.Save()", f"Write-Output {ps_str(lnk)}"]
    out = powershell("\n".join(lines), dry)
    for lnk in out.splitlines():
        print(f"created {lnk}")


def uninstall_shortcut(dry: bool):
    if not is_wsl():
        raise Fail("--uninstall-shortcut needs WSL")
    for lnk in shortcut_paths():
        p = to_linux(lnk)
        if p.exists():
            print(f"{'would remove' if dry else 'removed'} {lnk}")
            if not dry:
                p.unlink()
    print(f"(browser profile and icon stay in %LOCALAPPDATA%\\{WIN_DIR}; delete it to reset window/permissions)")


# ---------- main ----------

def status(port: int, choice: str):
    pid = our_pid(port)
    state = "healthy" if healthy(port) else "not answering"
    print(f"server   http://127.0.0.1:{port}/ {state}"
          + (f", pid {pid} (started by app.py)" if pid else ", no pid file" if state == "healthy" else ""))
    print(f"log      {log_file(port)}")
    try:
        label, prefix, _ = find_browser(choice)
        print(f"window   {label}" + (f": {prefix[0]}" if prefix else ""))
    except Fail as e:
        print(f"window   {e}")


def gui_error(msg: str):
    """Started from the shortcut there is no console: show the error in a message box."""
    script = ("Add-Type -AssemblyName PresentationFramework; "
              f"[System.Windows.MessageBox]::Show({ps_str(msg)}, {ps_str(NAME)}, 'OK', 'Error') | Out-Null")
    try:
        powershell(script, False)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--browser", choices=["auto", "edge", "chrome", "wslg", "default"], default="auto")
    ap.add_argument("--timeout", type=float, default=60, help="seconds to wait for the server to become healthy")
    ap.add_argument("--dry-run", action="store_true", help="print what would be executed, launch nothing")
    ap.add_argument("--wait", action="store_true",
                    help="stay running while the window is open, errors as message box (used by the shortcut)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--stop", action="store_true", help="stop the background server")
    g.add_argument("--status", action="store_true")
    g.add_argument("--install-shortcut", action="store_true", help="Windows Desktop + Start menu shortcut")
    g.add_argument("--uninstall-shortcut", action="store_true")
    g.add_argument("--write-icon", type=Path, metavar="FILE", help="write the .ico and exit")
    args = ap.parse_args()

    try:
        if args.stop:
            stop_server(args.port, args.dry_run)
        elif args.status:
            status(args.port, args.browser)
        elif args.install_shortcut:
            install_shortcut(args.port, args.dry_run)
        elif args.uninstall_shortcut:
            uninstall_shortcut(args.dry_run)
        elif args.write_icon:
            args.write_icon.write_bytes(ico())
            print(f"wrote {args.write_icon}")
        else:
            start_server(args.port, args.timeout, args.dry_run)
            open_window(args.port, args.browser, args.wait, args.dry_run)
    except Fail as e:
        print(f"error: {e}", file=sys.stderr)
        if args.wait and not sys.stderr.isatty() and is_wsl():
            gui_error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
