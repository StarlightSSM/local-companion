# Install the "other model": llama.cpp (Vulkan build) + Qwen3.5-9B GGUF (+ mmproj for image understanding)
# Usage: powershell -ExecutionPolicy Bypass -File setup-alt-model.ps1 [-Target D:\sumin\local-ai] [-Quant Q4_K_M]
# (ASCII only on purpose: Windows PowerShell 5.1 misreads UTF-8 scripts without BOM)
param(
    [string]$Target = "D:\sumin\local-ai",
    [string]$Quant = "Q4_K_M",
    [string]$Repo = "bartowski/Qwen_Qwen3.5-9B-GGUF",
    [string]$Prefix = "Qwen_Qwen3.5-9B"
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Target | Out-Null
$models = Join-Path $Target "models"
New-Item -ItemType Directory -Force $models | Out-Null

# 1) latest llama.cpp Windows Vulkan build
$bin = Join-Path $Target "llama.cpp"
if (-not (Test-Path (Join-Path $bin "llama-server.exe"))) {
    Write-Host "[1/3] checking latest llama.cpp release"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $rels = Invoke-RestMethod "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=5" -Headers @{ "User-Agent" = "local-companion-setup" }
    $asset = $null
    foreach ($rel in @($rels)) {
        $asset = @($rel.assets) | Where-Object { $_.name -like "*bin-win-vulkan-x64.zip" } | Select-Object -First 1
        if ($asset) { break }
    }
    if (-not $asset) { throw "Vulkan build not found in latest release" }
    $zip = Join-Path $Target $asset.name
    Write-Host "      downloading $($asset.name) ($($rel.tag_name))"
    curl.exe -L --fail -o $zip $asset.browser_download_url
    if ($LASTEXITCODE -ne 0) { throw "download failed" }
    Expand-Archive -Force $zip $bin
    Remove-Item $zip
    $exe = Get-ChildItem $bin -Recurse -Filter llama-server.exe | Select-Object -First 1
    if ($exe.DirectoryName -ne (Resolve-Path $bin).Path) {
        Get-ChildItem $exe.DirectoryName | Move-Item -Destination $bin -Force
    }
} else { Write-Host "[1/3] llama.cpp already installed" }

# 2) model GGUF, 3) mmproj (resumable: just run again if interrupted)
$files = @("$Prefix-$Quant.gguf", "mmproj-$Prefix-f16.gguf")
$i = 2
foreach ($f in $files) {
    $dst = Join-Path $models $f
    Write-Host "[$i/3] downloading $f"
    curl.exe -L --fail -C - -o $dst "https://huggingface.co/$Repo/resolve/main/$f"
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 33) { throw "download failed: $f" }
    $i++
}
Write-Host "DONE: $Target"
