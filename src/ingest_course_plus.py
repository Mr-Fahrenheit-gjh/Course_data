from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path


COURSE_PLUS_COLUMNS = [
    "course_code",
    "course_name",
    "department",
    "teacher",
    "credits",
    "enrollment",
    "class_capacity",
    "teaching_class",
    "campus",
    "course_type",
    "schedule_text",
    "has_virtual_schedule",
    "is_weekend_course",
    "time_bucket",
]

DEFAULT_INPUT_CSV = Path("data/processed/current_term_2025-2026_1/course_plus_offerings_2025-2026_1_cleaned.csv")
DEFAULT_SQLITE = Path("data/processed/course_reviews_simple.sqlite")
DAY_CODES = {
    "一": "D1",
    "二": "D2",
    "三": "D3",
    "四": "D4",
    "五": "D5",
    "六": "D6",
    "日": "D7",
    "天": "D7",
}
SCHEDULE_PATTERN = re.compile(r"星期([一二三四五六日天])第([^节{}]+)节\{([^{}]+)\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest cleaned Course+ offerings into the simple SQLite database.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    return parser.parse_args()


def ingest_course_plus(input_csv: Path, sqlite_path: Path) -> None:
    offerings = load_offerings(input_csv)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("DROP TABLE IF EXISTS course_plus_offerings")
        create_table(connection)
        connection.executemany(
            """
            INSERT INTO course_plus_offerings (
                course_code, course_name, department, teacher, credits, enrollment,
                class_capacity, teaching_class, campus, course_type, schedule_text,
                schedule_code, has_virtual_schedule, is_weekend_course, time_bucket
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ([offering[column] for column in COURSE_PLUS_COLUMNS_WITH_CODE] for offering in offerings),
        )
        create_indexes(connection)


def load_offerings(input_csv: Path) -> list[dict[str, object]]:
    offerings: list[dict[str, object]] = []

    with input_csv.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row.")
        missing_columns = [column for column in COURSE_PLUS_COLUMNS if column not in reader.fieldnames]
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

        for row in reader:
            offering = {column: clean_text(row[column]) for column in COURSE_PLUS_COLUMNS}
            offering["credits"] = parse_float(offering["credits"])
            offering["enrollment"] = parse_int(offering["enrollment"])
            offering["class_capacity"] = parse_int_or_float(offering["class_capacity"])
            offering["schedule_code"] = encode_schedule(str(offering["schedule_text"]))
            offerings.append(offering)

    return offerings


def encode_schedule(schedule_text: str) -> str:
    entries: list[str] = []
    for part in filter(None, (item.strip() for item in schedule_text.split(";"))):
        match = SCHEDULE_PATTERN.search(part)
        if not match:
            entries.append(f"RAW:{part}")
            continue
        day, periods_text, weeks_text = match.groups()
        day_code = DAY_CODES[day]
        periods = "+".join(f"P{period.strip()}" for period in periods_text.split(",") if period.strip())
        weeks = "+".join(f"W{week.strip().removesuffix('周')}" for week in weeks_text.split(",") if week.strip())
        entries.append(f"{day_code}:{periods}:{weeks}")
    return ";".join(entries)


def create_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE course_plus_offerings (
            course_code TEXT,
            course_name TEXT,
            department TEXT,
            teacher TEXT,
            credits REAL,
            enrollment INTEGER,
            class_capacity REAL,
            teaching_class TEXT,
            campus TEXT,
            course_type TEXT,
            schedule_text TEXT,
            schedule_code TEXT,
            has_virtual_schedule TEXT,
            is_weekend_course TEXT,
            time_bucket TEXT
        )
        """
    )


def create_indexes(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE INDEX idx_course_plus_offerings_course_code ON course_plus_offerings(course_code)")
    connection.execute("CREATE INDEX idx_course_plus_offerings_teaching_class ON course_plus_offerings(teaching_class)")
    connection.execute("CREATE INDEX idx_course_plus_offerings_schedule_code ON course_plus_offerings(schedule_code)")


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_float(value: object) -> float | None:
    text = clean_text(value)
    if not text or text.lower() == "nan":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: object) -> int | None:
    number = parse_float(value)
    if number is None:
        return None
    return int(number)


def parse_int_or_float(value: object) -> int | float | None:
    number = parse_float(value)
    if number is None:
        return None
    if number.is_integer():
        return int(number)
    return number


def main() -> None:
    args = parse_args()
    ingest_course_plus(args.input_csv, args.sqlite)
    print(f"Course+ offerings ingested into: {args.sqlite}")


COURSE_PLUS_COLUMNS_WITH_CODE = [
    "course_code",
    "course_name",
    "department",
    "teacher",
    "credits",
    "enrollment",
    "class_capacity",
    "teaching_class",
    "campus",
    "course_type",
    "schedule_text",
    "schedule_code",
    "has_virtual_schedule",
    "is_weekend_course",
    "time_bucket",
]


if __name__ == "__main__":
    main()
