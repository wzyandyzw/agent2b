param(
    [ValidateSet("customer", "delivery", "finance", "quote", "management", "knowledge", "product", "all")]
    [string]$Scenario = "customer",
    [string]$Prompt = "",
    [switch]$KeepErp
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
$env:ERP_BASE_URL = "http://127.0.0.1:9100"

$root = $PSScriptRoot
$agentProject = Join-Path $root "agent\apps\agent-python"
$erpProject = Join-Path $root "environment\shenwei-erp"
$erpPython = Join-Path $erpProject ".venv\Scripts\python.exe"
$uv = (Get-Command uv).Source
$scenarioPrompts = [ordered]@{
    customer   = "汇总客户 C-E001 的重点订单、物流和回款风险"
    delivery   = "订单 ORD-10086 的物流是否延误，尚未签收吗"
    finance    = "查看客户 C-E003 的应收和逾期风险"
    quote      = "为 C-E001 的 X200-Pro 2 台产品做选型和报价"
    management = "生成本周已发货订单的经营异常周报"
    knowledge  = "检索分子筛膜售前方案需要注意什么"
    product    = "查一下 X200-Pro 的规格和库存交期"
}

$server = $null
$erpReady = $false
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:9100/health" -TimeoutSec 2
    $erpReady = $health.status -eq "ok"
} catch {
    $erpReady = $false
}

if (-not $erpReady) {
    if (-not (Test-Path -LiteralPath $erpPython)) {
        & $uv sync --project $erpProject --python 3.12
        if ($LASTEXITCODE -ne 0) {
            throw "模拟 ERP 依赖安装失败。"
        }
    }
    $server = Start-Process -FilePath $erpPython `
        -ArgumentList @("-m", "shenwei_erp") `
        -WorkingDirectory $erpProject -WindowStyle Hidden -PassThru
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:9100/health" -TimeoutSec 2
            if ($health.status -eq "ok") {
                $erpReady = $true
                break
            }
        } catch {
        }
    }
}

if (-not $erpReady) {
    throw "模拟 ERP 未能启动。"
}

$names = if ($Scenario -eq "all") { @($scenarioPrompts.Keys) } else { @($Scenario) }
try {
    foreach ($name in $names) {
        $text = if ($Prompt -and $names.Count -eq 1) { $Prompt } else { $scenarioPrompts[$name] }
        if ($names.Count -gt 1) {
            Write-Host "`n=== $name ===" -ForegroundColor Cyan
        }
        & $uv run --project $agentProject agent-cli chat --offline-demo $text
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
} finally {
    if ($server -and -not $KeepErp) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
}

