"""Shared test setup: put the scraper package and repo root on sys.path so
tests can `import scraper_core`, `import run_scraper`, `import venues`, and so
the data-contract tests can open files relative to the repo root."""
import os
import sys

SCRAPER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(SCRAPER_DIR)

for p in (SCRAPER_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def repo_path(*parts):
    return os.path.join(REPO_ROOT, *parts)
