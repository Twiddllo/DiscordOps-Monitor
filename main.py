
import os
import json
import time
import asyncio
from collections import deque
from datetime import datetime

import psutil
import httpx
import discord
from discord import app_commands

# --------------------------
# Config (env first, then config.json if present)
# --------------------------

def _load_config():
    cfg = {}
    path = "config.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                cfg = raw.get("bot_config", {})
        except Exception:
            pass

    def get(name, default=""):
        return os.getenv(name, cfg.get(name.lower(), default))

    token = os.getenv("DISCORD_TOKEN") or cfg.get("token", "")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN (or bot_config.token in config.json)")

    guild_id = os.getenv("GUILD_ID") or cfg.get("server_id", 0)
    try:
        guild_id = int(guild_id)
    except Exception:
        guild_id = 0

    return {
        "token": token,
        "guild_id": guild_id,
        "icon": os.getenv("ICON_URL", cfg.get("icon", "")),
        "status": os.getenv("BOT_STATUS", cfg.get("bot_status", "Monitoring host")),
        "cpu_alert_webhook": os.getenv("CPU_ALERT_WEBHOOK", cfg.get("cpu_alert_webhook", "")),
    }

CFG = _load_config()

EMOJIS = {
    "info": "<a:info:1394700134788628615>",
    "success": "<a:success:1394351620430757918>",
    "warning": "<a:warning:1394701290000355388>",
    "error": "<a:error:1394702158414352495>",
    "live": "<a:live:1394700411889389752>",
    "queue": "<a:queue:1394699076032790649>",
}

# --------------------------
# Small helpers
# --------------------------
BOT_START = time.time()

def _uptime() -> str:
    s = int(time.time() - BOT_START)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}d {h}h {m}m {s}s"

def _bar(pct: float, length: int = 20) -> str:
    filled = max(0, min(length, int(round(length * pct / 100))))
    return "▰" * filled + "▱" * (length - filled)

