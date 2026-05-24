from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, order=True)
class Slot:
    week: int
    day: int
    period: int


@dataclass(frozen=True)
class Offering:
    course_code: str
    course_name: str
    credits: float
    teacher: str
    teaching_class: str
    schedule_text: str
    schedule_code: str
    avg_rating: float | None
    review_count: int | None
    slots: frozenset[Slot]
    score: float
    has_early_class: bool


@dataclass(frozen=True)
class SearchStats:
    raw_candidate_count: int
    compressed_candidate_count: int
    compressed_counts: dict[str, int]
    visited_nodes: int


@dataclass(frozen=True)
class Review:
    course_code: str
    course_name: str
    course_teacher: str
    rating: float | None
    score: str | None
    semester_name: str | None
    comment: str | None
    modified_at: str | None


@dataclass(frozen=True)
class TimetableResult:
    status: str
    requested_courses: list[str]
    compulsory_courses: list[str]
    optional_courses: list[str]
    selected: list[Offering]
    selected_optional_courses: list[str]
    skipped_optional_courses: list[str]
    missing_courses: list[str]
    missing_compulsory_courses: list[str]
    missing_optional_courses: list[str]
    total_score: float | None
    average_score: float | None
    weighted_score_sum: float | None
    total_credits: float | None
    weighted_average_score: float | None
    early_class_count: int
    max_early_classes: int | None
    stats: SearchStats
    warnings: list[str] = field(default_factory=list)


class ScheduleParseError(ValueError):
    pass


def load_input_config(input_path: Path) -> dict[str, Any]:
    return json.loads(input_path.read_text(encoding="utf-8"))


def load_requested_courses(input_path: Path) -> list[str]:
    compulsory_courses, optional_courses = parse_course_groups(load_input_config(input_path))
    return compulsory_courses + optional_courses


def parse_requested_courses(data: dict[str, Any]) -> list[str]:
    compulsory_courses, optional_courses = parse_course_groups(data)
    return compulsory_courses + optional_courses


def parse_course_groups(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    compulsory_courses = parse_course_list(data.get("compulsory"), "compulsory", required=True)
    optional_courses = parse_course_list(data.get("optional", []), "optional", required=False)
    duplicate_compulsory = duplicate_courses(compulsory_courses)
    duplicate_optional = duplicate_courses(optional_courses)
    overlap = sorted(set(compulsory_courses) & set(optional_courses))
    if duplicate_compulsory:
        raise ValueError(f"compulsory contains duplicate courses: {', '.join(duplicate_compulsory)}")
    if duplicate_optional:
        raise ValueError(f"optional contains duplicate courses: {', '.join(duplicate_optional)}")
    if overlap:
        raise ValueError(f"courses cannot be both compulsory and optional: {', '.join(overlap)}")
    return compulsory_courses, optional_courses


def parse_course_list(value: object, field_name: str, *, required: bool) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(isinstance(course, str) for course in value):
        raise ValueError(f"input JSON field '{field_name}' must be a string list.")
    return value


def duplicate_courses(courses: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for course in courses:
        if course in seen and course not in duplicates:
            duplicates.append(course)
        seen.add(course)
    return duplicates


def parse_max_early_classes(data: dict[str, Any]) -> int | None:
    value = data.get("max_early_classes")
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        raise ValueError("max_early_classes must be a non-negative integer.")
    return value


def parse_schedule_code(schedule_code: str) -> frozenset[Slot]:
    if not schedule_code:
        raise ScheduleParseError("empty schedule_code")
    if "RAW:" in schedule_code:
        raise ScheduleParseError(f"unparsed schedule_code: {schedule_code}")

    slots: set[Slot] = set()
    for item in filter(None, (part.strip() for part in schedule_code.split(";"))):
        match = re.fullmatch(r"D(\d+):(.*):(.*)", item)
        if not match:
            raise ScheduleParseError(f"invalid schedule component: {item}")
        day = int(match.group(1))
        periods = parse_number_expression(match.group(2), "P")
        weeks = parse_week_expression(match.group(3))
        for week in weeks:
            for period in periods:
                slots.add(Slot(week=week, day=day, period=period))

    if not slots:
        raise ScheduleParseError(f"schedule_code has no concrete slots: {schedule_code}")
    return frozenset(slots)


def parse_number_expression(text: str, prefix: str) -> set[int]:
    values: set[int] = set()
    cleaned = text.replace("，", "+").replace(",", "+")
    for part in filter(None, (item.strip() for item in cleaned.split("+"))):
        values.update(expand_number_range(part, prefix))
    if not values:
        raise ScheduleParseError(f"empty {prefix} expression: {text}")
    return values


def parse_week_expression(text: str) -> set[int]:
    parity: int | None = None
    if "单" in text:
        parity = 1
    elif "双" in text:
        parity = 0

    cleaned = re.sub(r"[（(][^）)]*[）)]", "", text)
    cleaned = cleaned.replace("周", "")
    values = parse_number_expression(cleaned, "W")
    if parity is not None:
        values = {week for week in values if week % 2 == parity}
    if not values:
        raise ScheduleParseError(f"empty week expression after parity filter: {text}")
    return values


def expand_number_range(text: str, prefix: str) -> set[int]:
    cleaned = text.strip()
    if cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix) :]
    cleaned = cleaned.strip()
    if not cleaned:
        raise ScheduleParseError(f"empty range part: {text}")

    if "-" in cleaned:
        start_text, end_text = cleaned.split("-", 1)
        start = parse_int_token(start_text)
        end = parse_int_token(end_text)
        if end < start:
            raise ScheduleParseError(f"invalid descending range: {text}")
        return set(range(start, end + 1))
    return {parse_int_token(cleaned)}


