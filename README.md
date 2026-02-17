# Ski Snow Notifier 🎿

Daily Telegram notifier that recommends where to ski tomorrow based on weather and snow conditions.

## Features

- **7-day weather forecast** from Open-Meteo (free API)
- **Smart scoring** based on snow depth, fresh snow, temperature, wind gusts, precipitation
- **Best day of the week** detection
- **8 resorts** in CH/AT/DE (alpine + XC)
- **Daily notifications** at 17:00 Europe/Berlin (Nov–Mar only)

## Setup

### 1. Create Telegram Bot

1. Open Telegram and find [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy the **bot token** (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Get Your Chat ID

**Option A:** Use [@userinfobot](https://t.me/userinfobot)
- Open the bot and send any message
- It will reply with your user ID

**Option B:** Use getUpdates API
1. Send `/start` to your new bot
2. Open: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `"chat":{"id": 123456789}` — that's your chat ID

### 3. Add GitHub Secrets

In your GitHub repo, go to **Settings → Secrets and variables → Actions** and add:

| Secret Name | Value |
|-------------|-------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your chat ID (number) |

### 4. Enable GitHub Actions

GitHub Actions should be enabled by default. The workflow will run:
- **Daily at 17:00 CET** (16:00 UTC)
- **Manually** via "Run workflow" button

### 5. Update Ski Pass Prices (Annually)

Edit `ski_notifier/resorts.yaml` and update `ski_pass_day_adult_eur` for each resort.

## Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Dry run (prints message without sending)
python -m ski_notifier.main --dry-run --force

# With Telegram (set env vars first)
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
python -m ski_notifier.main --force
```

## Scoring Formula

Each point (low/high) is scored 0–100:

```
base = 50
+ clamp(snow_depth_cm, 0..60) × 0.6
+ clamp(snow24_to_9_cm, 0..30) × 0.4 # fresh snow bonus (24h ending at 09:00)
- max(0, wind_gust - 35) × 0.8       # gusts over 35 km/h
- max(0, precip - 8) × 1.0           # heavy rain/wet snow
- min(6, max(0, wind_gust-35) × max(0, precip-8) × 0.15)
                                    # extra penalty for windy + wet combo
- max(0, temp - 4) × 3.0             # warm = worse snow
- max(0, -temp - 18) × 1.0           # extreme cold
```

Resort score = 0.45 × low + 0.55 × high

Distance bonus (closer resorts get more points):
- +10 for ~60 min drive
- +0 for 120+ min drive
- linear in between

### Notes

- **Wind threshold (35 km/h)** is for **gusts**, not average wind speed
- **Costs are NOT used in scoring** — only displayed in the message
- **Confidence** reflects snow data availability (1.0 = full, 0.7 = partial, 0.4 = none)

## Costs (for reference only)

| Item | Price |
|------|-------|
| Ferry Konstanz–Meersburg RT (PKW ≤4m) | €24.20 |
| Austrian 1-day vignette | €9.60 |

## File Structure

```
ski-snow-notifier/
├── .github/workflows/ski.yml   # GitHub Actions
├── ski_notifier/
│   ├── __init__.py
│   ├── resorts.yaml            # Resort data (edit prices here)
│   ├── resorts.py              # YAML loader
│   ├── fetch.py                # Open-Meteo client
│   ├── score.py                # Scoring engine
│   ├── message.py              # Message formatter
│   ├── telegram.py             # Telegram sender
│   └── main.py                 # Orchestrator
│   └── xc_registry.yaml        # Generated XC registry (core + extended)
│   └── alpine_registry.yaml    # Generated Alpine registry (core + extended)
├── scripts/
│   └── build_xc_registry.py    # Builds xc_registry.yaml from resorts.yaml + OSM
│   └── promote_extended_xc.py  # Promotes extended XC to resorts.yaml
│   └── build_alpine_registry.py
│   └── promote_extended_alpine.py
├── requirements.txt
└── README.md
```

## XC Registry (Core + Extended)

You now have two XC layers:

- `core`: manually curated XC resorts from `ski_notifier/resorts.yaml` (`type: xc`)
- `extended`: auto-discovered OSM nordic candidates around Konstanz (rough ETA filter)

Regenerate registry:

```bash
python3 scripts/build_xc_registry.py
```

Output:

- `ski_notifier/xc_registry.yaml`

Promote extended XC into `resorts.yaml`:

```bash
python3 scripts/promote_extended_xc.py
```

Build Alpine registry:

```bash
python3 scripts/build_alpine_registry.py
```

Output:

- `ski_notifier/alpine_registry.yaml`

Promote extended Alpine into `resorts.yaml`:

```bash
python3 scripts/promote_extended_alpine.py
```

## License

MIT
