from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


REVIEW_COLUMNS = [
    "review_id",
    "course_id",
    "course_code",
    "course_name",
    "course_teacher",
    "rating",
    "score",
    "semester_name",
    "comment",
    "comment_length",
    "created_at",
    "modified_at",
]

DEFAULT_INPUT_CSV = Path("data/raw/history_all_terms/course_community_reviews_all_terms.csv")
DEFAULT_OUTPUT_SQLITE = Path("data/processed/course_reviews_simple.sqlite")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a simple SQLite database from all-term course reviews.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-sqlite", type=Path, default=DEFAULT_OUTPUT_SQLITE)
    return parser.parse_args()


def build_simple_reviews_sqlite(input_csv: Path, output_sqlite: Path) -> None:
    reviews = load_reviews(input_csv)
    summary = build_summary(reviews)

    output_sqlite.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output_sqlite) as connection:
        connection.execute("DROP TABLE IF EXISTS course_teacher_reviews")
        connection.execute("DROP TABLE IF EXISTS course_teacher_rating_summary")
        create_tables(connection)
        connection.executemany(
            """
            INSERT INTO course_teacher_reviews (
                review_id, course_id, course_code, course_name, course_teacher, rating,
                score, semester_name, comment, comment_length, created_at, modified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ([review[column] for column in REVIEW_COLUMNS] for review in reviews),
        )
        connection.executemany(
            """
            INSERT INTO course_teacher_rating_summary (
                course_code, course_teacher, course_name, review_count, avg_rating
            ) VALUES (?, ?, ?, ?, ?)
            """,
            summary,
        )
        create_indexes(connection)


def load_reviews(input_csv: Path) -> list[dict[str, object]]:
    reviews: list[dict[str, object]] = []
    seen_review_ids: set[str] = set()

    with input_csv.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row.")
        missing_columns = [column for column in REVIEW_COLUMNS if column not in reader.fieldnames]
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

        for row in reader:
            review_id = clean_text(row["review_id"])
            if review_id in seen_review_ids:
                continue
            seen_review_ids.add(review_id)

            review = {column: row[column] for column in REVIEW_COLUMNS}
            review["review_id"] = review_id
            review["course_code"] = clean_text(review["course_code"])
            review["course_teacher"] = clean_text(review["course_teacher"])
            review["rating"] = parse_float(review["rating"])
            reviews.append(review)

    return reviews


def build_summary(reviews: list[dict[str, object]]) -> list[tuple[str, str, str | None, int, float | None]]:
    groups: dict[tuple[str, str], dict[str, object]] = {}

    for review in reviews:
        course_code = str(review["course_code"])
        course_teacher = str(review["course_teacher"])
        key = (course_code, course_teacher)
        group = groups.setdefault(
            key,
            {"course_name": None, "review_count": 0, "rating_sum": 0.0, "rating_count": 0},
        )
        group["review_count"] = int(group["review_count"]) + 1

        if group["course_name"] is None:
            course_name = clean_text(review["course_name"])
            if course_name:
                group["course_name"] = course_name

        rating = review["rating"]
        if isinstance(rating, float):
            group["rating_sum"] = float(group["rating_sum"]) + rating
            group["rating_count"] = int(group["rating_count"]) + 1

    summary = []
    for (course_code, course_teacher), group in groups.items():
        rating_count = int(group["rating_count"])
        avg_rating = round(float(group["rating_sum"]) / rating_count, 3) if rating_count else None
        summary.append(
            (
                course_code,
                course_teacher,
                group["course_name"],
                int(group["review_count"]),
                avg_rating,
            )
        )

    return summary


def create_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE course_teacher_reviews (
            review_id TEXT,
            course_id TEXT,
            course_code TEXT,
            course_name TEXT,
            course_teacher TEXT,
            rating REAL,
            score TEXT,
            semester_name TEXT,
            comment TEXT,
            comment_length TEXT,
            created_at TEXT,
            modified_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE course_teacher_rating_summary (
            course_code TEXT,
            course_teacher TEXT,
            course_name TEXT,
            review_count INTEGER,
            avg_rating REAL
        )
        """
    )


def create_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE INDEX idx_course_teacher_reviews_lookup "
        "ON course_teacher_reviews(course_code, course_teacher)"
    )
    connection.execute("CREATE INDEX idx_course_teacher_reviews_review_id ON course_teacher_reviews(review_id)")
    connection.execute(
        "CREATE UNIQUE INDEX idx_course_teacher_rating_summary_lookup "
        "ON course_teacher_rating_summary(course_code, course_teacher)"
    )


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_float(value: object) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def main() -> None:
    args = parse_args()
    build_simple_reviews_sqlite(args.input_csv, args.output_sqlite)
    print(f"SQLite database saved to: {args.output_sqlite}")


if __name__ == "__main__":
    main()
