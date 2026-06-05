# Deploys scenario-3 Capa 2 — APIM AI Gateway in front of the existing
# Foundry account from main.bicep. Additive: does NOT redeploy main.bicep.
# Idempotent: re-running just patches the policy/backends.
#
# Usage (from repo root):
#   .\scenario-3\infra\deploy_aigateway.ps1
#   .\scenario-3\infra\deploy_aigateway.ps1 -ResourceGroup rg-aieval3-poc -Location eastus2
#
# Prereqs (must already exist; produced by deploy.ps1):
#   * .env.scenario-3 with AZURE_AI_FOUNDRY_ACCOUNT, APP_INSIGHTS_RESOURCE_ID,
#     LOG_ANALYTICS_RESOURCE_ID, AZURE_RESOURCE_GROUP, AZURE_SUBSCRIPTION_ID.
#
# Heads-up:
#   APIM StandardV2 first-time provisioning takes ~15-25 minutes. The script
#   blocks on the deployment.

param(
    [string]$SubscriptionId = '',
    [string]$ResourceGroup  = '',
    [string]$Location       = 'eastus2'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$envPath  = Join-Path $repoRoot '.env.scenario-3'

if (-not (Test-Path $envPath)) {
    Write-Host "ERROR: $envPath not found. Run deploy.ps1 first." -ForegroundColor Red
    exit 1
}

# ---- parse .env.scenario-3 -------------------------------------------------------
$envMap = @{}
Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*$') { return }
    $kv = $_.Split('=', 2)
    if ($kv.Length -eq 2) { $envMap[$kv[0].Trim()] = $kv[1].Trim() }
}

if (-not $ResourceGroup) { $ResourceGroup = $envMap['AZURE_RESOURCE_GROUP'] }
if (-not $SubscriptionId) { $SubscriptionId = $envMap['AZURE_SUBSCRIPTION_ID'] }
$foundryAccount  = $envMap['AZURE_AI_FOUNDRY_ACCOUNT']
$appiResourceId  = $envMap['APP_INSIGHTS_RESOURCE_ID']
$lawResourceId   = $envMap['LOG_ANALYTICS_RESOURCE_ID']

foreach ($pair in @(
    @{ k='AZURE_RESOURCE_GROUP';       v=$ResourceGroup },
    @{ k='AZURE_AI_FOUNDRY_ACCOUNT';   v=$foundryAccount },
    @{ k='APP_INSIGHTS_RESOURCE_ID';   v=$appiResourceId },
    @{ k='LOG_ANALYTICS_RESOURCE_ID';  v=$lawResourceId }
)) {
    if (-not $pair.v) {
        Write-Host ("ERROR: {0} missing from .env.scenario-3" -f $pair.k) -ForegroundColor Red
        exit 1
    }
}

$appiName = ($appiResourceId -split '/')[-1]
$lawName  = ($lawResourceId  -split '/')[-1]

# ---- az session ------------------------------------------------------------
Write-Host '==> Checking az login...' -ForegroundColor Cyan
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host 'No session. Run `az login` and re-run this script.' -ForegroundColor Red
    exit 1
}
if ($SubscriptionId -and ($account.id -ne $SubscriptionId)) {
    az account set --subscription $SubscriptionId | Out-Null
    $account = az account show | ConvertFrom-Json
}
Write-Host ("    Subscription: {0} ({1})" -f $account.name, $account.id)
Write-Host ("    Resource group: {0}" -f $ResourceGroup)
Write-Host ("    Foundry account: {0}" -f $foundryAccount)
Write-Host ("    App Insights:    {0}" -f $appiName)
Write-Host ("    Log Analytics:   {0}" -f $lawName)

# ---- deploy ----------------------------------------------------------------
Write-Host ''
Write-Host '==> Deploying APIM AI Gateway (StandardV2, ~15-25 min first time)...' -ForegroundColor Cyan
$deployName = "aieval3-aigw-{0:yyyyMMddHHmmss}" -f (Get-Date)

