"""Main orchestrator for ski notifier."""

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from .features import compute_resort_features, compute_discipline_weekly, ResortFeatures, DisciplineWeekly
from .fetch import fetch_all_resorts_weather, FetchResult
from .message import RankedResort, format_message, format_resort_weather_line
from .resorts import load_resorts, LoadResult, Resort, Costs
from .score import calculate_resort_score
from .telegram import get_updates, send_message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Season months (Nov-Apr)
SEASON_MONTHS = {11, 12, 1, 2, 3, 4}
TZ = ZoneInfo("Europe/Berlin")

# Exit code thresholds
SUCCESS_THRESHOLD = 0.60  # Exit 0 if >= 60% success
CRITICAL_FAILURE_THRESHOLD = 0.30  # Exit 1 if < 30% success
CLOSE_PRIORITY_MAX_DRIVE_MIN = 95
CLOSE_PRIORITY_MAX_SCORE_GAP = 8.0
HARD_MAX_DRIVE_MIN = 135


@dataclass
class ForecastBundle:
    """Forecast calculation results for one target date."""

    target_date: date
    resorts: List[Resort]
    costs: Costs
    ranked_resorts: List[RankedResort]
    selected_ranked_resorts: List[RankedResort]
    discipline_weekly: Dict[str, DisciplineWeekly]
    resort_features: Dict[str, ResortFeatures]
    missing_resort_names: List[str]
    success_rate: float


def select_top_with_coverage(ranked: List[RankedResort], n_top: int = 3) -> List[RankedResort]:
    """Select top N resorts ensuring both types (alpine/xc) are represented.

    If TOP-N doesn't include a type, adds best missing type as N+1.
    """
    if len(ranked) <= n_top:
        return ranked

    top_n = ranked[:n_top]
    types_in_top = {r.resort.type for r in top_n}
    result = list(top_n)

    for missing in ("alpine", "xc"):
        if missing not in types_in_top:
            candidate = next((r for r in ranked[n_top:] if r.resort.type == missing), None)
            if candidate:
                result.append(candidate)

    return result


def prioritize_close_leader(
    ranked: List[RankedResort],
    max_drive_min: int = CLOSE_PRIORITY_MAX_DRIVE_MIN,
    max_score_gap: float = CLOSE_PRIORITY_MAX_SCORE_GAP,
) -> List[RankedResort]:
    """Move best nearby resort to #1 if it is close enough in score.

    Rule:
    - Find best resort within max_drive_min
    - If its score is within max_score_gap of current #1, promote it to #1
    """
    if len(ranked) < 2:
        return ranked

    leader = ranked[0]
    close_candidate = next(
        (r for r in ranked if r.resort.drive_time_min <= max_drive_min),
        None,
    )
    if close_candidate is None or close_candidate is leader:
        return ranked

    if (leader.score.score - close_candidate.score.score) > max_score_gap:
        return ranked

    reordered = [close_candidate]
    reordered.extend(r for r in ranked if r is not close_candidate)
    return reordered


def is_in_season() -> bool:
    """Check if current month is in ski season (Nov-Apr)."""
    now = datetime.now(TZ)
    return now.month in SEASON_MONTHS


def get_tomorrow() -> date:
    """Get tomorrow's date in Europe/Berlin timezone."""
    now = datetime.now(TZ)
    return (now + timedelta(days=1)).date()


def get_today() -> date:
    """Get today's date in Europe/Berlin timezone."""
    return datetime.now(TZ).date()


def extract_recommended_resort_names(message_text: str) -> List[str]:
    """Extract resort names from a previously sent forecast message."""
    names: List[str] = []
    pattern = re.compile(r"^(?:🎿|⛷️|⛷)\s+(.+?)\s+—\s+")
    for line in message_text.splitlines():
        m = pattern.match(line.strip())
        if m:
            names.append(m.group(1).strip())
    return names


def is_refresh_command(text: str) -> bool:
    """Check if message text is /refresh command."""
    command = text.strip().split()[0].lower() if text.strip() else ""
    return command == "/refresh" or command.startswith("/refresh@")


