param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$ErrorActionPreference = 'Stop'

$skillRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $skillRoot 'bin\ieee-spider.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw "Embedded IEEE Spider executable not found: $executable"
}

$runtimeHome = if ($env:IEEE_SPIDER_HOME) {
    $env:IEEE_SPIDER_HOME
} else {
    Join-Path $HOME '.ieee-spider'
}

$runtimeHome = [IO.Path]::GetFullPath($runtimeHome)
$configDir = Join-Path $runtimeHome 'config'
$defaultConfigDir = Join-Path $skillRoot 'assets\default-config'

New-Item -ItemType Directory -Path $configDir -Force | Out-Null

foreach ($name in @('authors.toml', 'login.toml')) {
    $target = Join-Path $configDir $name
    $source = Join-Path $defaultConfigDir $name
    if (-not (Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath $source)) {
        Copy-Item -LiteralPath $source -Destination $target
    }
}

$env:IEEE_SPIDER_HOME = $runtimeHome
& $executable @CliArgs
exit $LASTEXITCODE
