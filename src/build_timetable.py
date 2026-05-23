from __future__ import annotations
#  python src/build_timetable.py
import argparse
import json
from pathlib import Path

from sjtu_course_analysis.scheduler import build_timetable, format_result, load_input_config, parse_max_early_classes, result_to_dict


DEFAULT_INPUT = Path("input/input.json")
DEFAULT_SQLITE = Path("data/processed/course_reviews_simple.sqlite")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the highest-rated non-conflicting timetable.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--unrated-score", type=float, default=0.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--t", action="store_true", help="Debug mode: read max_early_classes from input JSON without prompting.")
    return parser.parse_args()


def read_max_early_classes(input_path: Path, debug_mode: bool) -> int | None:
    if debug_mode:
        return parse_max_early_classes(load_input_config(input_path))

    while True:
        value = input("早八课程数量最多允许多少门？直接回车表示不限制：").strip()
        if not value:
            return None
        try:
            limit = int(value)
        except ValueError:
            print("请输入非负整数，或直接回车表示不限制。")
            continue
        if limit < 0:
            print("请输入非负整数，或直接回车表示不限制。")
            continue
        return limit


def main() -> None:
    args = parse_args()
    max_early_classes = read_max_early_classes(args.input, args.t)
    result = build_timetable(
        args.input,
        args.sqlite,
        allow_missing=args.allow_missing,
        unrated_score=args.unrated_score,
        max_early_classes=max_early_classes,
    )
    if args.as_json:
        print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()