def build_forecast_bundle(target_date: date) -> ForecastBundle:
    """Build ranking and message inputs for a given target date."""
    logger.info(f"Fetching weather for {target_date}")

    load_result: LoadResult = load_resorts()
    resorts = [r for r in load_result.resorts if r.drive_time_min <= HARD_MAX_DRIVE_MIN]
    costs = load_result.costs
    n_filtered_out = len(load_result.resorts) - len(resorts)

    if load_result.n_skipped > 0:
        logger.info(f"Loaded {len(resorts)} resorts ({load_result.n_skipped} skipped: invalid coordinates)")
    else:
        logger.info(f"Loaded {len(resorts)} resorts")
    if n_filtered_out > 0:
        logger.info(f"Hard-filtered {n_filtered_out} resorts by drive_time_min > {HARD_MAX_DRIVE_MIN}")

    if not resorts:
        logger.error("CRITICAL: No valid resorts loaded")
        raise RuntimeError("No valid resorts loaded")

    fetch_result: FetchResult = fetch_all_resorts_weather(resorts, forecast_days=7)

    logger.info(
        f"Open-Meteo: {fetch_result.n_batches} batches, "
        f"{fetch_result.n_points_success}/{fetch_result.n_points_total} points OK"
    )

    if fetch_result.failed_resorts:
        logger.warning(f"Failed resorts: {fetch_result.failed_resorts}")

    n_resorts_with_data = len(fetch_result.weather)
    n_total_resorts = len(resorts)
    success_rate = n_resorts_with_data / n_total_resorts if n_total_resorts > 0 else 0.0
    logger.info(f"Success rate: {success_rate:.1%} ({n_resorts_with_data}/{n_total_resorts} resorts)")

    ranked_resorts: List[RankedResort] = []
    scores_by_day_by_disc: Dict[str, Dict[date, int]] = {"alpine": {}, "xc": {}}

    for resort in resorts:
        if resort.id not in fetch_result.weather:
            continue

        weather = fetch_result.weather[resort.id]
        valid_dates = sorted(set(weather.low.keys()) & set(weather.high.keys()))

        for d in valid_dates:
            score = calculate_resort_score(
                weather.low[d],
                weather.high[d],
                discipline=resort.type,
                drive_time_min=resort.drive_time_min,
            )

            score_int = round(score.score)
            disc_dict = scores_by_day_by_disc[resort.type]
            if d not in disc_dict or score_int > disc_dict[d]:
                disc_dict[d] = score_int

            if d == target_date:
                ranked_resorts.append(RankedResort(resort=resort, score=score))

    ranked_resorts.sort(key=lambda r: r.score.score, reverse=True)
    ranked_resorts = prioritize_close_leader(ranked_resorts)
    selected_ranked_resorts = select_top_with_coverage(ranked_resorts, n_top=3)

    discipline_weekly = compute_discipline_weekly(scores_by_day_by_disc, target_date)

    resort_features: Dict[str, ResortFeatures] = {}
    for ranked in selected_ranked_resorts:
        resort = ranked.resort
        if resort.id in fetch_result.weather:
            weather = fetch_result.weather[resort.id]
            if target_date in weather.low and target_date in weather.high:
                features = compute_resort_features(
                    weather.low[target_date],
                    weather.high[target_date],
                )
                resort_features[resort.id] = features

    missing_resort_names = [
        r.name for r in resorts if r.id in fetch_result.failed_resorts
    ]

    return ForecastBundle(
        target_date=target_date,
        resorts=resorts,
        costs=costs,
        ranked_resorts=ranked_resorts,
        selected_ranked_resorts=selected_ranked_resorts,
        discipline_weekly=discipline_weekly,
        resort_features=resort_features,
        missing_resort_names=missing_resort_names,
        success_rate=success_rate,
    )


def find_ranked_by_name(bundle: ForecastBundle, name: str) -> Optional[RankedResort]:
    """Find current scored resort by display name."""
    for ranked in bundle.ranked_resorts:
        if ranked.resort.name == name:
            return ranked
    return None


def format_refresh_message(previous_names: List[str], bundle: ForecastBundle) -> str:
    """Build /refresh response message for current-day forecasts."""
    now = datetime.now(TZ)
    lines = [
        f"🔄 Refresh ({now.strftime('%d.%m %H:%M')} Europe/Berlin)",
        "Ранее рекомендованные курорты (из сообщения, на которое ты ответил):",
    ]

    previous_ranked_found: List[RankedResort] = []
    missing_from_current: List[str] = []
    for name in previous_names:
        ranked = find_ranked_by_name(bundle, name)
        if ranked is None:
            missing_from_current.append(name)
            continue
        previous_ranked_found.append(ranked)
        lines.append(format_resort_weather_line(ranked, None))

    if not previous_ranked_found:
        lines.append("• Не удалось найти курорты из прошлого сообщения в текущих данных")

    if missing_from_current:
        lines.append(f"⚠️ Нет данных сейчас: {', '.join(missing_from_current)}")

    current_top = bundle.selected_ranked_resorts
    prev_ids = [r.resort.id for r in previous_ranked_found]
    top_ids = [r.resort.id for r in current_top]
    previous_position = {ranked.resort.id: idx for idx, ranked in enumerate(previous_ranked_found)}

    if prev_ids != top_ids:
        lines.append("")
        lines.append("Новый топ на сейчас:")
        for idx, ranked in enumerate(current_top):
            prev_idx = previous_position.get(ranked.resort.id)
            if prev_idx is None:
                marker = "🆕"
            elif prev_idx == idx:
                marker = "="
            elif prev_idx > idx:
                marker = f"↑{prev_idx - idx}"
            else:
                marker = f"↓{idx - prev_idx}"
            line = format_resort_weather_line(ranked, bundle.resort_features.get(ranked.resort.id))
            lines.append(f"{marker} {line}")
    else:
        lines.append("")
        lines.append("Топ на сейчас не изменился.")

    if bundle.missing_resort_names:
        lines.append("")
        lines.append(f"⚠️ Missing: {', '.join(bundle.missing_resort_names[:5])}")

    return "\n".join(lines)


