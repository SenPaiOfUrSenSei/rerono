import os
import sys
import json
import time
import signal
import argparse
import subprocess
from pathlib import Path

# Default rules template
DEFAULT_RULES_YAML = """# Rerono configuration file.
# Predefined lists of URLs/domains to block.
# You can reference these lists by name (e.g. 'rerono start social')
# Or specify individual domains/URLs directly.

default:
  - youtube.com/shorts
  - instagram.com/reels
  - facebook.com/watch
  - tiktok.com

social:
  - facebook.com
  - instagram.com
  - twitter.com
  - x.com
  - tiktok.com

productivity:
  - reddit.com
  - youtube.com
  - twitch.tv
"""

def get_config_dir() -> Path:
    if os.name == 'nt':
        return Path.home() / ".rerono"
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME")
        if config_home:
            return Path(config_home) / "rerono"
        else:
            return Path.home() / ".config" / "rerono"

def get_state_dir() -> Path:
    return Path.home() / ".rerono"

def ensure_config_exists() -> Path:
    config_dir = get_config_dir()
    config_file = config_dir / "rules.yaml"
    if not config_file.exists():
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                f.write(DEFAULT_RULES_YAML)
            print(f"Created default configuration file at: {config_file}")
        except Exception as e:
            print(f"Warning: Could not create default config: {e}")
    return config_file

def parse_simple_yaml(content: str) -> dict:
    import re
    data = {}
    current_key = None
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Check for list key (e.g., "default:")
        if line.endswith(":"):
            current_key = line[:-1].strip()
            data[current_key] = []
        elif line.startswith("-") and current_key:
            val = line[1:].strip()
            val = re.sub(r'^["\']|["\']$', '', val)
            data[current_key].append(val)
        elif ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if val.startswith("-"):
                val = val[1:].strip()
            val = re.sub(r'^["\']|["\']$', '', val)
            current_key = key
            data[current_key] = [val] if val else []
    return data

def load_yaml_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return parse_simple_yaml(content)
    except Exception as e:
        print(f"Error reading configuration file: {e}")
        return {}

def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except socket.error:
            return True

def set_windows_proxy(enabled: bool, host="127.0.0.1", port=8080) -> bool:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
        try:
            if enabled:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
            else:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        finally:
            winreg.CloseKey(key)

        # Notify system of settings change
        import ctypes
        INTERNET_OPTION_SETTINGS_CHANGED = 39
        INTERNET_OPTION_REFRESH = 37
        ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
        return True
    except Exception as e:
        print(f"Error setting Windows proxy: {e}")
        return False