def parse_int_token(text: str) -> int:
    match = re.search(r"\d+", text)
    if not match:
        raise ScheduleParseError(f"expected number in: {text}")
    return int(match.group(0))


def load_offerings(sqlite_path: Path, course_codes: list[str], unrated_score: float = 0.0) -> tuple[dict[str, list[Offering]], list[str]]:
    by_course = {course_code: [] for course_code in course_codes}
    warnings: list[str] = []
    if not course_codes:
        return by_course, warnings

    placeholders = ",".join("?" for _ in course_codes)
    query = f"""
        SELECT
            o.course_code,
            o.course_name,
            o.credits,
            o.teacher,
            o.teaching_class,
            o.schedule_text,
            o.schedule_code,
            r.avg_rating,
            r.review_count
        FROM course_plus_offerings AS o
        LEFT JOIN course_teacher_rating_summary AS r
          ON r.course_code = o.course_code
         AND r.course_teacher = o.teacher
        WHERE o.course_code IN ({placeholders})
        ORDER BY o.course_code, o.teaching_class
    """

    with sqlite3.connect(sqlite_path) as connection:
        rows = connection.execute(query, course_codes).fetchall()

    for row in rows:
        course_code, course_name, credits, teacher, teaching_class, schedule_text, schedule_code, avg_rating, review_count = row
        if credits is None or credits <= 0:
            warnings.append(f"Skipped {course_code} {teaching_class}: missing or invalid credits")
            continue
        try:
            slots = parse_schedule_code(schedule_code or "")
        except ScheduleParseError as error:
            warnings.append(f"Skipped {course_code} {teaching_class}: {error}")
            continue

        score = float(avg_rating) if avg_rating is not None else unrated_score
        by_course[course_code].append(
            Offering(
                course_code=course_code,
                course_name=course_name,
                credits=float(credits),
                teacher=teacher,
                teaching_class=teaching_class,
                schedule_text=schedule_text,
                schedule_code=schedule_code,
                avg_rating=avg_rating,
                review_count=review_count,
                slots=slots,
                score=score,
                has_early_class=has_early_class(slots),
            )
        )

    return by_course, warnings


