"""1.3 对照：同一任务的固定流程实现——校验型号 → 查两个接口 → 汇总。不用模型。
用法：uv run --project apps/agent-python python scripts/fixed_flow.py "查一下 X200 的规格和当前库存交期"
用同样的数据与正常错误处理；它能覆盖的任务不比 Loop 差，差在"请求形态一变就要加分支"。"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "apps/agent-python/src"))
from agent_app.config import Settings  # noqa: E402
from agent_app.contracts import ToolFailure  # noqa: E402
from agent_app.tools.erp_client import ErpClient  # noqa: E402

MODEL_RE = re.compile(r"\b([XTS]\d{2,3}(?:-Pro)?)\b", re.I)


def fixed_flow(text: str, erp: ErpClient) -> str:
    m = MODEL_RE.search(text)
    if not m:
        return "请提供型号。"                                     # 分支 1：缺型号
    sku = m.group(1).upper().replace("-PRO", "-Pro")
    try:
        p = erp.get_product(sku, timeout_s=5)
    except ToolFailure as f:
        return f"型号 {sku} 不存在。" if f.error.category == "not_found" else f"规格查询失败（{f.error.category}）。"
    try:
        inv = erp.get_inventory(sku, 1, timeout_s=5)             # 固定流程：不管用户问没问，都查
        avail = f"可用 {inv['available']} 台，最早 {inv['earliest_ship_date']} 深圳发运（观测 {inv['as_of']}）"
    except ToolFailure as f:
        avail = f"交期暂时无法确认（{f.error.category}）"          # 固定文案
    return f"{p['name_cn']}：{p['key_spec']}；挂牌价 {p['list_price']['amount']} {p['list_price']['currency']}。{avail}。"


if __name__ == "__main__":
    s = Settings.from_env()
    erp = ErpClient(s.erp_base_url, s.erp_api_key)
    for text in sys.argv[1:] or ["查一下 X200 的规格和当前库存交期"]:
        print(f"输入：{text}\n固定流程：{fixed_flow(text, erp)}\n")
