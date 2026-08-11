from __future__ import annotations

import argparse
import json

from worker.decision_agent import run_decision_agent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args()
    request = json.loads(args.request_json)
    result = run_decision_agent(request)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