def compress_offerings(by_course: dict[str, list[Offering]]) -> dict[str, list[Offering]]:
    compressed: dict[str, list[Offering]] = {}
    for course_code, offerings in by_course.items():
        best_by_slots: dict[tuple[frozenset[Slot], float], Offering] = {}
        for offering in offerings:
            key = (offering.slots, offering.credits)
            current = best_by_slots.get(key)
            if current is None or offering_sort_key(offering) > offering_sort_key(current):
                best_by_slots[key] = offering
        compressed[course_code] = sorted(best_by_slots.values(), key=offering_sort_key, reverse=True)
    return compressed


def offering_sort_key(offering: Offering) -> tuple[float, int, float, str]:
    return (offering.score, offering.review_count or 0, offering.credits, offering.teaching_class)


def has_early_class(slots: frozenset[Slot]) -> bool:
    return any(slot.period == 1 for slot in slots)


def build_timetable(
    input_path: Path,
    sqlite_path: Path,
    *,
    allow_missing: bool = False,
    unrated_score: float = 0.0,
    max_early_classes: int | None = None,
) -> TimetableResult:
    input_config = load_input_config(input_path)
    compulsory_courses, optional_courses = parse_course_groups(input_config)
    requested_courses = compulsory_courses + optional_courses
    if max_early_classes is None:
        max_early_classes = parse_max_early_classes(input_config)

    by_course, warnings = load_offerings(sqlite_path, requested_courses, unrated_score=unrated_score)
    raw_candidate_count = sum(len(offerings) for offerings in by_course.values())
    missing_compulsory_courses = [course_code for course_code in compulsory_courses if not by_course[course_code]]
    missing_optional_courses = [course_code for course_code in optional_courses if not by_course[course_code]]
    missing_courses = missing_compulsory_courses + missing_optional_courses

    if missing_compulsory_courses and not allow_missing:
        stats = SearchStats(
            raw_candidate_count=raw_candidate_count,
            compressed_candidate_count=0,
            compressed_counts={},
            visited_nodes=0,
        )
        return make_result(
            status="infeasible",
            requested_courses=requested_courses,
            compulsory_courses=compulsory_courses,
            optional_courses=optional_courses,
            selected=[],
            missing_compulsory_courses=missing_compulsory_courses,
            missing_optional_courses=missing_optional_courses,
            max_early_classes=max_early_classes,
            stats=stats,
            warnings=warnings,
        )

    searchable_compulsory = [course_code for course_code in compulsory_courses if by_course[course_code]]
    searchable_optional = [course_code for course_code in optional_courses if by_course[course_code]]
    compulsory_compressed = compress_offerings({course_code: by_course[course_code] for course_code in searchable_compulsory})
    optional_compressed = compress_offerings({course_code: by_course[course_code] for course_code in searchable_optional})
    selected, weighted_score_sum, total_credits, weighted_average_score, visited_nodes = search_best_timetable(
        compulsory_compressed,
        optional_compressed,
        max_early_classes=max_early_classes,
    )
    compressed_counts = {
        **{course_code: len(offerings) for course_code, offerings in compulsory_compressed.items()},
        **{course_code: len(offerings) for course_code, offerings in optional_compressed.items()},
    }
    stats = SearchStats(
        raw_candidate_count=raw_candidate_count,
        compressed_candidate_count=sum(compressed_counts.values()),
        compressed_counts=compressed_counts,
        visited_nodes=visited_nodes,
    )

    if selected is None:
        return make_result(
            status="infeasible",
            requested_courses=requested_courses,
            compulsory_courses=compulsory_courses,
            optional_courses=optional_courses,
            selected=[],
            missing_compulsory_courses=missing_compulsory_courses,
            missing_optional_courses=missing_optional_courses,
            max_early_classes=max_early_classes,
            stats=stats,
            warnings=warnings,
        )

    selected_by_course = {offering.course_code: offering for offering in selected}
    ordered_selected = [selected_by_course[course_code] for course_code in compulsory_courses if course_code in selected_by_course]
    ordered_selected.extend(selected_by_course[course_code] for course_code in optional_courses if course_code in selected_by_course)
    return make_result(
        status="optimal",
        requested_courses=requested_courses,
        compulsory_courses=compulsory_courses,
        optional_courses=optional_courses,
        selected=ordered_selected,
        missing_compulsory_courses=missing_compulsory_courses,
        missing_optional_courses=missing_optional_courses,
        max_early_classes=max_early_classes,
        stats=stats,
        warnings=warnings,
        weighted_score_sum=weighted_score_sum,
        total_credits=total_credits,
        weighted_average_score=weighted_average_score,
    )