async def snapshot_top_processes(n: int = 10, sample_seconds: float = 1.0):
    """
    Returns a list of dicts: [{'pid': 1234, 'name': 'chrome.exe', 'cpu': 12.3}, ...]
    'cpu' is normalized to 0..100 total CPU (not per-core).
    """
    cpu_count = psutil.cpu_count(logical=True) or 1
    procs = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(None)  # prime
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    await asyncio.sleep(sample_seconds)

    rows = []
    for p in procs:
        try:
            raw = p.cpu_percent(None)  # may be up to 100 * cpu_count
            rows.append({
                "pid": p.pid,
                "name": (p.info.get("name") or f"pid-{p.pid}")[:64],
                "cpu": max(0.0, raw / cpu_count),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    rows.sort(key=lambda r: r["cpu"], reverse=True)
    return rows[:n]

def format_proc_line(i: int, row: dict) -> str:
    pct = f"{row['cpu']:.1f}%".rjust(6)
    name = (row["name"] or "unknown")[:32]
    return f"`{i:>2}.` **{name}**  {pct}  • PID `{row['pid']}`"

# --------------------------
# CPU Alert Watchdog
# --------------------------
class CPUWatchdog:
    def __init__(self, webhook: str, threshold=90.0, cooldown=300):
        self.webhook = webhook
        self.threshold = float(threshold)
        self.cooldown = int(cooldown)
        self._last_alert_ts = 0.0
        self._over_counter = 0

    async def _send_webhook_alert(self, total_pct: float, top3: list):
        if not self.webhook:
            return
        lines = [format_proc_line(i + 1, row) for i, row in enumerate(top3)]
        desc = (
            f"{EMOJIS['warning']} **High CPU detected:** `{total_pct:.1f}%`\n\n"
            f"**Top 3 processes:**\n" + "\n".join(lines) + "\n\n"
            f"Use `/topcpu` to see top 10 and `/terminate <index>` to kill one."
        )
        embed = {
            "title": f"{EMOJIS['warning']} Host CPU Alert",
            "description": desc,
            "color": 0xE67E22,
            "footer": {"text": f"Host Guardian • {datetime.utcnow().isoformat(timespec='seconds')}Z"},
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(self.webhook, json={"embeds": [embed]})
        except Exception:
            # Alert failure isn't fatal to the monitor
            pass

    async def run(self):
        while True:
            total = psutil.cpu_percent(interval=1.0)
            if total >= self.threshold:
                self._over_counter += 1
                if self._over_counter >= 2 and (time.time() - self._last_alert_ts) > self.cooldown:
                    top3 = await snapshot_top_processes(3)
                    await self._send_webhook_alert(total, top3)
                    self._last_alert_ts = time.time()
            else:
                self._over_counter = 0
            await asyncio.sleep(4.0)  # ~5s cadence incl. the 1s psutil sample

# --------------------------
# Termination safeguards
# --------------------------
SYSTEM_NAMES = {"System Idle Process", "System", "Registry", "MemCompression"}
PROTECTED_PIDS = {0, 4}  # Windows critical PIDs; adjust for your OS

def safe_terminate_pid(pid: int, timeout: float = 3.0):
    """Attempt to terminate PID safely. Returns (ok: bool, message: str)."""
    try:
        if pid in PROTECTED_PIDS:
            return False, "Refusing to terminate a protected system process."
        p = psutil.Process(pid)
        name = p.name()
        if name in SYSTEM_NAMES:
            return False, f"Refusing to terminate critical process: {name}."
        p.terminate()
        try:
            p.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            p.kill()
        return True, f"Terminated **{name}** (PID {pid})."
    except psutil.NoSuchProcess:
        return False, "Process no longer exists."
    except psutil.AccessDenied:
        return False, "Access denied. Run the bot with sufficient privileges."
    except Exception as e:
        return False, f"Unexpected error: {e!r}"

# --------------------------
# Discord Bot
# --------------------------
CPU_HISTORY = deque(maxlen=150)  # 5 minutes @ 2s resolution
CPU_HISTORY_LOCK = asyncio.Lock()

class Bot:
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = False  # not needed for slash-only
        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)
        self._last_topcpu_by_user = {}  # user_id -> {'at': ts, 'rows': list[dict]}
        self.watchdog = CPUWatchdog(
            webhook=CFG["cpu_alert_webhook"],
            threshold=90.0,
            cooldown=300,
        )

        self.client.event(self.on_ready)
        self._register_commands()

    async def on_ready(self):
        try:
            if CFG["guild_id"]:
                await self.tree.sync(guild=discord.Object(id=CFG["guild_id"]))
            else:
                await self.tree.sync()
        except Exception as e:
            print(f"[sync] {e}")

        await self.client.change_presence(activity=discord.Game(name=CFG["status"]))
        asyncio.create_task(self.watchdog.run())
        asyncio.create_task(self._cpu_history_collector())
        print(f"Logged in as {self.client.user} • ready")

    def _register_commands(self):
        # ---- /status ----
        @self.tree.command(
            name="status",
            description="Live host status for 5 minutes.",
            guild=discord.Object(id=CFG["guild_id"]) if CFG["guild_id"] else None,
        )
        async def status(interaction: discord.Interaction):
            await interaction.response.send_message(
                embed=self._build_status_embed(),
                ephemeral=True
            )
            msg = await interaction.original_response()
            for _ in range(150):  # 2s * 150 = 5 minutes
                await asyncio.sleep(2.0)
                try:
                    await msg.edit(embed=self._build_status_embed())
                except discord.HTTPException:
                    break

        # ---- /topcpu ----
        @self.tree.command(
            name="topcpu",
            description="Show the top 10 CPU-hungry processes.",
            guild=discord.Object(id=CFG["guild_id"]) if CFG["guild_id"] else None,
        )
        async def topcpu(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            rows = await snapshot_top_processes(10)
            self._last_topcpu_by_user[interaction.user.id] = {"at": time.time(), "rows": rows}

            total = psutil.cpu_percent(interval=None)
            lines = [format_proc_line(i + 1, r) for i, r in enumerate(rows)]
            desc = f"**Total CPU:** `{total:.1f}%`\n\n" + "\n".join(lines) + \
                   "\n\nUse `/terminate <index>` to end a process from this list."
            embed = discord.Embed(
                title=f"{EMOJIS['info']} Top CPU Processes",
                description=desc,
                color=discord.Color.yellow()
            )
            if CFG["icon"]:
                embed.set_thumbnail(url=CFG["icon"])
            embed.set_footer(text="Host Guardian")
            await interaction.followup.send(embed=embed, ephemeral=True)

        # ---- /terminate ----
        @self.tree.command(
            name="terminate",
            description="Terminate a process by index from your latest /topcpu.",
            guild=discord.Object(id=CFG["guild_id"]) if CFG["guild_id"] else None,
        )
        @app_commands.default_permissions(administrator=True)
        @app_commands.describe(index="Index from /topcpu (1..10)")
        async def terminate(interaction: discord.Interaction, index: app_commands.Range[int, 1, 10]):
            await interaction.response.defer(ephemeral=True, thinking=True)

            cache = self._last_topcpu_by_user.get(interaction.user.id)
            if not cache or (time.time() - cache["at"] > 600):
                await interaction.followup.send(
                    f"{EMOJIS['warning']} No recent `/topcpu` list found (or it expired). Run `/topcpu` again.",
                    ephemeral=True
                )
                return

            rows = cache["rows"]
            if index > len(rows):
                await interaction.followup.send(
                    f"{EMOJIS['error']} Index out of range. You have only {len(rows)} items.",
                    ephemeral=True
                )
                return

            target = rows[index - 1]
            ok, msg = await asyncio.to_thread(safe_terminate_pid, target["pid"])
            embed = discord.Embed(
                title=f"{EMOJIS['success'] if ok else EMOJIS['error']} Terminate Result",
                description=msg,
                color=discord.Color.green() if ok else discord.Color.red()
            )
            embed.set_footer(text="Host Guardian")
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _cpu_history_collector(self):
        while True:
            value = psutil.cpu_percent(interval=None)
            async with CPU_HISTORY_LOCK:
                CPU_HISTORY.append(value)
            await asyncio.sleep(2.0)

    def _build_status_embed(self) -> discord.Embed:
        cpu_now = psutil.cpu_percent(interval=None)
        ram_now = psutil.virtual_memory().percent

        # quick pass for top3 without slowing the UI (uses last deltas if any)
        try:
            cpu_count = psutil.cpu_count(logical=True) or 1
            rows = []
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    v = p.cpu_percent(None) / cpu_count
                    rows.append({"pid": p.pid, "name": (p.info.get("name") or "")[:64], "cpu": max(0.0, v)})
                except Exception:
                    continue
            rows.sort(key=lambda r: r["cpu"], reverse=True)
            top3 = rows[:3]
        except Exception:
            top3 = []

        lines = [format_proc_line(i + 1, r) for i, r in enumerate(top3)] or ["_sampling…_"]

        with_history = list(CPU_HISTORY)
        max_cpu = max(with_history) if with_history else cpu_now
        avg_cpu = (sum(with_history) / len(with_history)) if with_history else cpu_now

        desc = (
            f"{EMOJIS['info']} **Uptime:** `{_uptime()}`\n"
            f"{EMOJIS['queue']} **CPU:** `{cpu_now:.1f}%`  [{_bar(cpu_now)}]\n"
            f"{EMOJIS['queue']} **RAM:** `{ram_now:.1f}%`\n"
            f"**Top 3 (share of total CPU):**\n" + "\n".join(lines) + "\n\n"
            f"**History (5m)** — Max: `{max_cpu:.1f}%`, Avg: `{avg_cpu:.1f}%`\n"
            f"_Updates every 2s for 5 minutes._"
        )

        embed = discord.Embed(
            title=f"{EMOJIS['live']} Host Status",
            description=desc,
            color=discord.Color.blurple()
        )
        if CFG["icon"]:
            embed.set_thumbnail(url=CFG["icon"])
        embed.set_footer(text="Host Guardian")
        return embed

    def run(self):
        self.client.run(CFG["token"])

if __name__ == "__main__":
    Bot().run()