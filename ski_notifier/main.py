"""Main orchestrator for ski notifier."""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List
from zoneinfo import ZoneInfo

from .fetch import fetch_all_resorts_weather, FetchResult
from .message import RankedResort, format_message
from .resorts import load_resorts, LoadResult
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
    all_scores_by_day: Dict[date, List[float]] = {}
    
    for resort in resorts:
        if resort.id not in fetch_result.weather:
            continue
        
        weather = fetch_result.weather[resort.id]
        
        # Calculate scores for all days
        for d in weather.low.keys():
            if d not in weather.high:
                continue
            
            score = calculate_resort_score(weather.low[d], weather.high[d])
            
            # Track for best-day-of-week calculation
            if d not in all_scores_by_day:
                all_scores_by_day[d] = []
            all_scores_by_day[d].append(score.score)
            
            # Store tomorrow's score for ranking
            if d == tomorrow:
                ranked_resorts.append(RankedResort(resort=resort, score=score))
    
    # Sort by score descending
    ranked_resorts.sort(key=lambda r: r.score.score, reverse=True)
    
    # Build best scores by day (for "best day of week" logic)
    best_scores_by_day = {d: max(scores) for d, scores in all_scores_by_day.items()}
    
    # Get list of missing resort names for the message
    missing_resort_names = [
        r.name for r in resorts if r.id in fetch_result.failed_resorts
    ]
    
    # Format message (always attempt, even with low success rate)
    message = format_message(
        tomorrow, 
        ranked_resorts, 
        best_scores_by_day, 
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