def acknowledge_updates(updates: List[Dict]) -> None:
    """Acknowledge consumed Telegram updates so they won't be reprocessed."""
    if not updates:
        return
    max_update_id = max(int(update.get("update_id", 0)) for update in updates)
    # Telegram confirms all updates with update_id < offset.
    get_updates(offset=max_update_id + 1, limit=1, timeout=0)


def run_refresh_command_flow(dry_run: bool = False) -> bool:
    """Process incoming /refresh commands and send responses."""
    updates = get_updates(timeout=0, limit=100)
    if not updates:
        logger.info("No incoming Telegram updates")
        return False

    refresh_updates = []
    for update in updates:
        message = update.get("message") or {}
        text = message.get("text", "")
        if isinstance(text, str) and is_refresh_command(text):
            refresh_updates.append(update)

    if not refresh_updates:
        acknowledge_updates(updates)
        logger.info("No /refresh commands in updates")
        return False

    last_update = sorted(refresh_updates, key=lambda u: u.get("update_id", 0))[-1]
    message = last_update.get("message") or {}
    reply = message.get("reply_to_message") or {}
    reply_text = reply.get("text", "")

    if not isinstance(reply_text, str) or not reply_text.strip():
        response = "Для /refresh ответь этой командой именно на последнее сообщение с прогнозом."
        if dry_run:
            print(response)
        else:
            send_message(response)
        acknowledge_updates(updates)
        return True

    previous_names = extract_recommended_resort_names(reply_text)
    if not previous_names:
        response = "Не смог распознать курорты в сообщении-реплае. Ответь /refresh на обычный прогноз с курортами."
        if dry_run:
            print(response)
        else:
            send_message(response)
        acknowledge_updates(updates)
        return True

    bundle = build_forecast_bundle(get_today())
    response = format_refresh_message(previous_names, bundle)

    if dry_run:
        print("\n" + "=" * 50)
        print("DRY RUN - /refresh response would be:")
        print("=" * 50)
        print(response)
        print("=" * 50)
    else:
        send_message(response)

    acknowledge_updates(updates)
    logger.info("Processed /refresh command")
    return True


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Ski Snow Notifier")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print message without sending to Telegram",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if not in season (Nov-Apr)",
    )
    parser.add_argument(
        "--mode",
        choices=["daily", "commands"],
        default="daily",
        help="daily: send regular tomorrow forecast, commands: process Telegram /refresh",
    )
    args = parser.parse_args()

    if not is_in_season() and not args.force:
        print("Not in season (Nov-Apr). Use --force to override.")
        return

    if args.mode == "commands":
        try:
            handled = run_refresh_command_flow(dry_run=args.dry_run)
            if handled:
                sys.exit(0)
            sys.exit(0)
        except Exception as e:
            logger.error(f"Command mode failed: {e}")
            sys.exit(1)

    try:
        bundle = build_forecast_bundle(get_tomorrow())
    except Exception as e:
        logger.error(f"Daily mode failed before send: {e}")
        sys.exit(1)

    message = format_message(
        bundle.target_date,
        bundle.selected_ranked_resorts,
        bundle.discipline_weekly,
        bundle.resort_features,
        bundle.costs,
        missing_resort_names=bundle.missing_resort_names,
        success_rate=bundle.success_rate,
    )

    telegram_sent = False
    if args.dry_run:
        print("\n" + "=" * 50)
        print("DRY RUN - Message would be:")
        print("=" * 50)
        print(message)
        print("=" * 50)
        telegram_sent = True
    else:
        if bundle.ranked_resorts:
            try:
                send_message(message)
                telegram_sent = True
                logger.info("Telegram message sent successfully")
            except Exception as e:
                logger.error(f"Failed to send Telegram message: {e}")
        else:
            logger.warning("No resorts with data to report")

    if bundle.success_rate >= SUCCESS_THRESHOLD:
        logger.info("Exit 0: Success rate >= 60%")
        sys.exit(0)
    if bundle.success_rate < CRITICAL_FAILURE_THRESHOLD:
        logger.error("Exit 1: Critical failure - success rate < 30%")
        sys.exit(1)

    if telegram_sent:
        logger.info("Exit 0: Partial success, Telegram sent")
        sys.exit(0)

    logger.error("Exit 1: Partial failure, could not send Telegram")
    sys.exit(1)


if __name__ == "__main__":
    main()