def make_result(
    *,
    status: str,
    requested_courses: list[str],
    compulsory_courses: list[str],
    optional_courses: list[str],
    selected: list[Offering],
    missing_compulsory_courses: list[str],
    missing_optional_courses: list[str],
    max_early_classes: int | None,
    stats: SearchStats,
    warnings: list[str],
    weighted_score_sum: float | None = None,
    total_credits: float | None = None,
    weighted_average_score: float | None = None,
) -> TimetableResult:
    selected_courses = {offering.course_code for offering in selected}
    selected_optional_courses = [course_code for course_code in optional_courses if course_code in selected_courses]
    skipped_optional_courses = [course_code for course_code in optional_courses if course_code not in selected_courses]
    return TimetableResult(
        status=status,
        requested_courses=requested_courses,
        compulsory_courses=compulsory_courses,
        optional_courses=optional_courses,
        selected=selected,
        selected_optional_courses=selected_optional_courses,
        skipped_optional_courses=skipped_optional_courses,
        missing_courses=missing_compulsory_courses + missing_optional_courses,
        missing_compulsory_courses=missing_compulsory_courses,
        missing_optional_courses=missing_optional_courses,
        total_score=weighted_score_sum,
        average_score=weighted_average_score,
        weighted_score_sum=weighted_score_sum,
        total_credits=total_credits,
        weighted_average_score=weighted_average_score,
        early_class_count=sum(1 for offering in selected if offering.has_early_class),
        max_early_classes=max_early_classes,
        stats=stats,
        warnings=warnings,
    )


def search_best_timetable(
    compulsory_by_course: dict[str, list[Offering]],
    optional_by_course: dict[str, list[Offering]],
    *,
    max_early_classes: int | None = None,
) -> tuple[list[Offering] | None, float | None, float | None, float | None, int]:
    if not compulsory_by_course and not optional_by_course:
        return [], 0.0, 0.0, None, 1

    compulsory_order = sorted(compulsory_by_course, key=lambda course_code: len(compulsory_by_course[course_code]))
    optional_order = sorted(optional_by_course, key=lambda course_code: len(optional_by_course[course_code]))
    course_items = [("compulsory", course_code) for course_code in compulsory_order]
    course_items.extend(("optional", course_code) for course_code in optional_order)

    best_selection: list[Offering] | None = None
    best_key: tuple[float, int, float, float, int] | None = None
    best_weighted_sum: float | None = None
    best_total_credits: float | None = None
    best_weighted_average: float | None = None
    visited_nodes = 0

    def dfs(
        index: int,
        occupied: frozenset[Slot],
        selected: list[Offering],
        weighted_sum: float,
        total_credits: float,
        early_class_count: int,
    ) -> None:
        nonlocal best_selection, best_key, best_weighted_sum, best_total_credits, best_weighted_average, visited_nodes
        visited_nodes += 1
        if max_early_classes is not None and early_class_count > max_early_classes:
            return
        if index == len(course_items):
            if total_credits <= 0:
                return
            weighted_average = weighted_sum / total_credits
            optional_count = sum(1 for offering in selected if offering.course_code in optional_by_course)
            candidate_key = (weighted_average, optional_count, total_credits, weighted_sum, -early_class_count)
            if best_key is None or candidate_key > best_key:
                best_key = candidate_key
                best_selection = list(selected)
                best_weighted_sum = weighted_sum
                best_total_credits = total_credits
                best_weighted_average = weighted_average
            return

        course_kind, course_code = course_items[index]
        offerings = compulsory_by_course[course_code] if course_kind == "compulsory" else optional_by_course[course_code]
        if course_kind == "optional":
            dfs(index + 1, occupied, selected, weighted_sum, total_credits, early_class_count)

        for offering in offerings:
            if occupied.isdisjoint(offering.slots):
                selected.append(offering)
                dfs(
                    index + 1,
                    occupied | offering.slots,
                    selected,
                    weighted_sum + offering.score * offering.credits,
                    total_credits + offering.credits,
                    early_class_count + int(offering.has_early_class),
                )
                selected.pop()

    dfs(0, frozenset(), [], 0.0, 0.0, 0)
    return best_selection, best_weighted_sum, best_total_credits, best_weighted_average, visited_nodes


