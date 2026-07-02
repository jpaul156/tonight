#!/usr/bin/env python3
"""Run the pytest suite and write data/test_status.json so app_health.html can
show whether the tests are green. Exits non-zero on failure so CI still fails,
but always writes the status file first.

Usage (from repo root):
    python3 scraper/run_tests.py
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(REPO_ROOT, "scraper", "tests")
JUNIT = os.path.join(REPO_ROOT, "test-results.xml")
STATUS_FILE = os.path.join(REPO_ROOT, "data", "test_status.json")


def main():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TESTS_DIR, "-q", f"--junitxml={JUNIT}"],
        cwd=REPO_ROOT,
    )

    status = {"status": "unknown", "at": datetime.now(timezone.utc).isoformat()}
    if os.path.exists(JUNIT):
        suite = ET.parse(JUNIT).getroot()
        # junit root is <testsuites> wrapping <testsuite>, or <testsuite> itself
        ts = suite.find("testsuite") if suite.tag == "testsuites" else suite
        total = int(ts.get("tests", 0))
        failed = int(ts.get("failures", 0)) + int(ts.get("errors", 0))
        skipped = int(ts.get("skipped", 0))
        status.update(
            status="pass" if failed == 0 else "fail",
            total=total, passed=total - failed - skipped,
            failed=failed, skipped=skipped,
        )
        os.remove(JUNIT)

    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)
    print(f"Wrote {STATUS_FILE}: {status['status']} "
          f"({status.get('passed', '?')}/{status.get('total', '?')} passed)")
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
