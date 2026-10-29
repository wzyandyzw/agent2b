"""CLI 入口。W1.4：只有骨架，后续节逐步填入。"""
import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print("agent-cli · 深维工作台 W1\n  chat   与 agent 对话（w1.7 起）\n  replay 回放一次会话（w1.8 起）")
        return 0
    print(f"未知命令：{argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