def set_linux_proxy(enabled: bool, host="127.0.0.1", port=8080) -> bool:
    gnome_success = False
    try:
        # Check if gsettings is available
        subprocess.run(["gsettings", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        mode = "manual" if enabled else "none"
        subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", mode], check=True)
        if enabled:
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.http", "host", host], check=True)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.http", "port", str(port)], check=True)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.https", "host", host], check=True)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.https", "port", str(port)], check=True)
        gnome_success = True
    except Exception:
        pass
        
    kde_success = False
    for kwriteconfig in ["kwriteconfig6", "kwriteconfig5"]:
        try:
            subprocess.run([kwriteconfig, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proxy_type = "1" if enabled else "0"
            subprocess.run([kwriteconfig, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "ProxyType", proxy_type], check=True)
            if enabled:
                subprocess.run([kwriteconfig, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "httpProxy", f"http://{host}:{port}"], check=True)
                subprocess.run([kwriteconfig, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "httpsProxy", f"http://{host}:{port}"], check=True)
            subprocess.run(["dbus-send", "--type=signal", "/KIO/Scheduler", "org.kde.KIO.Scheduler.reparseConfiguration"], check=True)
            kde_success = True
            break
        except Exception:
            pass
            
    if not gnome_success and not kde_success:
        if enabled:
            print("\n[Notice] Could not set system proxy automatically (GNOME or KDE not detected/supported).")
            print("Please configure your system or browser proxy manually:")
            print(f"  HTTP/HTTPS Proxy Host: {host}")
            print(f"  HTTP/HTTPS Proxy Port: {port}")
            print("Or set these environment variables in your terminal:")
            print(f"  export http_proxy=http://{host}:{port}")
            print(f"  export https_proxy=http://{host}:{port}")
        return False
    return True

def set_system_proxy(enabled: bool, host="127.0.0.1", port=8080) -> bool:
    if os.name == 'nt':
        return set_windows_proxy(enabled, host, port)
    else:
        return set_linux_proxy(enabled, host, port)

def get_mitm_ca_path() -> Path:
    home = Path.home()
    mitm_dir = home / ".mitmproxy"
    if os.name == 'nt':
        return mitm_dir / "mitmproxy-ca-cert.cer"
    else:
        return mitm_dir / "mitmproxy-ca-cert.pem"

def ensure_ca_certificates() -> Path:
    ca_path = get_mitm_ca_path()
    if not ca_path.exists():
        print("Mitmproxy CA certificate not found. Starting mitmdump briefly to generate it...")
        # We start mitmdump on a high port so that it initializes proxying and generates CA certs
        proc = subprocess.Popen(
            ["uv", "tool", "run", "--from", "mitmproxy", "mitmdump", "-p", "61023"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL
        )
        start_time = time.time()
        while time.time() - start_time < 12:
            if ca_path.exists():
                break
            time.sleep(0.5)
        proc.terminate()
        proc.wait()
        
    if not ca_path.exists():
        raise RuntimeError("Failed to generate mitmproxy CA certificates. Please verify that 'uv' is working.")
    return ca_path

def trust_ca_windows(ca_path: Path) -> bool:
    try:
        result = subprocess.run([
            "certutil", "-addstore", "-user", "Root", str(ca_path)
        ], capture_output=True, text=True)
        if result.returncode == 0:
            print("Successfully trusted mitmproxy CA certificate in Windows User certificate store.")
            return True
        else:
            print(f"Warning: Failed to trust CA certificate. certutil error: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"Warning: Failed to run certutil to trust CA certificate: {e}")
        return False

def trust_ca_linux_nss(pem_path: Path) -> bool:
    nss_db_dir = Path.home() / ".pki" / "nssdb"
    if not nss_db_dir.exists():
        try:
            nss_db_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
            
    try:
        subprocess.run(["certutil", "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        print("Note: NSS certutil is not installed. Skipping automatic Chrome/NSS certificate trust.")
        return False
        
    try:
        subprocess.run([
            "certutil", "-d", f"sql:{Path.home()}/.pki/nssdb", 
            "-A", "-t", "C,,", "-n", "Rerono mitmproxy CA", "-i", str(pem_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Successfully trusted Rerono CA in Chromium/NSS certificate store.")
        return True
    except Exception as e:
        print(f"Note: Failed to add CA to NSS store automatically: {e}")
        return False

def print_linux_ca_instructions(pem_path: Path):
    print("\n[HTTPS Certificate Instruction]")
    print("To block HTTPS pages (like youtube.com/shorts) without security warnings,")
    print("please trust the locally generated certificate in your system or browser:")
    print(f"  Certificate File: {pem_path}")
    print("\nFor System-wide Trust (Debian/Ubuntu):")
    print(f"  sudo cp {pem_path} /usr/local/share/ca-certificates/rerono-ca.crt")
    print("  sudo update-ca-certificates")
    print("\nFor Firefox:")
    print("  Go to Settings -> Privacy & Security -> Certificates -> View Certificates -> Authorities -> Import,")
    print("  select the certificate file above, and check 'Trust this CA to identify websites'.")

def get_addon_path() -> str:
    package_dir = os.path.dirname(os.path.abspath(__file__))
    addon_path = os.path.join(package_dir, "blocker_addon.py")
    return addon_path

def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == 'nt':
        try:
            import ctypes
            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_SYNCHRONIZE = 0x0010
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SYNCHRONIZE, False, pid)
            if handle == 0:
                return False
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            is_active = (exit_code.value == 259) # 259 is STILL_ACTIVE
            ctypes.windll.kernel32.CloseHandle(handle)
            return is_active
        except Exception:
            try:
                out = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}"], text=True)
                return str(pid) in out
            except Exception:
                return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

def kill_process(pid: int):
    if pid <= 0:
        return
    if os.name == 'nt':
        import signal
        try:
            os.kill(pid, signal.CTRL_BREAK_EVENT)
            start_time = time.time()
            while time.time() - start_time < 2:
                if not is_pid_alive(pid):
                    return
                time.sleep(0.1)
        except Exception:
            pass
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    else:
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
            start_time = time.time()
            while time.time() - start_time < 2:
                if not is_pid_alive(pid):
                    return
                time.sleep(0.1)
        except OSError:
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

def setup_signals(handler):
    if os.name != 'nt':
        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)
    else:
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGBREAK, handler)

def log_error(msg: str):
    state_dir = get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / "rerono.log"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] ERROR: {msg}\n")
    except Exception:
        pass

def run_controller():
    state_dir = get_state_dir()
    active_path = state_dir / "active_rules.json"
    
    if not active_path.exists():
        sys.exit("No active rules file found.")
        
    try:
        with open(active_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        sys.exit(f"Failed to read active rules: {e}")
        
    port = state.get("port", 8080)
    end_time = state.get("end_time")
    
    # Save controller PID
    state["controller_pid"] = os.getpid()
    try:
        with open(active_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log_error(f"Failed to write controller PID: {e}")
        
    mitm_proc = None
    exit_requested = False
    
    def signal_handler(signum, frame):
        nonlocal exit_requested
        exit_requested = True
        
    setup_signals(signal_handler)
    
    # Enable system proxy
    proxy_enabled = set_system_proxy(True, "127.0.0.1", port)
    if not proxy_enabled:
        log_error("Could not set system proxy. Running proxy server only.")
        
    try:
        ca_path = ensure_ca_certificates()
    except Exception as e:
        log_error(f"CA Certificate error: {e}")
        cleanup_and_exit(state_dir, port, None, 1)
        
    # Start mitmdump
    addon_path = get_addon_path()
    cmd = [
        "uv", "tool", "run", "--from", "mitmproxy", "mitmdump",
        "-q",
        "-s", addon_path,
        "-p", str(port)
    ]
    
    env = os.environ.copy()
    env["RERONO_ACTIVE_RULES_PATH"] = str(active_path)
    
    log_path = state_dir / "rerono.log"
    
    try:
        with open(log_path, "a", encoding="utf-8") as log_file:
            mitm_proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                env=env,
                preexec_fn=os.setpgrp if os.name != 'nt' else None,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            
        # Update mitmdump PID
        state["mitmdump_pid"] = mitm_proc.pid
        with open(active_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            
        # Keep running
        while not exit_requested:
            if mitm_proc.poll() is not None:
                log_error(f"mitmdump exited with code {mitm_proc.returncode}")
                break
                
            if end_time is not None and time.time() > end_time:
                break
                
            time.sleep(1)
            
    except Exception as e:
        log_error(f"Exception in main controller loop: {e}")
    finally:
        cleanup_and_exit(state_dir, port, mitm_proc, 0)

def cleanup_and_exit(state_dir: Path, port: int, mitm_proc, exit_code: int):
    # Disable system proxy
    set_system_proxy(False, "127.0.0.1", port)
    
    # Terminate mitmdump
    if mitm_proc:
        try:
            mitm_proc.terminate()
            mitm_proc.wait(timeout=2)
        except Exception:
            try:
                mitm_proc.kill()
            except Exception:
                pass
                
    # Delete active rules
    active_path = state_dir / "active_rules.json"
    if active_path.exists():
        try:
            active_path.unlink()
        except Exception:
            pass
            
    sys.exit(exit_code)

def cmd_start(targets: list, duration_mins: int, port: int):
    state_dir = get_state_dir()
    active_path = state_dir / "active_rules.json"
    
    # Check if already running
    if active_path.exists():
        try:
            with open(active_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            ctrl_pid = state.get("controller_pid", 0)
            if is_pid_alive(ctrl_pid):
                print(f"Rerono is already running (Controller PID: {ctrl_pid}).")
                print("Run 'rerono status' to check its status or 'rerono stop' to stop it.")
                return
        except Exception:
            pass
            
    # Resolve rules
    config_file = ensure_config_exists()
    config = load_yaml_config(config_file)
    
    resolved_rules = set()
    
    # Normalize a target (strip http, https, www)
    def normalize_target(t: str) -> str:
        t = t.strip().lower()
        if t.startswith("http://"):
            t = t[7:]
        elif t.startswith("https://"):
            t = t[8:]
        if t.startswith("www."):
            t = t[4:]
        return t

    if not targets:
        # Default to 'default' category if exists
        if "default" in config:
            for item in config["default"]:
                resolved_rules.add(normalize_target(item))
        else:
            print("Error: No block targets specified, and no 'default' list found in rules.yaml.")
            print("Please specify a target (e.g. 'rerono start social' or 'rerono start youtube.com/shorts').")
            return
    else:
        for t in targets:
            if t in config:
                for item in config[t]:
                    resolved_rules.add(normalize_target(item))
            else:
                resolved_rules.add(normalize_target(t))
                
    if not resolved_rules:
        print("Error: Resolved rules list is empty. Nothing to block.")
        return
        
    # Check port
    if is_port_in_use(port):
        print(f"Error: Port {port} is already in use. Choose another port with '--port <port>'.")
        return
        
    state_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare active rules JSON
    now = time.time()
    end_time = now + (duration_mins * 60) if duration_mins > 0 else None
    
    state_data = {
        "rules": list(resolved_rules),
        "start_time": now,
        "end_time": end_time,
        "port": port,
        "controller_pid": 0,
        "mitmdump_pid": 0
    }
    
    with open(active_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)
        
    # Generate and trust CA certificates
    try:
        ca_path = ensure_ca_certificates()
        if os.name == 'nt':
            trust_ca_windows(ca_path)
        else:
            nss_success = trust_ca_linux_nss(ca_path)
            if not nss_success:
                print_linux_ca_instructions(ca_path)
    except Exception as e:
        print(f"Warning: Failed to trust CA certificates: {e}")
        
    # Launch controller
    controller_cmd = [sys.executable, os.path.abspath(__file__), "--controller-worker"]
    
    if os.name == 'nt':
        subprocess.Popen(
            controller_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        subprocess.Popen(
            controller_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            preexec_fn=os.setpgrp
        )
        
    # Wait briefly for controller to write its PID
    start_wait = time.time()
    ctrl_pid = 0
    while time.time() - start_wait < 3:
        try:
            with open(active_path, "r", encoding="utf-8") as f:
                s = json.load(f)
            ctrl_pid = s.get("controller_pid", 0)
            if ctrl_pid > 0:
                break
        except Exception:
            pass
        time.sleep(0.1)
        
    print(f"\nRerono started successfully on port {port}!")
    print(f"Blocking {len(resolved_rules)} targets.")
    if duration_mins > 0:
        print(f"Duration: {duration_mins} minutes (expires in {duration_mins}m).")
    else:
        print("Duration: Indefinite (until 'rerono stop' is run).")
        
    print("\nCurrently Blocking:")
    for r in sorted(resolved_rules):
        print(f"  - {r}")
    print("\nRun 'rerono status' to check, or 'rerono stop' to stop blocking.")
    print("\n💡 Tips for Google/YouTube & Browsers:")
    print("  1. Socket Reuse: If your browser was already open, it may reuse established connections.")
    print("     Please close and restart your browser or open a new Private/Incognito window.")
    print("  2. HTTP/3 (QUIC): Google sites use UDP-based HTTP/3, which bypasses TCP proxies.")
    print("     If you can still access blocked pages, please disable QUIC in your browser:")
    print("     - Chrome/Edge: Go to chrome://flags, search 'Experimental QUIC protocol', set to 'Disabled', and relaunch.")
    print("     - Firefox: Go to about:config, search 'network.http.http3.enable', set to 'false'.")

def cmd_stop():
    state_dir = get_state_dir()
    active_path = state_dir / "active_rules.json"
    
    if not active_path.exists():
        print("Rerono is not active.")
        return
        
    try:
        with open(active_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
        
    ctrl_pid = state.get("controller_pid", 0)
    mitm_pid = state.get("mitmdump_pid", 0)
    port = state.get("port", 8080)
    
    print("Stopping Rerono...")
    
    # Graceful stop: kill controller first
    if ctrl_pid > 0 and is_pid_alive(ctrl_pid):
        kill_process(ctrl_pid)
        
    # Wait for file cleanup
    start_wait = time.time()
    cleaned = False
    while time.time() - start_wait < 3:
        if not active_path.exists():
            cleaned = True
            break
        time.sleep(0.1)
        
    if not cleaned:
        # Forceful cleanup fallback
        print("Performing forceful cleanup...")
        if ctrl_pid > 0:
            kill_process(ctrl_pid)
        if mitm_pid > 0:
            kill_process(mitm_pid)
        set_system_proxy(False, "127.0.0.1", port)
        if active_path.exists():
            try:
                active_path.unlink()
            except Exception:
                pass
                
    print("Rerono stopped successfully. System proxy settings restored.")

def cmd_status():
    state_dir = get_state_dir()
    active_path = state_dir / "active_rules.json"
    
    if not active_path.exists():
        print("Rerono is inactive (not running).")
        return
        
    try:
        with open(active_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        print(f"Error reading state: {e}")
        print("Run 'rerono clean' to reset stale files.")
        return
        
    ctrl_pid = state.get("controller_pid", 0)
    mitm_pid = state.get("mitmdump_pid", 0)
    port = state.get("port", 8080)
    rules = state.get("rules", [])
    start_time = state.get("start_time", 0)
    end_time = state.get("end_time")
    
    if not is_pid_alive(ctrl_pid):
        print("Rerono is inactive (stale session files detected).")
        print("Run 'rerono clean' to restore settings and clear state files.")
        return
        
    print("================ Rerono Status ================")
    print("Status:         ACTIVE (Running)")
    print(f"Proxy Port:     {port}")
    print(f"Controller PID: {ctrl_pid}")
    print(f"mitmdump PID:   {mitm_pid}")
    
    elapsed = time.time() - start_time
    print(f"Time Elapsed:   {elapsed/60:.1f} minutes")
    
    if end_time:
        remaining = end_time - time.time()
        if remaining > 0:
            print(f"Time Remaining: {remaining/60:.1f} minutes")
        else:
            print("Time Remaining: Expired (should stop shortly)")
    else:
        print("Time Remaining: Indefinite (Until manually stopped)")
        
    print(f"Blocked Rules ({len(rules)} total):")
    for r in sorted(rules):
        print(f"  - {r}")
    print("===============================================")

def cmd_list():
    config_file = ensure_config_exists()
    config = load_yaml_config(config_file)
    
    if not config:
        print("No categories defined or empty rules.yaml.")
        return
        
    print("Predefined lists in rules.yaml:")
    for cat, rules in config.items():
        print(f"  {cat} ({len(rules)} URLs):")
        for r in rules[:5]:
            print(f"    - {r}")
        if len(rules) > 5:
            print(f"    - ... and {len(rules) - 5} more")
    print("\nYou can start blocking a list with: rerono start <list_name>")

def cmd_clean():
    print("Restoring proxy settings and cleaning up local files...")
    state_dir = get_state_dir()
    active_path = state_dir / "active_rules.json"
    
    # Load port if possible to turn off that specific proxy
    port = 8080
    if active_path.exists():
        try:
            with open(active_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            port = state.get("port", 8080)
            ctrl_pid = state.get("controller_pid", 0)
            mitm_pid = state.get("mitmdump_pid", 0)
            if ctrl_pid > 0:
                kill_process(ctrl_pid)
            if mitm_pid > 0:
                kill_process(mitm_pid)
        except Exception:
            pass
            
    # Force disable system proxy
    set_system_proxy(False, "127.0.0.1", port)
    
    # Delete active rules
    if active_path.exists():
        try:
            active_path.unlink()
        except Exception:
            pass
            
    print("System proxy settings restored. All Rerono state has been reset.")

def main():
    parser = argparse.ArgumentParser(
        description="Rerono: A modern cross-platform URL and domain blocker."
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Start command
    start_parser = subparsers.add_parser("start", help="Start blocking specific URLs/lists")
    start_parser.add_argument(
        "targets", nargs="*", 
        help="Named lists from rules.yaml or direct URLs (e.g. social, youtube.com/shorts)"
    )
    start_parser.add_argument(
        "-d", "--duration", type=int, default=0,
        help="Duration to block in minutes. If 0 or omitted, blocks indefinitely."
    )
    start_parser.add_argument(
        "-p", "--port", type=int, default=8080,
        help="Local proxy port (default: 8080)"
    )
    
    # Stop command
    subparsers.add_parser("stop", help="Stop blocking and restore settings")
    
    # Status command
    subparsers.add_parser("status", help="Show current block status and time remaining")
    
    # List command
    subparsers.add_parser("list", help="List predefined categories in rules.yaml")
    
    # Clean command
    subparsers.add_parser("clean", help="Forcefully restore proxy settings and reset local files")
    
    # Hidden controller worker flag
    parser.add_argument(
        "--controller-worker", action="store_true",
        help=argparse.SUPPRESS
    )
    
    args = parser.parse_args()
    
    if args.controller_worker:
        run_controller()
        return
        
    if not args.command:
        parser.print_help()
        return
        
    if args.command == "start":
        cmd_start(args.targets, args.duration, args.port)
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "status":
        cmd_status()
    elif args.command == "list":
        cmd_list()
    elif args.command == "clean":
        cmd_clean()

if __name__ == "__main__":
    main()
