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
DEFAULT_TIMETABLE_SETTINGS: dict[str, int | str | None] = {
    "max_early_classes": 1,
    "search_mode": "approx",
    "beam_width": 1000,
    "per_course_limit": 40,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the highest-rated non-conflicting timetable.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--unrated-score", type=float, default=0.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--approx", action="store_true", help="Use approximate beam search instead of exact DFS.")
    parser.add_argument("--beam-width", type=int, default=None)
    parser.add_argument("--per-course-limit", type=int, default=None)
    parser.add_argument("--t", action="store_true", help="Debug mode: read max_early_classes from input JSON without prompting.")
    return parser.parse_args()


def read_timetable_settings(input_path: Path, debug_mode: bool) -> dict[str, int | str | None]:
    input_config = load_input_config(input_path)
    settings = parse_timetable_settings(input_config)
    if debug_mode:
        return settings

    changed = False
    while True:
        print_timetable_settings(settings)
        value = input(c("请输入要修改的序号，直接回车开始排课：", "cyan", True)).strip()
        if not value:
            if changed:
                save_timetable_settings(input_path, input_config, settings)
                print(c("设置已保存到 input.json。", "green", True))
            return settings
        if value == "1":
            settings["search_mode"] = read_search_mode(str(settings["search_mode"]))
            changed = True
        elif value == "2":
            current_early = settings["max_early_classes"] if settings["max_early_classes"] is not None else "不限制"
            settings["max_early_classes"] = read_optional_nonnegative_int(
                f"早八课程数量最多允许多少门？直接回车使用当前值 {current_early}，输入 none 表示不限制：",
                default=settings["max_early_classes"],
                allow_none_text=True,
            )
            changed = True
        elif value == "3":
            settings["beam_width"] = read_optional_nonnegative_int(
                f"beam_width 设置为多少？直接回车使用当前值 {settings['beam_width']}：",
                default=int(settings["beam_width"]),
            )
            changed = True
        elif value == "4":
            settings["per_course_limit"] = read_optional_nonnegative_int(
                f"per_course_limit 设置为多少？直接回车使用当前值 {settings['per_course_limit']}：",
                default=int(settings["per_course_limit"]),
            )
            changed = True
        elif value == "5":
            settings = dict(DEFAULT_TIMETABLE_SETTINGS)
            changed = True
            print(c("已恢复默认设置。", "green", True))
        else:
            print(c("请输入 1-5，或直接回车开始排课。", "yellow", True))


def parse_timetable_settings(input_config: dict) -> dict[str, int | str | None]:
    search_mode = input_config.get("search_mode", "exact")
    if search_mode not in {"exact", "approx"}:
        raise ValueError("search_mode must be 'exact' or 'approx'.")
    return {
        "max_early_classes": parse_max_early_classes(input_config),
        "search_mode": search_mode,
        "beam_width": int(input_config.get("beam_width", 500)),
        "per_course_limit": int(input_config.get("per_course_limit", 30)),
    }


def print_timetable_settings(settings: dict[str, int | str | None]) -> None:
    print(c("当前排课设置：", "cyan", True))
    print(f"  1. 搜索模式: {settings['search_mode']} ({'近似 beam search' if settings['search_mode'] == 'approx' else '精确 DFS'})")
    print(f"  2. 早八上限: {settings['max_early_classes'] if settings['max_early_classes'] is not None else '不限制'}")
    print(f"  3. beam_width: {settings['beam_width']}")
    print(f"  4. per_course_limit: {settings['per_course_limit']}")
    print("  5. 恢复默认设置")


def save_timetable_settings(input_path: Path, input_config: dict, settings: dict[str, int | str | None]) -> None:
    input_config.update(settings)
    input_path.write_text(json.dumps(input_config, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def read_search_mode(current: str) -> str:
    while True:
        value = input(c(f"搜索模式 exact/approx？直接回车使用当前值 {current}：", "cyan", True)).strip().lower()
        if not value:
            value = current
        if value in {"exact", "approx"}:
            return value
        print(c("请输入 exact 或 approx。", "yellow", True))


def read_optional_nonnegative_int(prompt: str, *, default: int | None = None, allow_none_text: bool = False) -> int | None:
    while True:
        value = input(c(prompt, "cyan", True)).strip().lower()
        if not value:
            return default
        if allow_none_text and value in {"none", "no", "不限", "不限制"}:
            return None
        try:
            result = int(value)
        except ValueError:
            print(c("请输入非负整数。", "yellow", True))
            continue
        if result < 0:
            print(c("请输入非负整数。", "yellow", True))
            continue
        return result


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

    show_result = False
    while True:
        if show_result:
            print("")
            print(format_result(result, color=True))
        show_result = True
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
    settings = read_timetable_settings(args.input, args.t or args.as_json)
    search_mode = "approx" if args.approx else str(settings["search_mode"])
    result = build_timetable(
        args.input,
        args.sqlite,
        allow_missing=args.allow_missing,
        unrated_score=args.unrated_score,
        max_early_classes=settings["max_early_classes"],
        progress_callback=make_progress_bar(not args.as_json),
        search_mode=search_mode,
        beam_width=args.beam_width if args.beam_width is not None else int(settings["beam_width"]),
        per_course_limit=args.per_course_limit if args.per_course_limit is not None else int(settings["per_course_limit"]),
    )
    if args.as_json:
        print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
    else:
        print(format_result(result, color=True))
        review_loop(args.sqlite, result)


if __name__ == "__main__":
    main()