def result_to_dict(result: TimetableResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "requested_courses": result.requested_courses,
        "compulsory_courses": result.compulsory_courses,
        "optional_courses": result.optional_courses,
        "selected_optional_courses": result.selected_optional_courses,
        "skipped_optional_courses": result.skipped_optional_courses,
        "missing_courses": result.missing_courses,
        "missing_compulsory_courses": result.missing_compulsory_courses,
        "missing_optional_courses": result.missing_optional_courses,
        "total_score": result.total_score,
        "average_score": result.average_score,
        "weighted_score_sum": result.weighted_score_sum,
        "total_credits": result.total_credits,
        "weighted_average_score": result.weighted_average_score,
        "early_class_count": result.early_class_count,
        "max_early_classes": result.max_early_classes,
        "stats": {
            "raw_candidate_count": result.stats.raw_candidate_count,
            "compressed_candidate_count": result.stats.compressed_candidate_count,
            "compressed_counts": result.stats.compressed_counts,
            "visited_nodes": result.stats.visited_nodes,
        },
        "warnings": result.warnings,
        "selected": [offering_to_dict(offering) for offering in result.selected],
    }


def offering_to_dict(offering: Offering) -> dict[str, Any]:
    return {
        "course_code": offering.course_code,
        "course_name": offering.course_name,
        "credits": offering.credits,
        "teacher": offering.teacher,
        "teaching_class": offering.teaching_class,
        "schedule_text": offering.schedule_text,
        "schedule_code": offering.schedule_code,
        "avg_rating": offering.avg_rating,
        "review_count": offering.review_count,
        "score": offering.score,
        "has_early_class": offering.has_early_class,
    }


def fetch_reviews(sqlite_path: Path, offering: Offering, *, limit: int = 10, offset: int = 0) -> list[Review]:
    query = """
        SELECT
            course_code,
            course_name,
            course_teacher,
            rating,
            score,
            semester_name,
            comment,
            modified_at
        FROM course_teacher_reviews
        WHERE course_code = ?
          AND course_teacher = ?
        ORDER BY modified_at DESC
        LIMIT ? OFFSET ?
    """
    with sqlite3.connect(sqlite_path) as connection:
        rows = connection.execute(query, (offering.course_code, offering.teacher, limit, offset)).fetchall()

    return [
        Review(
            course_code=row[0],
            course_name=row[1],
            course_teacher=row[2],
            rating=row[3],
            score=row[4],
            semester_name=row[5],
            comment=row[6],
            modified_at=row[7],
        )
        for row in rows
    ]


COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "header": "\033[1;36m",
    "index": "\033[1;33m",
}


