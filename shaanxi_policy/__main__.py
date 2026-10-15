import argparse
import json
from datetime import datetime
from pathlib import Path

from industry_monitor_core.web import LOCAL_TZ
from .collect import collect, empty_state
from .report import payload, write_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=Path("config/sources.json"))
    parser.add_argument("--state", type=Path, default=Path("data/state.json"))
    parser.add_argument("--output", type=Path, default=Path("site"))
    parser.add_argument("--budget", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.budget <= 30:
        parser.error("budget must be between 1 and 30 articles per source")
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    previous = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else empty_state()
    if previous.get("schema_version") != 1:
        raise ValueError("Unsupported state version; refusing to discard the baseline")
    instant = datetime.now(LOCAL_TZ)
    state, health = collect(sources, previous, instant, budget=args.budget)
    report = payload(state, health, instant)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.state.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.state)
    write_report(report, args.output)
    print(json.dumps({"date": report["date"], "counts": report["counts"], "sources": health}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
