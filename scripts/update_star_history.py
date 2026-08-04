#!/usr/bin/env python3
"""Generate repository-owned Star history artifacts from the GitHub API."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "docs" / "star-history.json"
SVG_PATH = ROOT / "docs" / "star-history.svg"
MARKDOWN_PATH = ROOT / "STAR_HISTORY.md"


def history_is_current(
    repository: str,
    points: list[dict[str, int | str]],
) -> bool:
    if not all(path.exists() for path in (JSON_PATH, SVG_PATH, MARKDOWN_PATH)):
        return False
    try:
        existing = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        existing.get("repository") == repository
        and existing.get("history") == points
    )


def fetch_stargazers(repository: str, token: str) -> list[dict[str, str]]:
    stargazers: list[dict[str, str]] = []
    page = 1
    while True:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/stargazers?per_page=100&page={page}",
            headers={
                "Accept": "application/vnd.github.star+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "xianyu-super-butler-star-history",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.load(response)
        stargazers.extend(batch)
        if len(batch) < 100:
            return stargazers
        page += 1


def build_points(stargazers: list[dict[str, str]]) -> list[dict[str, int | str]]:
    stars_per_day = Counter(
        entry["starred_at"][:10]
        for entry in stargazers
        if entry.get("starred_at")
    )
    total = 0
    points = []
    for date, count in sorted(stars_per_day.items()):
        total += count
        points.append({"date": date, "stars": total})
    return points


def write_json(repository: str, points: list[dict[str, int | str]]) -> str:
    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(
        json.dumps(
            {
                "repository": repository,
                "updated_at": updated_at,
                "stars": points[-1]["stars"] if points else 0,
                "history": points,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return updated_at


def write_markdown(
    repository: str,
    points: list[dict[str, int | str]],
    updated_at: str,
) -> None:
    total = points[-1]["stars"] if points else 0
    rows = "\n".join(f"| {point['date']} | {point['stars']} |" for point in points)
    MARKDOWN_PATH.write_text(
        f"""# Star History

Repository: `{repository}`

Current stars: **{total}**

Updated at: `{updated_at}`

![Star History](docs/star-history.svg)

| Date | Stars |
| --- | ---: |
{rows}
""",
        encoding="utf-8",
    )


def write_svg(repository: str, points: list[dict[str, int | str]]) -> None:
    width, height = 960, 360
    left, right, top, bottom = 72, 28, 54, 58
    chart_width = width - left - right
    chart_height = height - top - bottom
    total = int(points[-1]["stars"]) if points else 0
    maximum = max(total, 1)

    coordinates = []
    divisor = max(len(points) - 1, 1)
    for index, point in enumerate(points):
        x = left + chart_width * index / divisor
        y = top + chart_height * (1 - int(point["stars"]) / maximum)
        coordinates.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(coordinates)
    first_date = points[0]["date"] if points else "-"
    last_date = points[-1]["date"] if points else "-"
    title = escape(repository)
    SVG_PATH.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Star history for {title}</title>
  <desc id="desc">{total} current stars from {first_date} to {last_date}</desc>
  <rect width="{width}" height="{height}" fill="#ffffff"/>
  <text x="{left}" y="30" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#111827">{title}</text>
  <text x="{width - right}" y="30" text-anchor="end" font-family="Arial, sans-serif" font-size="16" fill="#f59e0b">{total} stars</text>
  <line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_height}" stroke="#d1d5db"/>
  <line x1="{left}" y1="{top + chart_height}" x2="{left + chart_width}" y2="{top + chart_height}" stroke="#d1d5db"/>
  <line x1="{left}" y1="{top}" x2="{left + chart_width}" y2="{top}" stroke="#e5e7eb" stroke-dasharray="4 4"/>
  <line x1="{left}" y1="{top + chart_height / 2}" x2="{left + chart_width}" y2="{top + chart_height / 2}" stroke="#e5e7eb" stroke-dasharray="4 4"/>
  <text x="{left - 12}" y="{top + 5}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#6b7280">{maximum}</text>
  <text x="{left - 12}" y="{top + chart_height / 2 + 5}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#6b7280">{maximum // 2}</text>
  <text x="{left - 12}" y="{top + chart_height + 5}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#6b7280">0</text>
  <polyline points="{polyline}" fill="none" stroke="#f59e0b" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
  <text x="{left}" y="{height - 20}" font-family="Arial, sans-serif" font-size="12" fill="#6b7280">{first_date}</text>
  <text x="{width - right}" y="{height - 20}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#6b7280">{last_date}</text>
</svg>
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot-count",
        type=int,
        help="Generate a one-point bootstrap snapshot without calling GitHub.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repository = os.getenv("GITHUB_REPOSITORY", "23Star/xianyu-super-butler")
    if args.snapshot_count is not None:
        today = datetime.now(timezone.utc).date().isoformat()
        points = [{"date": today, "stars": args.snapshot_count}]
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise SystemExit("GITHUB_TOKEN is required")
        points = build_points(fetch_stargazers(repository, token))

    if history_is_current(repository, points):
        print("Star history is already current")
        return

    updated_at = write_json(repository, points)
    write_markdown(repository, points, updated_at)
    write_svg(repository, points)


if __name__ == "__main__":
    main()
