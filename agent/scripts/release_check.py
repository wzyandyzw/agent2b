"""发布前检查：配置、测试、敏感信息、文档。用法：uv run --project apps/agent-python python scripts/release_check.py"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "apps/agent-python"


def run(cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main() -> int:
    ok = True

    def check(name, passed, detail=""):
        nonlocal ok
        ok &= bool(passed)
        print(f"[{'ok' if passed else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))

    tracked = run(["git", "ls-files"]).stdout.splitlines()
    check(".env 不在版本库", ".env" not in tracked)
    check(".env.example 存在且不含真实 key", (ROOT / ".env.example").exists() and
          not re.search(r"DASHSCOPE_API_KEY=\S{10,}", (ROOT / ".env.example").read_text()))
    leaks = run(["git", "grep", "-nE", r"sk-[A-Za-z0-9_.-]{16,}", "--", ":!*.md", ":!.env.example"]).stdout
    check("仓库里没有形如 sk- 的密钥", leaks == "", leaks[:200])
    runs_tracked = [f for f in tracked if f.startswith("apps/agent-python/runs/") or f.startswith("runs/")]
    check("运行日志 runs/ 没入库", not runs_tracked)
    t = run(["uv", "run", "pytest", "tests/unit", "-q"], cwd=APP)
    last = t.stdout.strip().splitlines()[-1] if t.stdout.strip() else t.stderr[-200:]
    check("单元测试全绿", t.returncode == 0, last)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for key in ["uv sync", "pytest", "agent-cli"]:
        check(f"README 含启动命令 {key}", key in readme)
    check("Release 说明存在", (ROOT / "docs/releases/w1.md").exists())
    smoke = sorted((ROOT / "evals/runs").glob("w01-smoke-*/results.jsonl"))
    check("冒烟记录存在", bool(smoke), str(smoke[-1].relative_to(ROOT)) if smoke else "")
    tags = run(["git", "tag", "--list", "w1*"]).stdout.split()
    check("本周 tag 齐全", all(t in tags for t in ["w1.4", "w1.5", "w1.6", "w1.7", "w1.8"]), " ".join(tags))
    print("\n发布检查通过" if ok else "\n发布检查未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
