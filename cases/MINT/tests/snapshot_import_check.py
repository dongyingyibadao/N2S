#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys
import traceback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = args.expected_source.resolve()
    result = {"expected_source": str(expected), "python": sys.version.split()[0], "status": "failed"}
    try:
        import lerobot
        import lerobot_policy_mint
        from lerobot_policy_mint import configuration_mint, mint_utils, modeling_mint, processor_mint

        files = {
            "package": lerobot_policy_mint.__file__,
            "configuration": configuration_mint.__file__,
            "mint_utils": mint_utils.__file__,
            "modeling": modeling_mint.__file__,
            "processor": processor_mint.__file__,
        }
        wrong = [path for path in files.values() if expected not in Path(path).resolve().parents]
        result.update(
            status="passed" if not wrong else "failed",
            imported_files=files,
            wrong_source_files=wrong,
            lerobot_version=getattr(lerobot, "__version__", "unknown"),
        )
    except Exception as exc:
        result["exception"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback_tail": "\n".join(traceback.format_exc().splitlines()[-12:]),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
