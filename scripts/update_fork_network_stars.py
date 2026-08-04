#!/usr/bin/env python3
"""Generate a README-ready SVG with stars across a GitHub fork network."""

from __future__ import annotations

import argparse
import json
import os
from collections import deque
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"


def github_get(path: str, token: str | None, params: dict[str, Any] | None = None) -> Any:
    url = f"{API_ROOT}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "xianyu-super-butler-fork-star-counter",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API request failed ({exc.code}): {detail}") from exc


def fetch_network(repo: str, token: str | None) -> dict[str, Any]:
    root = github_get(f"/repos/{repo}", token)
    unique_forks: dict[str, dict[str, Any]] = {}
    parents_to_scan: deque[str] = deque([root["full_name"]])
    scanned_parents: set[str] = set()

    while parents_to_scan:
        parent = parents_to_scan.popleft()
        if parent in scanned_parents:
            continue
        scanned_parents.add(parent)

        page = 1
        while True:
            batch = github_get(
                f"/repos/{parent}/forks",
                token,
                {"sort": "oldest", "per_page": 100, "page": page},
            )
            for fork in batch:
                full_name = fork["full_name"]
                if full_name not in unique_forks:
                    unique_forks[full_name] = fork
                    if int(fork.get("forks_count", 0)) > 0:
                        parents_to_scan.append(full_name)
            if len(batch) < 100:
                break
            page += 1

    ranked_forks = sorted(
        unique_forks.values(),
        key=lambda fork: (-int(fork.get("stargazers_count", 0)), fork["full_name"].lower()),
    )

    main_stars = int(root.get("stargazers_count", 0))
    fork_stars = sum(int(fork.get("stargazers_count", 0)) for fork in ranked_forks)
    starred_forks = sum(1 for fork in ranked_forks if int(fork.get("stargazers_count", 0)) > 0)

    return {
        "repository": root["full_name"],
        "main_stars": main_stars,
        "fork_count": len(ranked_forks),
        "starred_fork_count": starred_forks,
        "fork_stars": fork_stars,
        "total_stars": main_stars + fork_stars,
        "top_forks": [
            {
                "repository": fork["full_name"],
                "stars": int(fork.get("stargazers_count", 0)),
                "url": fork["html_url"],
            }
            for fork in ranked_forks[:5]
            if int(fork.get("stargazers_count", 0)) > 0
        ],
    }


def render_svg(data: dict[str, Any], updated_at: str) -> str:
    width = 900
    top_forks = data["top_forks"]
    height = 270 + max(1, len(top_forks)) * 42
    max_fork_stars = max((fork["stars"] for fork in top_forks), default=1)

    rows: list[str] = []
    if top_forks:
        for index, fork in enumerate(top_forks):
            y = 278 + index * 42
            bar_width = max(8, round(300 * fork["stars"] / max_fork_stars))
            rows.append(
                f'<text x="32" y="{y}" class="repo">{escape(fork["repository"])}</text>'
                f'<rect x="500" y="{y - 16}" width="{bar_width}" height="14" rx="3" class="bar"/>'
                f'<text x="820" y="{y}" text-anchor="end" class="count">{fork["stars"]:,}</text>'
            )
    else:
        rows.append('<text x="32" y="278" class="muted">No public fork has received a star yet.</text>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Fork network star summary for {escape(data["repository"])}</title>
  <desc id="desc">{data["total_stars"]:,} stars across the main repository and {data["fork_count"]:,} public forks.</desc>
  <style>
    .bg {{ fill: #ffffff; stroke: #d0d7de; }}
    .title {{ fill: #1f2328; font: 700 24px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .total {{ fill: #1f2328; font: 700 48px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .label {{ fill: #59636e; font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .metric {{ fill: #1f2328; font: 700 22px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .repo {{ fill: #1f2328; font: 14px ui-monospace, SFMono-Regular, Consolas, monospace; }}
    .count {{ fill: #1f2328; font: 700 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .muted {{ fill: #59636e; font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .card {{ fill: #f6f8fa; }}
    .bar {{ fill: #f5b301; }}
    @media (prefers-color-scheme: dark) {{
      .bg {{ fill: #0d1117; stroke: #30363d; }}
      .title, .total, .metric, .repo, .count {{ fill: #f0f6fc; }}
      .label, .muted {{ fill: #8b949e; }}
      .card {{ fill: #161b22; }}
    }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8" class="bg"/>
  <text x="32" y="44" class="title">Fork Network Stars</text>
  <text x="32" y="104" class="total">{data["total_stars"]:,}</text>
  <text x="32" y="130" class="label">combined stars across the main repository and public forks</text>

  <rect x="32" y="154" width="256" height="76" rx="6" class="card"/>
  <text x="48" y="181" class="label">Main repository</text>
  <text x="48" y="213" class="metric">{data["main_stars"]:,} stars</text>

  <rect x="306" y="154" width="256" height="76" rx="6" class="card"/>
  <text x="322" y="181" class="label">Public fork repositories</text>
  <text x="322" y="213" class="metric">{data["fork_count"]:,} forks</text>

  <rect x="580" y="154" width="288" height="76" rx="6" class="card"/>
  <text x="596" y="181" class="label">Stars received by forks</text>
  <text x="596" y="213" class="metric">{data["fork_stars"]:,} on {data["starred_fork_count"]:,} forks</text>

  <text x="32" y="258" class="label">Most-starred forks</text>
  {"".join(rows)}
  <text x="868" y="{height - 18}" text-anchor="end" class="label">Updated {escape(updated_at)} UTC</text>
</svg>
"""


def write_if_changed(output_json: Path, output_svg: Path, data: dict[str, Any]) -> bool:
    previous: dict[str, Any] | None = None
    if output_json.exists():
        try:
            previous = json.loads(output_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None

    comparable_previous = {key: value for key, value in (previous or {}).items() if key != "updated_at"}
    if comparable_previous == data and output_svg.exists():
        print("Fork network star data is unchanged.")
        return False

    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    payload = {**data, "updated_at": updated_at}
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_svg.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_svg.write_text(render_svg(data, updated_at), encoding="utf-8")
    print(
        f"Updated {output_svg}: {data['total_stars']:,} total stars "
        f"across {data['fork_count'] + 1:,} repositories."
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "23Star/xianyu-super-butler"))
    parser.add_argument("--json", type=Path, default=Path("docs/fork-network-stars.json"))
    parser.add_argument("--svg", type=Path, default=Path("docs/fork-network-stars.svg"))
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    data = fetch_network(args.repo, token)
    write_if_changed(args.json, args.svg, data)


if __name__ == "__main__":
    main()
