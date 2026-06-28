import os
import json
import time
from urllib.parse import urlparse
from mitmproxy import http

class RuleLoader:
    def __init__(self, path):
        self.path = path
        self.last_mtime = 0
        self.rules = []
        self.start_time = 0
        self.end_time = None
        self.reload()

    def reload(self):
        try:
            if not os.path.exists(self.path):
                self.rules = []
                self.start_time = 0
                self.end_time = None
                return
            mtime = os.path.getmtime(self.path)
            if mtime > self.last_mtime:
                self.last_mtime = mtime
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.rules = data.get("rules", [])
                    self.start_time = data.get("start_time", 0)
                    self.end_time = data.get("end_time")
        except Exception:
            pass  # Fallback to current loaded values on transient read errors

class ReronoBlocker:
    def __init__(self, rules_path):
        self.loader = RuleLoader(rules_path)

    def request(self, flow: http.HTTPFlow) -> None:
        self.loader.reload()
        
        # Check if duration has expired
        if self.loader.end_time is not None:
            if time.time() > self.loader.end_time:
                return  # Block expired, allow traffic
        
        url = flow.request.pretty_url
        is_blocked = should_block(url, self.loader.rules)
        
        # Check referer header for client-side navigation (SPA) block support
        if not is_blocked:
            referer = flow.request.headers.get("referer", "")
            if referer and should_block(referer, self.loader.rules):
                is_blocked = True
        
        # Deep block YouTube Shorts AJAX/API requests if youtube.com/shorts is in the block list
        if not is_blocked and ("youtube.com" in url or "youtubei.googleapis.com" in url):
            has_shorts_rule = any("youtube.com/shorts" in r.lower() or r.lower() == "youtube.com" for r in self.loader.rules)
            if has_shorts_rule:
                if "/youtubei/v1/reel" in url:
                    is_blocked = True
                elif "/youtubei/v1/browse" in url and flow.request.method == "POST":
                    try:
                        body = flow.request.get_text()
                        if body and "FEshorts" in body:
                            is_blocked = True
                    except Exception:
                        pass
        
        if is_blocked:
            # Check if this is an AJAX/fetch request or subresource
            dest = flow.request.headers.get("sec-fetch-dest", "").lower()
            accept = flow.request.headers.get("accept", "").lower()
            is_ajax = dest in ["empty", "script", "style", "image", "font"] or "application/json" in accept or flow.request.headers.get("x-requested-with")
            
            if is_ajax:
                flow.response = http.Response.make(
                    403,
                    b"Blocked by Rerono",
                    {"Content-Type": "text/plain"}
                )
            else:
                # Block the request and return custom focus page
                html_content = generate_block_page(
                    url=url,
                    end_time=self.loader.end_time,
                    start_time=self.loader.start_time
                )
                flow.response = http.Response.make(
                    403,
                    html_content.encode("utf-8"),
                    {"Content-Type": "text/html"}
                )

DEVELOPER_BYPASS_DOMAINS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "antigravity.google",
    "antigravity-unleash.goog",
    "google-antigravity.com",
}

def should_block(url: str, block_rules: list) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path
        
        # Strip port if present
        if ":" in host:
            host = host.split(":")[0]
            
        # Check if the host matches any domain in the developer bypass list (including subdomains)
        for bypass_dom in DEVELOPER_BYPASS_DOMAINS:
            if host == bypass_dom or host.endswith("." + bypass_dom):
                return False
                
        for rule in block_rules:
            rule = rule.lower().strip()
            if not rule:
                continue
                
            if "/" in rule:
                rule_host, rule_path = rule.split("/", 1)
                rule_path = "/" + rule_path
                # Check host (either exact or subdomain match)
                if host == rule_host or host.endswith("." + rule_host):
                    # Check path prefix
                    if path.startswith(rule_path):
                        return True
            else:
                # Domain match only
                if host == rule or host.endswith("." + rule):
                    return True
    except Exception:
        pass
    return False

