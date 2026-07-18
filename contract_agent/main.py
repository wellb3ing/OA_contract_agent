"""Command-line entry point for the contract check agent."""

import argparse
import json
import sys
from contract_agent.agent import run_contract_check


def main():
    parser = argparse.ArgumentParser(description="合同校验 Agent")
    parser.add_argument(
        "--params",
        type=str,
        required=True,
        help='查询参数 JSON 字符串，例如 \'{"contract_id": "C001"}\'',
    )
    args = parser.parse_args()

    try:
        query_params = json.loads(args.params)
    except json.JSONDecodeError:
        print("错误：--params 必须是合法的 JSON 字符串", file=sys.stderr)
        sys.exit(1)

    print("正在处理合同，请稍候...\n")
    try:
        report = run_contract_check(query_params)
    except Exception as e:
        print(f"合同校验失败：{e}", file=sys.stderr)
        sys.exit(1)
    print(report)


if __name__ == "__main__":
    main()
