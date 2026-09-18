param(
    [Parameter(Mandatory = $true)]
    [string]$InputMarkdown,

    [Parameter(Mandatory = $true)]
    [string]$OutputDocx
)

$node = $env:IEEE_SPIDER_NODE
$nodeModules = $env:IEEE_SPIDER_NODE_MODULES

if (-not $node) {
    $runtime = Join-Path $HOME `
        '.cache\codex-runtimes\codex-primary-runtime\dependencies'
    $node = Join-Path $runtime 'node\bin\node.exe'
    if (-not $nodeModules) {
        $nodeModules = Join-Path $runtime 'node\node_modules'
    }
}

if (-not (Test-Path -LiteralPath $node)) {
    throw "Node.js runtime not found: $node"
}
if ($nodeModules -and -not (Test-Path -LiteralPath $nodeModules)) {
    throw "Node.js module directory not found: $nodeModules"
}

if ($nodeModules) {
    $env:NODE_PATH = $nodeModules
}
& $node (Join-Path $PSScriptRoot 'markdown_to_docx.js') `
    $InputMarkdown `
    $OutputDocx

if ($LASTEXITCODE -ne 0) {
    throw "DOCX rendering failed with exit code $LASTEXITCODE"
}