$deployJson = az deployment group create `
    --resource-group $ResourceGroup `
    --name $deployName `
    --template-file (Join-Path $PSScriptRoot 'aigateway.bicep') `
    --parameters `
        location=$Location `
        foundryAccountName=$foundryAccount `
        appInsightsName=$appiName `
        logAnalyticsWorkspaceName=$lawName `
    --only-show-errors `
    -o json | ConvertFrom-Json

$o = $deployJson.properties.outputs
$apimName          = $o.apimName.value
$gatewayUrl        = $o.gatewayUrl.value
$openAiDeployment  = $o.openAiDeploymentName.value
$openAiApiVersion  = $o.openAiApiVersion.value
$csEndpoint        = $o.contentSafetyEndpoint.value

# ---- fetch subscription primary key (Bicep @secure() output is masked) -----
Write-Host '==> Fetching default subscription primary key...' -ForegroundColor Cyan
$primaryKey = az apim subscription show `
    --service-name $apimName `
    --resource-group $ResourceGroup `
    --sid 'corp-llm-default' `
    --query primaryKey -o tsv 2>$null

if (-not $primaryKey) {
    # APIM CLI subscription show doesn't always return primaryKey; use REST.
    $primaryKey = az rest --method post `
        --uri "https://management.azure.com/subscriptions/$($account.id)/resourceGroups/$ResourceGroup/providers/Microsoft.ApiManagement/service/$apimName/subscriptions/corp-llm-default/listSecrets?api-version=2024-06-01-preview" `
        --query primaryKey -o tsv
}

# ---- append AZURE_OPENAI_GATEWAY_* to .env.scenario-3 ----------------------------
Write-Host '==> Updating .env.scenario-3 with gateway entries...' -ForegroundColor Cyan
$existing = Get-Content $envPath | Where-Object {
    $_ -notmatch '^AZURE_OPENAI_GATEWAY_' -and
    $_ -notmatch '^AZURE_CONTENT_SAFETY_'  -and
    $_ -notmatch '^# ---- Capa 2'
}
$append = @"
# ---- Capa 2 — APIM AI Gateway (generated by deploy_aigateway.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm'))
AZURE_OPENAI_GATEWAY_ENDPOINT=$gatewayUrl
AZURE_OPENAI_GATEWAY_SUBSCRIPTION_KEY=$primaryKey
AZURE_OPENAI_GATEWAY_DEPLOYMENT=$openAiDeployment
AZURE_OPENAI_GATEWAY_API_VERSION=$openAiApiVersion
AZURE_OPENAI_GATEWAY_APIM_NAME=$apimName
AZURE_CONTENT_SAFETY_ENDPOINT=$csEndpoint
"@
Set-Content -Path $envPath -Value (($existing -join [Environment]::NewLine) + [Environment]::NewLine + $append) -Encoding utf8

Write-Host ''
Write-Host '==> DONE' -ForegroundColor Green
Write-Host ("    APIM:            {0}" -f $apimName)
Write-Host ("    Gateway URL:     {0}" -f $gatewayUrl)
Write-Host ("    Deployment:      {0}" -f $openAiDeployment)
Write-Host ("    Content Safety:  {0}" -f $csEndpoint)
Write-Host ''
Write-Host 'Smoke test:'
Write-Host @"
  curl.exe -X POST `"$gatewayUrl/openai/deployments/$openAiDeployment/chat/completions?api-version=$openAiApiVersion`" ``
    -H `"Content-Type: application/json`" ``
    -H `"api-key: <key from .env.scenario-3>`" ``
    -H `"X-Corp-Team: governance`" ``
    -H `"X-Corp-Actor: $env:USERNAME`" ``
    -H `"X-Corp-Agent: smoke-test`" ``
    -H `"X-Corp-Corr-Id: smoke-`$(Get-Date -Format yyyyMMddHHmmss)`" ``
    -d '{`"messages`":[{`"role`":`"user`",`"content`":`"ping`"}],`"max_tokens`":10}'
"@
