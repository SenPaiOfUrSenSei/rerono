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

DEVELOPER_BYPASS_DOMAINS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "antigravity.google",
    "antigravity-unleash.goog",
    "google-antigravity.com",
}

def is_developer_bypass_domain(host: str) -> bool:
    host = host.lower().strip()
    for d in DEVELOPER_BYPASS_DOMAINS:
        if host == d or host.endswith("." + d):
            return True
    return False


def get_original_user_home() -> Path:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        import pwd
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except Exception:
            pass
    return Path.home()

def chown_to_original_user(path: Path):
    sudo_uid = os.environ.get("SUDO_UID")
    sudo_gid = os.environ.get("SUDO_GID")
    if sudo_uid and sudo_gid:
        try:
            os.chown(str(path), int(sudo_uid), int(sudo_gid))
        except Exception:
            pass

def find_uv_path() -> str:
    import shutil
    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path
        
    home = get_original_user_home()
    possible_paths = [
        home / ".local" / "bin" / "uv",
        home / ".cargo" / "bin" / "uv",
        Path("/usr/local/bin/uv"),
        Path("/usr/bin/uv")
    ]
    for p in possible_paths:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
            
    return "uv"

def setup_transparent_proxy(port: int) -> bool:
    import subprocess
    print("Setting up transparent proxy redirection via iptables and ip6tables...")
    
    def check_and_add_rule(tool: str, args: list) -> bool:
        check_args = [tool]
        for arg in args:
            if arg == "-A":
                check_args.append("-C")
            else:
                check_args.append(arg)
        try:
            res = subprocess.run(check_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                return True
        except Exception:
            pass
            
        try:
            subprocess.run([tool] + args, check=True)
            return True
        except Exception as e:
            if tool == "ip6tables":
                print(f"Warning: Failed to add ip6tables rule {args}: {e}")
                return True
            print(f"Error configuring iptables rule {args}: {e}")
            return False

    # IPv4 Redirects
    r1 = check_and_add_rule("iptables", [
        "-t", "nat", "-A", "OUTPUT", "-p", "tcp",
        "--dport", "80", "-m", "owner", "!", "--uid-owner", "root",
        "-j", "REDIRECT", "--to-ports", str(port)
    ])
    
    r2 = check_and_add_rule("iptables", [
        "-t", "nat", "-A", "OUTPUT", "-p", "tcp",
        "--dport", "443", "-m", "owner", "!", "--uid-owner", "root",
        "-j", "REDIRECT", "--to-ports", str(port)
    ])
    
    r3 = check_and_add_rule("iptables", [
        "-A", "OUTPUT", "-p", "udp", "--dport", "443",
        "-j", "REJECT"
    ])
    
    # IPv6 Redirects
    r4 = check_and_add_rule("ip6tables", [
        "-t", "nat", "-A", "OUTPUT", "-p", "tcp",
        "--dport", "80", "-m", "owner", "!", "--uid-owner", "root",
        "-j", "REDIRECT", "--to-ports", str(port)
    ])
    
    r5 = check_and_add_rule("ip6tables", [
        "-t", "nat", "-A", "OUTPUT", "-p", "tcp",
        "--dport", "443", "-m", "owner", "!", "--uid-owner", "root",
        "-j", "REDIRECT", "--to-ports", str(port)
    ])
    
    r6 = check_and_add_rule("ip6tables", [
        "-A", "OUTPUT", "-p", "udp", "--dport", "443",
        "-j", "REJECT"
    ])
    
    if r1 and r2 and r3 and r4 and r5 and r6:
        print("Transparent proxy rules and QUIC block successfully configured (IPv4 & IPv6).")
        return True
    return False

def teardown_transparent_proxy(port: int):
    import subprocess
    print("Removing transparent proxy redirection rules (IPv4 & IPv6)...")
    try:
        def delete_rule_all_occurrences(tool: str, args: list):
            while True:
                try:
                    res = subprocess.run([tool] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if res.returncode != 0:
                        break
                except Exception:
                    break

        # IPv4 Cleanup
        delete_rule_all_occurrences("iptables", [
            "-t", "nat", "-D", "OUTPUT", "-p", "tcp",
            "--dport", "80", "-m", "owner", "!", "--uid-owner", "root",
            "-j", "REDIRECT", "--to-ports", str(port)
        ])
        
        delete_rule_all_occurrences("iptables", [
            "-t", "nat", "-D", "OUTPUT", "-p", "tcp",
            "--dport", "443", "-m", "owner", "!", "--uid-owner", "root",
            "-j", "REDIRECT", "--to-ports", str(port)
        ])
        
        delete_rule_all_occurrences("iptables", [
            "-D", "OUTPUT", "-p", "udp", "--dport", "443",
            "-j", "REJECT"
        ])
        
        # IPv6 Cleanup
        delete_rule_all_occurrences("ip6tables", [
            "-t", "nat", "-D", "OUTPUT", "-p", "tcp",
            "--dport", "80", "-m", "owner", "!", "--uid-owner", "root",
            "-j", "REDIRECT", "--to-ports", str(port)
        ])
        
        delete_rule_all_occurrences("ip6tables", [
            "-t", "nat", "-D", "OUTPUT", "-p", "tcp",
            "--dport", "443", "-m", "owner", "!", "--uid-owner", "root",
            "-j", "REDIRECT", "--to-ports", str(port)
        ])
        
        delete_rule_all_occurrences("ip6tables", [
            "-D", "OUTPUT", "-p", "udp", "--dport", "443",
            "-j", "REJECT"
        ])
        
        print("Redirection rules successfully removed.")
    except Exception as e:
        print(f"Error clearing iptables: {e}")

def get_config_dir() -> Path:
    home = get_original_user_home()
    if os.name == 'nt':
        return home / ".rerono"
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME")
        if config_home:
            return Path(config_home) / "rerono"
        else:
            return home / ".config" / "rerono"

def get_state_dir() -> Path:
    return get_original_user_home() / ".rerono"

def ensure_config_exists() -> Path:
    config_dir = get_config_dir()
    config_file = config_dir / "rules.yaml"
    if not config_file.exists():
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            chown_to_original_user(config_dir)
            with open(config_file, "w", encoding="utf-8") as f:
                f.write(DEFAULT_RULES_YAML)
            chown_to_original_user(config_file)
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
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except socket.error as e:
            print(f"[Debug] Port check bind failed for 127.0.0.1:{port}: {e}")
            return True

def set_windows_proxy(enabled: bool, host="127.0.0.1", port=58291) -> bool:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
        try:
            if enabled:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
                bypass_list = "localhost;127.0.0.1;*.github.com;github.com;*.gitlab.com;gitlab.com;*.bitbucket.org;bitbucket.org;*.antigravity.google;antigravity.google;<local>"
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, bypass_list)
            else:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
                try:
                    winreg.DeleteValue(key, "ProxyOverride")
                except FileNotFoundError:
                    pass
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

def set_linux_proxy(enabled: bool, host="127.0.0.1", port=58291) -> bool:
    # Update Wayland D-Bus & systemd user session environment (for Hyprland, Sway, i3, etc.)
    try:
        val = f"http://{host}:{port}" if enabled else ""
        no_proxy_val = "localhost,127.0.0.1,0.0.0.0,::1,github.com,.github.com,gitlab.com,.gitlab.com,bitbucket.org,.bitbucket.org,antigravity.google,.antigravity.google" if enabled else ""
        subprocess.run([
            "dbus-update-activation-environment", "--systemd",
            f"http_proxy={val}", f"https_proxy={val}",
            f"HTTP_PROXY={val}", f"HTTPS_PROXY={val}",
            f"no_proxy={no_proxy_val}", f"NO_PROXY={no_proxy_val}"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

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
            
            # Set ignore-hosts to bypass developer domains
            ignore_hosts = "['localhost', '127.0.0.0/8', '::1', '*.github.com', 'github.com', '*.gitlab.com', 'gitlab.com', '*.bitbucket.org', 'bitbucket.org', '*.antigravity.google', 'antigravity.google']"
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "ignore-hosts", ignore_hosts], check=True)
        else:
            # Restore default ignore-hosts
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "ignore-hosts", "['localhost', '127.0.0.0/8', '::1']"], check=True)
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
                subprocess.run([kwriteconfig, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "NoProxyFor", "localhost,127.0.0.1,github.com,gitlab.com,bitbucket.org,antigravity.google"], check=True)
            else:
                subprocess.run([kwriteconfig, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "NoProxyFor", ""], check=True)
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

