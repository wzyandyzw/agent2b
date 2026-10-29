"""配置只从环境变量来；.env 由这里读（不引第三方包）。密钥不会出现在任何其它地方。"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass


def load_dotenv(start: pathlib.Path | None = None) -> pathlib.Path | None:
    """从当前目录向上找 .env；已存在的环境变量不覆盖。"""
    cur = (start or pathlib.Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        f = d / ".env"
        if f.is_file():
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return f
    return None


@dataclass(frozen=True)
class Settings:
    dashscope_api_key: str
    model: str
    model_base_url: str
    erp_base_url: str
    erp_api_key: str
    runs_dir: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
            model=os.environ.get("AGENT_MODEL", "qwen-plus"),
            model_base_url=os.environ.get("AGENT_MODEL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            erp_base_url=os.environ.get("ERP_BASE_URL", "http://localhost:9100"),
            erp_api_key=os.environ.get("ERP_API_KEY", "east-demo-key"),
            runs_dir=os.environ.get("AGENT_RUNS_DIR", "runs"),
        )
