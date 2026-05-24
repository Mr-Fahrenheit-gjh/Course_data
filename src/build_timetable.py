from __future__ import annotations
#  python src/build_timetable.py
import argparse
import json
import sys
from pathlib import Path

from sjtu_course_analysis.presentation import c, format_result, format_reviews
from sjtu_course_analysis.scheduler import (
    build_timetable,
    fetch_reviews,
    load_input_config,
    parse_max_early_classes,
    result_to_dict,
)


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
        value = input(c("早八课程数量最多允许多少门？直接回车表示不限制：", "cyan", True)).strip()
        if not value:
            return None
        try:
            limit = int(value)
        except ValueError:
            print(c("请输入非负整数，或直接回车表示不限制。", "yellow", True))
            continue
        if limit < 0:
            print(c("请输入非负整数，或直接回车表示不限制。", "yellow", True))
            continue
        return limit


def make_progress_bar(enabled: bool):
    if not enabled or not sys.stderr.isatty():
        return None

    width = 30

    def update(current: int, total: int, course_code: str) -> None:
        ratio = current / total if total else 1.0
        filled = min(width, int(width * ratio))
        bar = "#" * filled + "-" * (width - filled)
        end = "\n" if current >= total else ""
        print(f"\r排课进度 [{bar}] {ratio:6.2%} ({current}/{total}) 当前: {course_code}", end=end, file=sys.stderr, flush=True)

    return update


def review_loop(sqlite_path: Path, result) -> None:
    if not result.selected:
        return

    while True:
        try:
            value = input(c("请输入上方选课结果中的序号查看评论，或直接回车退出：", "cyan", True)).strip()
        except EOFError:
            return
        if not value:
            return
        try:
            index = int(value)
        except ValueError:
            print(c("请输入有效序号，或直接回车退出。", "yellow", True))
            continue
        if index < 1 or index > len(result.selected):
            print(c("序号超出范围。", "yellow", True))
            continue

        offering = result.selected[index - 1]
        page = 1
        while True:
            reviews = fetch_reviews(sqlite_path, offering, limit=10, offset=(page - 1) * 10)
            print("")
            print(format_reviews(reviews, page=page, page_size=10, color=True))
            if not reviews:
                break
            try:
                action = input(c("输入 n 查看下一页，输入其他内容返回序号输入，Ctrl+C 退出：", "cyan", True)).strip().lower()
            except EOFError:
                return
            if action not in {"n", "next", "下一页"}:
                break
            page += 1


def main() -> None:
    args = parse_args()
    max_early_classes = read_max_early_classes(args.input, args.t)
    result = build_timetable(
        args.input,
        args.sqlite,
        allow_missing=args.allow_missing,
        unrated_score=args.unrated_score,
        max_early_classes=max_early_classes,
        progress_callback=make_progress_bar(not args.as_json),
    )
    if args.as_json:
        print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
    else:
        print(format_result(result, color=True))
        review_loop(args.sqlite, result)


if __name__ == "__main__":
    main()