def generate_block_page(url: str, end_time: float, start_time: float) -> str:
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        display_url = parsed.netloc + parsed.path
    except Exception:
        display_url = url
        
    if len(display_url) > 60:
        display_url = display_url[:57] + "..."

    js_end_time = end_time if end_time else 0
    js_start_time = start_time if start_time else 0
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Blocked by Rerono</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Plus+Jakarta+Sans:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #080a10;
            --card-bg: rgba(13, 17, 28, 0.45);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #ffffff;
            --text-secondary: #8b949e;
            --accent-primary: #8a2be2;
            --accent-secondary: #ff007f;
            --glow-color: rgba(138, 43, 226, 0.15);
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            background-color: var(--bg-color);
            background-image: 
                radial-gradient(at 10% 10%, rgba(138, 43, 226, 0.08) 0px, transparent 50%),
                radial-gradient(at 90% 90%, rgba(255, 0, 127, 0.05) 0px, transparent 50%);
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            color: var(--text-primary);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
        }}

        .container {{
            width: 100%;
            max-width: 500px;
            padding: 24px;
            text-align: center;
            position: relative;
            z-index: 10;
        }}

        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 28px;
            padding: 40px 30px;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: 
                0 30px 60px rgba(0, 0, 0, 0.4),
                inset 0 1px 0 rgba(255, 255, 255, 0.1);
            position: relative;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}

        .card::before {{
            content: '';
            position: absolute;
            top: -2px;
            left: -2px;
            right: -2px;
            bottom: -2px;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            z-index: -1;
            border-radius: 30px;
            opacity: 0.15;
            filter: blur(8px);
        }}

        .logo-area {{
            margin-bottom: 24px;
            position: relative;
        }}

        .timer-circle-wrapper {{
            position: relative;
            width: 160px;
            height: 160px;
            margin-bottom: 24px;
        }}

        .timer-circle {{
            width: 100%;
            height: 100%;
            transform: rotate(-90deg);
        }}

        .timer-circle circle {{
            fill: none;
            stroke-width: 6;
        }}

        .timer-circle-bg {{
            stroke: rgba(255, 255, 255, 0.03);
        }}

        .timer-circle-progress {{
            stroke: url(#gradient);
            stroke-linecap: round;
            transition: stroke-dashoffset 1s linear;
        }}

        .lock-icon-container {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            display: flex;
            flex-direction: column;
            align-items: center;
        }}

        .lock-icon {{
            width: 38px;
            height: 38px;
            fill: #fff;
            filter: drop-shadow(0 0 8px var(--accent-primary));
            animation: pulse 3s infinite ease-in-out;
        }}

        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); filter: drop-shadow(0 0 8px var(--accent-primary)); }}
            50% {{ transform: scale(1.08); filter: drop-shadow(0 0 16px var(--accent-secondary)); }}
        }}

        h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 28px;
            font-weight: 800;
            margin-bottom: 12px;
            background: linear-gradient(135deg, #fff 40%, #c3b4fc 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }}

        .target-url {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.05);
            padding: 8px 16px;
            border-radius: 12px;
            font-family: monospace;
            font-size: 14px;
            color: #d1d5db;
            display: inline-block;
            margin-bottom: 24px;
            word-break: break-all;
            max-width: 100%;
        }}

        .countdown {{
            font-family: 'Outfit', sans-serif;
            font-size: 36px;
            font-weight: 600;
            margin-bottom: 12px;
            color: #fff;
            letter-spacing: 1px;
            display: flex;
            gap: 12px;
            justify-content: center;
        }}

        .countdown-segment {{
            display: flex;
            flex-direction: column;
            align-items: center;
        }}

        .countdown-value {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            min-width: 60px;
            padding: 6px 10px;
            font-weight: 600;
        }}

        .countdown-label {{
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
            margin-top: 6px;
            letter-spacing: 1.5px;
            font-weight: 600;
        }}

        .countdown-separator {{
            font-size: 32px;
            color: rgba(255, 255, 255, 0.2);
            line-height: 50px;
        }}

        .tagline {{
            font-size: 15px;
            color: var(--text-secondary);
            max-width: 320px;
            line-height: 1.6;
            margin-top: 10px;
        }}

        .quote-container {{
            margin-top: 24px;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
            padding-top: 20px;
            width: 100%;
        }}

        .quote {{
            font-style: italic;
            font-size: 13px;
            color: #8b949e;
            line-height: 1.5;
        }}

        .quote-author {{
            font-size: 11px;
            color: var(--accent-secondary);
            margin-top: 6px;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="timer-circle-wrapper">
                <svg class="timer-circle" viewBox="0 0 100 100">
                    <defs>
                        <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="var(--accent-primary)" />
                            <stop offset="100%" stop-color="var(--accent-secondary)" />
                        </linearGradient>
                    </defs>
                    <circle class="timer-circle-bg" cx="50" cy="50" r="45" />
                    <circle class="timer-circle-progress" id="progress-circle" cx="50" cy="50" r="45" stroke-dasharray="282.7" stroke-dashoffset="0" />
                </svg>
                <div class="lock-icon-container">
                    <svg class="lock-icon" viewBox="0 0 24 24">
                        <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/>
                    </svg>
                </div>
            </div>

            <h1>Focus Active</h1>
            <div class="target-url">{display_url}</div>

            <div id="countdown-container" class="countdown" style="display: none;">
                <div class="countdown-segment">
                    <div id="hours" class="countdown-value">00</div>
                    <div class="countdown-label">Hours</div>
                </div>
                <div class="countdown-separator">:</div>
                <div class="countdown-segment">
                    <div id="minutes" class="countdown-value">00</div>
                    <div class="countdown-label">Mins</div>
                </div>
                <div class="countdown-separator">:</div>
                <div class="countdown-segment">
                    <div id="seconds" class="countdown-value">00</div>
                    <div class="countdown-label">Secs</div>
                </div>
            </div>

            <div id="indefinite-status" class="countdown-label" style="letter-spacing: 2px; font-size: 12px; color: var(--accent-secondary);">
                Blocked Indefinitely
            </div>

            <p class="tagline">Rerono is helping you avoid distractions. Get back to work!</p>

            <div class="quote-container">
                <p class="quote" id="motivational-quote">"Focus is a matter of deciding what things you're not going to do."</p>
                <p class="quote-author" id="quote-author">John Carmack</p>
            </div>
        </div>
    </div>

    <script>
        const endTime = {js_end_time};
        const startTime = {js_start_time};
        
        const quotes = [
            {{ text: "Focus is a matter of deciding what things you're not going to do.", author: "John Carmack" }},
            {{ text: "The successful warrior is the average man, with laser-like focus.", author: "Bruce Lee" }},
            {{ text: "It is during our darkest moments that we must focus to see the light.", author: "Aristotle" }},
            {{ text: "Concentrate all your thoughts upon the work at hand. The sun's rays do not burn until brought to a focus.", author: "Alexander Graham Bell" }},
            {{ text: "You can do anything, but not everything.", author: "David Allen" }},
            {{ text: "Only the paranoid survive.", author: "Andy Grove" }}
        ];
        
        const randomQuote = quotes[Math.floor(Math.random() * quotes.length)];
        document.getElementById('motivational-quote').innerText = `"${{randomQuote.text}}"`;
        document.getElementById('quote-author').innerText = randomQuote.author;

        const progressCircle = document.getElementById('progress-circle');
        const totalLength = 282.7;

        function updateTimer() {{
            if (endTime === 0) {{
                document.getElementById('indefinite-status').style.display = 'block';
                document.getElementById('countdown-container').style.display = 'none';
                progressCircle.style.strokeDashoffset = '0';
                return;
            }}

            document.getElementById('indefinite-status').style.display = 'none';
            document.getElementById('countdown-container').style.display = 'flex';

            const now = Math.floor(Date.now() / 1000);
            const totalDuration = endTime - startTime;
            const remaining = endTime - now;

            if (remaining <= 0) {{
                document.getElementById('hours').innerText = '00';
                document.getElementById('minutes').innerText = '00';
                document.getElementById('seconds').innerText = '00';
                progressCircle.style.strokeDashoffset = totalLength.toString();
                setTimeout(() => location.reload(), 1500);
                return;
            }}

            if (totalDuration > 0) {{
                const pct = Math.max(0, Math.min(1, remaining / totalDuration));
                const offset = totalLength * (1 - pct);
                progressCircle.style.strokeDashoffset = offset.toString();
            }}

            const hrs = Math.floor(remaining / 3600);
            const mins = Math.floor((remaining % 3600) / 60);
            const secs = remaining % 60;

            document.getElementById('hours').innerText = String(hrs).padStart(2, '0');
            document.getElementById('minutes').innerText = String(mins).padStart(2, '0');
            document.getElementById('seconds').innerText = String(secs).padStart(2, '0');
        }}

        updateTimer();
        setInterval(updateTimer, 1000);
    </script>
</body>
</html>
"""

# The active rules configuration path will be set by the main runner via environment variable
rules_path = os.environ.get("RERONO_ACTIVE_RULES_PATH", os.path.expanduser("~/.rerono/active_rules.json"))
blocker = ReronoBlocker(rules_path)

def request(flow: http.HTTPFlow) -> None:
    blocker.request(flow)
