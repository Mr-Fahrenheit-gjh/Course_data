from __future__ import annotations

import argparse
import json
from pathlib import Path

from sjtu_course_analysis.scheduler import build_timetable, format_result, result_to_dict


DEFAULT_INPUT = Path("input/input.json")
DEFAULT_SQLITE = Path("data/processed/course_reviews_simple.sqlite")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the highest-rated non-conflicting timetable.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--unrated-score", type=float, default=0.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_timetable(
        args.input,
        args.sqlite,
        allow_missing=args.allow_missing,
        unrated_score=args.unrated_score,
    )
    if args.as_json:
        print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()
