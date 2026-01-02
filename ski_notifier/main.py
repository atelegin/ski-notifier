"""Main orchestrator for ski notifier."""

import argparse
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List
from zoneinfo import ZoneInfo

from .fetch import fetch_resort_weather
from .message import RankedResort, format_message
from .resorts import load_resorts
from .score import calculate_resort_score
from .telegram import send_message

# Season months (Nov-Mar)
SEASON_MONTHS = {11, 12, 1, 2, 3}
TZ = ZoneInfo("Europe/Berlin")


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
    print(f"Fetching weather for {tomorrow}...")
    
    # Load resorts
    resorts, costs = load_resorts()
    print(f"Loaded {len(resorts)} resorts")
    
    # Fetch weather and calculate scores for each resort
    ranked_resorts: List[RankedResort] = []
    all_scores_by_day: Dict[date, List[float]] = {}
    
    for resort in resorts:
        try:
            print(f"  Fetching {resort.name}...")
            weather = fetch_resort_weather(resort.point_low, resort.point_high, forecast_days=7)
            
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
                    
        except RuntimeError as e:
            print(f"  ERROR fetching {resort.name}: {e}", file=sys.stderr)
            # Continue with other resorts, but log the error
            continue
    
    if not ranked_resorts:
        print("ERROR: No resort data available", file=sys.stderr)
        sys.exit(1)
    
    # Sort by score descending
    ranked_resorts.sort(key=lambda r: r.score.score, reverse=True)
    
    # Build best scores by day (for "best day of week" logic)
    best_scores_by_day = {d: max(scores) for d, scores in all_scores_by_day.items()}
    
    # Format message
    message = format_message(tomorrow, ranked_resorts, best_scores_by_day, costs)
    
    if args.dry_run:
        print("\n" + "=" * 50)
        print("DRY RUN - Message would be:")
        print("=" * 50)
        print(message)
        print("=" * 50)
    else:
        send_message(message)
        print("Done!")


if __name__ == "__main__":
    main()
