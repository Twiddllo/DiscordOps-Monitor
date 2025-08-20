
I build reliable systems, automate the boring stuff, and keep services up even when things get noisy. Strong focus on **observability**, **incident response**, and **practical automation**.

---

## Highlights
- **Incident-savvy**: on-call mindset, root cause over band‑aids.
- **Automator**: Python + Bash for glue, IaC with Terraform/Ansible, CI/CD that actually ships.
- **Observability first**: Prometheus, Grafana, Loki/ELK, tracing, and alerting that isn’t spammy.
- **Cloud + Linux**: Containers (Docker), Kubernetes, and the usual cloud suspects (AWS/GCP).

---

## Featured Project — Host Guardian (Discord CPU Sentry)
> A tiny “SRE‑style” daemon that watches host CPU, alerts to Discord when it crosses a threshold, and lets you take action.

**Why it matters:** it shows practical SRE thinking: measure what matters, alert only when needed, include **actionable context** (top offenders), and provide a **safe remediation path**.

**What it does**
- Sends a **Discord webhook alert** if total CPU > **90%** (with cooldown to prevent spam).
- Includes **Top 3 CPU hogs** (normalized to 0–100% total CPU).
- Slash command **`/topcpu`**: snapshot Top 10 processes with live CPU%.
- Slash command **`/terminate <index>`**: safely kill a selected process from the latest `/topcpu` list.
- Slash command **`/status`**: live‑updating embed every **2s for 5 minutes** with CPU/RAM + Top 3.

---

## Screens (add yours)
- Alert embed when CPU crosses threshold
- `/topcpu` result list
- `/status` live view

> Paste screenshots/gifs here to make the repo pop on GitHub and Telegram.

---

## Stack
- **Language:** Python 3.11+
- **Libs:** discord.py (slash commands), psutil, httpx
- **Ops:** Linux, systemd (optional), Docker (optional)

---

## Quickstart
1. **Clone**

   ```bash
   git clone https://github.com/Twiddllo/DiscordOps-Monitor.git
   cd DiscordOps-Monitor
   ```



2. **Install**

   ```bash
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -U pip
   pip install discord.py psutil httpx
   ```

3. **Configure**

   * Option A (env vars):

     ```bash
     export DISCORD_TOKEN="your-bot-token"
     export GUILD_ID="123456789012345678"          # your Discord server id
     export CPU_ALERT_WEBHOOK="https://discord.com/api/webhooks/.../..."
     export ICON_URL="https://cdn.example.com/icon.png"  # optional
     export BOT_STATUS="Monitoring host"                 # optional
     ```
   * Option B (`config.json` at repo root):

     ```json
     {
       "bot_config": {
         "token": "your-bot-token",
         "server_id": 123456789012345678,
         "cpu_alert_webhook": "https://discord.com/api/webhooks/.../...",
         "icon": "https://cdn.example.com/icon.png",
         "bot_status": "Monitoring host"
       }
     }
     ```

4. **Run**

   ```bash
   python main.py
   ```

> Permissions: terminating processes may require elevated rights on your host. Run accordingly.

---

## Commands

* `/status` – live CPU/RAM + Top 3, updates every 2s for 5 minutes.
* `/topcpu` – Top 10 processes by CPU (normalized 0–100%).
* `/terminate <index>` – terminate item **N** from your latest `/topcpu` (admin‑only by default).

---

## Design Notes

* **Noise control:** CPU watchdog uses a short confirmation (2 consecutive hits) and a **cooldown** to avoid ping storms.
* **Actionable alerts:** includes Top 3 CPU hogs so you don’t need to jump to the host first.
* **Safety rails:** protected PIDs and common system process names are blocked from termination.
* **UX:** slash commands are ephemeral by default to keep channels clean.

---

## Contact

* **Telegram:** @twiddllo
* **GitHub:** [https://github.com/Twiddllo](Twiddllo)

If you like the project, a ⭐ helps


