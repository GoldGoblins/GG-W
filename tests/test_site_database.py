#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend.site_database import PORT, import_sql_dump, rewrite_preview_origin

    if PORT != 3307:
        raise AssertionError("local MariaDB port must stay 3307")
    bad = import_sql_dump("/tmp/no-such-dump.sql")
    if not str(bad).startswith("FAIL"):
        raise AssertionError("missing SQL dump was accepted")
    remote = rewrite_preview_origin("https://goldgoblins.se")
    if not str(remote).startswith("FAIL"):
        raise AssertionError("non-localhost siteurl rewrite accepted")
    print("SITE_DATABASE_TEST=PASS")
    print("LOCAL_MYSQL=127.0.0.1:3307")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
