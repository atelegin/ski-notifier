"""Main orchestrator for ski notifier."""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List
from zoneinfo import ZoneInfo

from .features import compute_resort_features, compute_discipline_weekly, ResortFeatures, DisciplineWeekly
from .fetch import fetch_all_resorts_weather, FetchResult
from .message import RankedResort, format_message
from .resorts import load_resorts, LoadResult, Resort
from .score import calculate_resort_score
from .telegram import send_message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Season months (Nov-Mar)
SEASON_MONTHS = {11, 12, 1, 2, 3}
TZ = ZoneInfo("Europe/Berlin")

# Exit code thresholds
SUCCESS_THRESHOLD = 0.60  # Exit 0 if >= 60% success
CRITICAL_FAILURE_THRESHOLD = 0.30  # Exit 1 if < 30% success


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


def is_in_season() -> bool:
    """Check if current month is in ski season (Nov-Mar)."""
    now = datetime.now(TZ)
    return now.month in SEASON_MONTHS


def get_tomorrow() -> date:
    """Get tomorrow's date in Europe/Berlin timezone."""
    now = datetime.now(TZ)
    return (now + timedelta(days=1)).date()


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
        help="Run even if not in season (Nov-Mar)",
    )
    args = parser.parse_args()
    
    # Season check
    if not is_in_season() and not args.force:
        print("Not in season (Nov-Mar). Use --force to override.")
        return
    
    tomorrow = get_tomorrow()
    logger.info(f"Fetching weather for {tomorrow}")
    
    # Load resorts
    load_result: LoadResult = load_resorts()
    resorts = load_result.resorts
    costs = load_result.costs
    
    if load_result.n_skipped > 0:
        logger.info(f"Loaded {len(resorts)} resorts ({load_result.n_skipped} skipped: invalid coordinates)")
    else:
        logger.info(f"Loaded {len(resorts)} resorts")
    
    if not resorts:
        logger.error("CRITICAL: No valid resorts loaded")
        sys.exit(1)
    
    # Fetch weather using batch API
    fetch_result: FetchResult = fetch_all_resorts_weather(resorts, forecast_days=7)
    
    logger.info(
        f"Open-Meteo: {fetch_result.n_batches} batches, "
        f"{fetch_result.n_points_success}/{fetch_result.n_points_total} points OK"
    )
    
    if fetch_result.failed_resorts:
        logger.warning(f"Failed resorts: {fetch_result.failed_resorts}")
    
    # Calculate success rate based on resorts with data
    n_resorts_with_data = len(fetch_result.weather)
    n_total_resorts = len(resorts)
    success_rate = n_resorts_with_data / n_total_resorts if n_total_resorts > 0 else 0.0
    
    logger.info(f"Success rate: {success_rate:.1%} ({n_resorts_with_data}/{n_total_resorts} resorts)")
    
    # Calculate scores for each resort with weather data
    ranked_resorts: List[RankedResort] = []
    # Track best score per day per discipline for weekly analysis
    scores_by_day_by_disc: Dict[str, Dict[date, int]] = {"alpine": {}, "xc": {}}
    
    for resort in resorts:
        if resort.id not in fetch_result.weather:
            continue
        
        weather = fetch_result.weather[resort.id]
        
        # Use intersection of low and high keys for safety
        valid_dates = sorted(set(weather.low.keys()) & set(weather.high.keys()))
        
        for d in valid_dates:
            score = calculate_resort_score(weather.low[d], weather.high[d])
            
            # Track best-of-day per discipline (using round for consistency)
            score_int = round(score.score)
            disc_dict = scores_by_day_by_disc[resort.type]
            if d not in disc_dict or score_int > disc_dict[d]:
                disc_dict[d] = score_int
            
            # Store tomorrow's score for ranking
            if d == tomorrow:
                ranked_resorts.append(RankedResort(resort=resort, score=score))
    
    # Sort by score descending
    ranked_resorts.sort(key=lambda r: r.score.score, reverse=True)
    
    # Apply selection logic: TOP-3 + ensure both types represented
    selected_ranked_resorts = select_top_with_coverage(ranked_resorts, n_top=3)
    
    # Compute discipline weekly summaries
    discipline_weekly = compute_discipline_weekly(scores_by_day_by_disc, tomorrow)
    
    # Compute ResortFeatures for each selected resort
    resort_features: Dict[str, ResortFeatures] = {}
    for ranked in selected_ranked_resorts:
        resort = ranked.resort
        if resort.id in fetch_result.weather:
            weather = fetch_result.weather[resort.id]
            # Build daily snowfall list from weather data
            dates_sorted = sorted(weather.high.keys())
            daily_snowfall = [
                weather.high[d].snowfall_cm if d in weather.high else None
                for d in dates_sorted
            ]
            if tomorrow in weather.low and tomorrow in weather.high:
                features = compute_resort_features(
                    weather.low[tomorrow],
                    weather.high[tomorrow],
                    daily_snowfall,
                )
                resort_features[resort.id] = features
    
    # Get list of missing resort names for the message
    missing_resort_names = [
        r.name for r in resorts if r.id in fetch_result.failed_resorts
    ]
    
    # Format message (always attempt, even with low success rate)
    message = format_message(
        tomorrow, 
        selected_ranked_resorts,
        discipline_weekly,
        resort_features,
        costs,
        missing_resort_names=missing_resort_names,
        success_rate=success_rate,
    )
    
    # Send or print message
    telegram_sent = False
    if args.dry_run:
        print("\n" + "=" * 50)
        print("DRY RUN - Message would be:")
        print("=" * 50)
        print(message)
        print("=" * 50)
        telegram_sent = True  # Consider dry-run as success
    else:
        if ranked_resorts:
            try:
                send_message(message)
                telegram_sent = True
                logger.info("Telegram message sent successfully")
            except Exception as e:
                logger.error(f"Failed to send Telegram message: {e}")
        else:
            logger.warning("No resorts with data to report")
    
    # Decide exit code (after Telegram attempt)
    if success_rate >= SUCCESS_THRESHOLD:
        logger.info("Exit 0: Success rate >= 60%")
        sys.exit(0)
    elif success_rate < CRITICAL_FAILURE_THRESHOLD:
        logger.error("Exit 1: Critical failure - success rate < 30%")
        sys.exit(1)
    else:
        # Between 30-60%: exit 0 if Telegram sent, else 1
        if telegram_sent:
            logger.info("Exit 0: Partial success, Telegram sent")
            sys.exit(0)
        else:
            logger.error("Exit 1: Partial failure, could not send Telegram")
            sys.exit(1)


if __name__ == "__main__":
    main()
