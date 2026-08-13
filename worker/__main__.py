from __future__ import annotations

import argparse
import json

from worker.decision_agent import run_decision_agent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args()
    request = json.loads(args.request_json)
    try:
        result = run_decision_agent(request)
    except Exception as error:
        print(
            json.dumps(
                {
                    "event": "application_failure",
                    "exception_type": type(error).__name__,
                    "exception_message": str(error),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        raise
    print(
        json.dumps(
            {"event": "invocation_completed", "output": result},
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