def set_system_proxy(enabled: bool, host="127.0.0.1", port=58291) -> bool:
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
            [find_uv_path(), "tool", "run", "--from", "mitmproxy", "mitmdump", "-p", "61023"],
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
    home = get_original_user_home()
    nss_db_dir = home / ".pki" / "nssdb"
    if not nss_db_dir.exists():
        try:
            nss_db_dir.mkdir(parents=True, exist_ok=True)
            chown_to_original_user(nss_db_dir)
            chown_to_original_user(home / ".pki")
        except Exception:
            pass
            
    try:
        subprocess.run(["certutil", "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        print("Note: NSS certutil is not installed. Skipping automatic Chrome/NSS certificate trust.")
        return False
        
    try:
        subprocess.run([
            "certutil", "-d", f"sql:{home}/.pki/nssdb", 
            "-A", "-t", "C,,", "-n", "Rerono mitmproxy CA", "-i", str(pem_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # NSS database files are created, we should make sure the original user owns them
        for f in ["cert9.db", "key4.db", "pkcs11.txt"]:
            db_file = nss_db_dir / f
            if db_file.exists():
                chown_to_original_user(db_file)
        print("Successfully trusted Rerono CA in Chromium/NSS certificate store.")
        return True
    except Exception as e:
        print(f"Note: Failed to add CA to NSS store automatically: {e}")
        return False

def trust_ca_linux_firefox(pem_path: Path) -> bool:
    home = get_original_user_home()
    firefox_dir = home / ".mozilla" / "firefox"
    if not firefox_dir.exists():
        return False
        
    try:
        subprocess.run(["certutil", "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
        
    success = False
    try:
        # Find all cert9.db files recursively in the firefox directory
        for p in firefox_dir.glob("**/cert9.db"):
            profile_dir = p.parent
            try:
                subprocess.run([
                    "certutil", "-d", f"sql:{profile_dir}", 
                    "-A", "-t", "C,,", "-n", "Rerono mitmproxy CA", "-i", str(pem_path)
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                # Make sure the files are owned by the original user
                for f in ["cert9.db", "key4.db", "pkcs11.txt"]:
                    db_file = profile_dir / f
                    if db_file.exists():
                        chown_to_original_user(db_file)
                success = True
            except Exception:
                pass
    except Exception:
        pass
    if success:
        print("Successfully trusted Rerono CA in Firefox certificate stores.")
    return success

def check_git_config_warning():
    try:
        res = subprocess.run(
            ["git", "config", "--global", "http.sslcainfo"],
            capture_output=True, text=True
        )
        if res.returncode == 0 and res.stdout.strip():
            val = res.stdout.strip()
            if "mitmproxy" in val.lower() or "rerono" in val.lower():
                print("\n⚠️  [Warning] Detected custom Git SSL configuration pointing to mitmproxy:")
                print(f"     http.sslcainfo = {val}")
                print("     Because Rerono now bypasses SSL decryption for unblocked sites (like GitHub),")
                print("     this will cause Git connection errors on unblocked repositories.")
                print("     We highly recommend unsetting this option so Git uses system-wide CA trust:")
                print("       git config --global --unset http.sslcainfo\n")
    except Exception:
        pass

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
        import errno
        try:
            os.kill(pid, 0)
            return True
        except OSError as e:
            return e.errno == errno.EPERM

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
        
    port = state.get("port", 58291)
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
    
    transparent = state.get("transparent", False)

    # Enable system proxy (only if not in transparent mode)
    if not transparent:
        proxy_enabled = set_system_proxy(True, "127.0.0.1", port)
        if not proxy_enabled:
            log_error("Could not set system proxy. Running proxy server only.")
    else:
        print("Transparent proxy mode enabled. System proxy changes bypassed.")
        
    try:
        ca_path = ensure_ca_certificates()
    except Exception as e:
        log_error(f"CA Certificate error: {e}")
        cleanup_and_exit(state_dir, port, None, 1)
        
    # Start mitmdump
    addon_path = get_addon_path()
    cmd = [
        find_uv_path(), "tool", "run", "--from", "mitmproxy", "mitmdump",
        "-s", addon_path,
        "-p", str(port),
        "--set", "block_global=false"
    ]
    if transparent:
        cmd += ["--mode", "transparent"]
        
    # Build allow-hosts regex to only intercept configured block domains.
    # All other domains are bypassed via SSL passthrough, preventing certificate errors.
    rules = state.get("rules", [])
    hosts = set()
    for rule in rules:
        rule = rule.strip().lower()
        if not rule:
            continue
        if "/" in rule:
            host_part = rule.split("/", 1)[0]
        else:
            host_part = rule
        if ":" in host_part:
            host_part = host_part.split(":", 1)[0]
        if host_part:
            hosts.add(host_part)
            # YouTube's InnerTube API is located at youtubei.googleapis.com.
            # If youtube.com is blocked (such as youtube.com/shorts), we must also decrypt youtubei.googleapis.com.
            if host_part == "youtube.com":
                hosts.add("youtubei.googleapis.com")
            
    # Filter out developer bypass domains from allow-hosts
    filtered_hosts = set()
    for host in hosts:
        should_bypass = False
        for bypass_dom in DEVELOPER_BYPASS_DOMAINS:
            if host == bypass_dom or host.endswith("." + bypass_dom):
                should_bypass = True
                break
        if not should_bypass:
            filtered_hosts.add(host)
    hosts = filtered_hosts
            
    if hosts:
        import re
        escaped_hosts = [re.escape(h) for h in hosts]
        hosts_regex = f"^([a-zA-Z0-9-]+\\.)*({'|'.join(escaped_hosts)})(:[0-9]+)?$"
        cmd += ["--allow-hosts", hosts_regex]
    else:
        cmd += ["--allow-hosts", "^$"]
        
    env = os.environ.copy()
    env["RERONO_ACTIVE_RULES_PATH"] = str(active_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    
    log_path = state_dir / "rerono.log"
    chown_to_original_user(log_path)
    
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
            chown_to_original_user(log_path)
            
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
    # Load transparent state if possible
    active_path = state_dir / "active_rules.json"
    transparent = False
    if active_path.exists():
        try:
            with open(active_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            transparent = state.get("transparent", False)
        except Exception:
            pass

    # Disable system proxy
    set_system_proxy(False, "127.0.0.1", port)
    
    if transparent:
        teardown_transparent_proxy(port)
        
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
    if active_path.exists():
        try:
            active_path.unlink()
        except Exception:
            pass
            
    sys.exit(exit_code)

def cmd_start(targets: list, duration_mins: int, port: int, transparent: bool = False):
    if transparent:
        if os.name == 'nt':
            sys.exit("Error: Transparent proxy mode is only supported on Linux.")
        if os.geteuid() != 0:
            sys.exit("Error: Transparent proxy mode requires root privileges. Please run via sudo:\n  sudo rerono start -t ...")

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
                
    # Filter out developer bypass domains from active block rules
    final_rules = set()
    for rule in resolved_rules:
        host_part = rule.split("/", 1)[0] if "/" in rule else rule
        if ":" in host_part:
            host_part = host_part.split(":", 1)[0]
        should_bypass = False
        for bypass_dom in DEVELOPER_BYPASS_DOMAINS:
            if host_part == bypass_dom or host_part.endswith("." + bypass_dom):
                should_bypass = True
                break
        if not should_bypass:
            final_rules.add(rule)
    resolved_rules = final_rules

    if not resolved_rules:
        print("Error: Resolved rules list is empty. Nothing to block.")
        return
        
    # Check port
    if is_port_in_use(port):
        print(f"Error: Port {port} is already in use. Choose another port with '--port <port>'.")
        return
        
    state_dir.mkdir(parents=True, exist_ok=True)
    chown_to_original_user(state_dir)
    
    # If transparent mode is requested, set up iptables redirect rules first
    if transparent:
        if not setup_transparent_proxy(port):
            sys.exit("Error: Failed to set up transparent proxy redirection rules via iptables.")
            
    # Prepare active rules JSON
    now = time.time()
    end_time = now + (duration_mins * 60) if duration_mins > 0 else None
    
    state_data = {
        "rules": list(resolved_rules),
        "start_time": now,
        "end_time": end_time,
        "port": port,
        "transparent": transparent,
        "controller_pid": 0,
        "mitmdump_pid": 0
    }
    
    with open(active_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)
    chown_to_original_user(active_path)
        
    # Generate and trust CA certificates
    try:
        ca_path = ensure_ca_certificates()
        if os.name == 'nt':
            trust_ca_windows(ca_path)
        else:
            nss_success = trust_ca_linux_nss(ca_path)
            trust_ca_linux_firefox(ca_path)
            if not nss_success:
                print_linux_ca_instructions(ca_path)
    except Exception as e:
        print(f"Warning: Failed to trust CA certificates: {e}")
        
    check_git_config_warning()
        
    # Launch controller
    controller_cmd = [sys.executable, os.path.abspath(__file__), "--controller-worker"]
    controller_env = os.environ.copy()
    controller_env["PYTHONDONTWRITEBYTECODE"] = "1"
    
    if os.name == 'nt':
        subprocess.Popen(
            controller_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            env=controller_env
        )
    else:
        subprocess.Popen(
            controller_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            preexec_fn=os.setpgrp,
            env=controller_env
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
    
    # Check if user is on a window manager (like Hyprland, sway, i3, etc.) on Linux
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    is_wm = False
    if os.name != 'nt' and desktop and not any(de in desktop for de in ["gnome", "kde", "xfce", "mate", "cinnamon"]):
        is_wm = True
        
    if is_wm:
        print(f"  ⚠️  Window Manager Detected ({os.environ.get('XDG_CURRENT_DESKTOP')}):")
        print("     Browsers running under window managers often ignore system-wide desktop proxy settings.")
        print("     Please configure your browser manually to route traffic through the proxy:")
        print(f"     - Chrome/Edge/Brave: Close all instances and relaunch from your terminal with:")
        print(f"       google-chrome-stable --proxy-server=\"http://127.0.0.1:{port}\"")
        print(f"     - Firefox: Settings -> Network Settings -> Manual Proxy: Host 127.0.0.1, Port {port} (check 'Also use this proxy for HTTPS')")
    else:
        print("  1. Socket Reuse: If your browser was already open, it may reuse established connections.")
        print("     Please close and restart your browser or open a new Private/Incognito window.")
        
    num = 3 if is_wm else 2
    print(f"  {num}. HTTP/3 (QUIC): Google sites use UDP-based HTTP/3, which bypasses TCP proxies.")
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
    port = state.get("port", 58291)
    transparent = state.get("transparent", False)
    
    # If transparent mode was used, we require root to clean up iptables
    if transparent and os.name != 'nt' and os.geteuid() != 0:
        sys.exit("Error: Stopping Rerono in transparent mode requires root privileges. Please run via sudo:\n  sudo rerono stop")
        
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
        if not transparent:
            set_system_proxy(False, "127.0.0.1", port)
        else:
            teardown_transparent_proxy(port)
            
        if active_path.exists():
            try:
                active_path.unlink()
            except Exception:
                pass
                
    print("Rerono stopped successfully. System settings restored.")

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
    port = state.get("port", 58291)
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
    port = 58291
    transparent = False
    if active_path.exists():
        try:
            with open(active_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            port = state.get("port", 58291)
            transparent = state.get("transparent", False)
            ctrl_pid = state.get("controller_pid", 0)
            mitm_pid = state.get("mitmdump_pid", 0)
            if ctrl_pid > 0:
                kill_process(ctrl_pid)
            if mitm_pid > 0:
                kill_process(mitm_pid)
        except Exception:
            pass
            
    # Force disable system proxy
    if not transparent:
        set_system_proxy(False, "127.0.0.1", port)
    
    # Clear transparent proxy if applicable
    if os.name != 'nt' and (transparent or os.geteuid() == 0):
        if os.geteuid() == 0:
            teardown_transparent_proxy(port)
        else:
            print("Note: Transparent proxy redirection rules could not be cleared because 'clean' was not run as root/sudo.")
            print("Please run: sudo rerono clean")
            
    # Delete active rules
    if active_path.exists():
        try:
            active_path.unlink()
        except Exception:
            pass
            
    print("System settings restored. All Rerono state has been reset.")

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
        "-p", "--port", type=int, default=58291,
        help="Local proxy port (default: 58291)"
    )
    start_parser.add_argument(
        "-t", "--transparent", action="store_true",
        help="Enable transparent proxy NAT redirection (Linux only, requires sudo/root)"
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
        cmd_start(args.targets, args.duration, args.port, args.transparent)
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