def c(text: str, style: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{COLORS[style]}{text}{COLORS['reset']}"


def _color_rating(text: str, rating: float | None, enabled: bool) -> str:
    if rating is None:
        return c(text, "dim", enabled)
    if rating >= 4.5:
        return c(text, "green", enabled)
    if rating >= 3.5:
        return c(text, "yellow", enabled)
    return c(text, "red", enabled)


def format_reviews(reviews: list[Review], *, page: int, page_size: int = 10, color: bool = False) -> str:
    if not reviews:
        return "没有更多评论。"

    lines = [c(f"评论第 {page} 页：", "header", color)]
    start = (page - 1) * page_size
    for index, review in enumerate(reviews, start=start + 1):
        rating_text = "无评分" if review.rating is None else f"{review.rating:.1f}"
        rating_colored = _color_rating(rating_text, review.rating, color)
        semester = review.semester_name or "未知学期"
        modified_at = review.modified_at or "未知时间"
        comment = (review.comment or "").strip() or "无文字评论"
        idx = c(str(index), "index", color)
        sem = c(f"[{semester}]", "dim", color)
        lines.append(f"{idx}. {sem} rating={rating_colored} score={review.score or '无'} updated={modified_at}")
        lines.append(f"  {comment}")
    return "\n".join(lines)


def format_result(result: TimetableResult, *, color: bool = False) -> str:
    status_style = "green" if result.status == "optimal" else "red"
    lines = [f"{c('Status:', 'bold', color)} {c(result.status, status_style, color)}"]
    if result.missing_compulsory_courses:
        lines.append(f"{c('Missing compulsory courses:', 'red', color)} {', '.join(result.missing_compulsory_courses)}")
    if result.missing_optional_courses:
        lines.append(f"{c('Missing optional courses:', 'yellow', color)} {', '.join(result.missing_optional_courses)}")
    if result.weighted_average_score is not None:
        lines.append(f"{c('Weighted average score:', 'bold', color)} {c(f'{result.weighted_average_score:.3f}', 'green', color)}")
    if result.weighted_score_sum is not None and result.total_credits is not None:
        lines.append(f"{c('Weighted score sum:', 'bold', color)} {c(f'{result.weighted_score_sum:.3f}', 'green', color)}")
        lines.append(f"{c('Total credits:', 'bold', color)} {c(f'{result.total_credits:.1f}', 'green', color)}")

    early_limit = "unlimited" if result.max_early_classes is None else str(result.max_early_classes)
    early_style = "green" if result.max_early_classes is None or result.early_class_count <= result.max_early_classes else "red"
    lines.append(f"{c('Early classes:', 'bold', color)} {c(f'{result.early_class_count} / {early_limit}', early_style, color)}")

    if result.selected_optional_courses:
        lines.append(f"{c('Selected optional courses:', 'bold', color)} {', '.join(result.selected_optional_courses)}")
    if result.skipped_optional_courses:
        lines.append(f"{c('Skipped optional courses:', 'yellow', color)} {', '.join(result.skipped_optional_courses)}")

    lines.append(
        f"{c('Stats:', 'dim', color)} "
        f"raw={result.stats.raw_candidate_count}, "
        f"compressed={result.stats.compressed_candidate_count}, "
        f"visited_nodes={result.stats.visited_nodes}"
    )

    if result.stats.compressed_counts:
        counts = ", ".join(f"{course}={count}" for course, count in result.stats.compressed_counts.items())
        lines.append(f"{c('Compressed counts:', 'dim', color)} {counts}")

    if result.selected:
        lines.append("")
        lines.append(c("Selected offerings:", "header", color))
        for index, offering in enumerate(result.selected, start=1):
            rating_text = "unrated" if offering.avg_rating is None else f"{offering.avg_rating:.3f}"
            rating = _color_rating(rating_text, offering.avg_rating, color)
            reviews = 0 if offering.review_count is None else offering.review_count
            early = c("yes", "yellow", color) if offering.has_early_class else c("no", "green", color)
            course_type = c("[选修]", "yellow", color) if offering.course_code in result.optional_courses else c("[必修]", "cyan", color)
            lines.append(
                f"{c(str(index), 'index', color)}. {course_type} {c(offering.course_code, 'cyan', color)} {offering.course_name} | "
                f"{c(offering.teacher, 'magenta', color)} | {offering.teaching_class} | "
                f"credits={offering.credits:.1f} rating={rating} reviews={reviews} early={early} | {c(offering.schedule_code, 'dim', color)}"
            )

    if result.warnings:
        lines.append("")
        lines.append(c("Warnings:", "yellow", color))
        for warning in result.warnings[:20]:
            lines.append(f"- {c(warning, 'yellow', color)}")
        if len(result.warnings) > 20:
            lines.append(f"- {c(f'... {len(result.warnings) - 20} more warnings', 'yellow', color)}")

    return "\n".join(lines)
