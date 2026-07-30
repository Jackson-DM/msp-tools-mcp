<#
.SYNOPSIS
  Materializes the isolated Codex handoff directory outside this repository.

.DESCRIPTION
  The corpus author must not see what the corpus measures. Running Codex inside
  this repo would give it msp_tools/security.py (the patterns), the SYSTEM_PROMPT
  in msp_tools/classifier.py, and a README that names every case the guardrail
  has historically missed - at which point the resulting corpus measures the
  repo's own documentation.

  This script copies the brief and KB-006 into an empty directory somewhere else
  on disk, then prints its full contents so the isolation is something you can
  see rather than something you assumed. Contamination control becomes a
  property of the filesystem instead of an instruction Codex agreed to follow.

  ASCII ONLY. Windows PowerShell 5.1 reads a .ps1 with no byte-order mark as
  ANSI, so any non-ASCII character here arrives as mojibake and the parser fails
  on whatever quote-like byte falls out. Keeping the file to ASCII makes its
  encoding irrelevant, which is more durable than saving it correctly once.

.EXAMPLE
  .\eval\handoff\make-handoff.ps1
  .\eval\handoff\make-handoff.ps1 -Destination D:\scratch\corpus -Force
#>
[CmdletBinding()]
param(
    [string]$Destination,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# $PSScriptRoot is <repo>\eval\handoff
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $Destination) {
    $Destination = Join-Path (Split-Path $repo -Parent) '_codex-corpus-handoff'
}

$kb = Join-Path $repo 'kb\KB-006-security-incident-response.md'
if (-not (Test-Path $kb)) { throw "KB-006 not found at $kb" }

# Refuse to write inside the repo: a working directory under the repo root
# leaves 'cd ..' between Codex and everything this exercise withholds.
$destFull = [System.IO.Path]::GetFullPath($Destination)
$repoFull = [System.IO.Path]::GetFullPath($repo)
if ($destFull.StartsWith($repoFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Destination '$destFull' is inside the repo. Pick a path outside it; the isolation is the point."
}

if (Test-Path $destFull) {
    if (-not $Force) { throw "$destFull already exists. Re-run with -Force to replace it." }
    Remove-Item $destFull -Recurse -Force
}

New-Item -ItemType Directory -Path $destFull          -Force | Out-Null
New-Item -ItemType Directory -Path "$destFull\output" -Force | Out-Null

Copy-Item (Join-Path $PSScriptRoot 'AGENTS.md')     $destFull
Copy-Item (Join-Path $PSScriptRoot 'FORMAT.md')     $destFull
Copy-Item (Join-Path $PSScriptRoot 'TEMPLATE.json') $destFull
Copy-Item $kb                                       $destFull

Write-Host ""
Write-Host "Handoff directory ready:" -ForegroundColor Green
Write-Host "  $destFull"
Write-Host ""
Write-Host "Everything Codex can see. Verify this list; anything unexpected is a leak:"
Get-ChildItem $destFull -Recurse -File |
    ForEach-Object { "  {0,-46} {1,7:N0} bytes" -f $_.FullName.Substring($destFull.Length + 1), $_.Length } |
    Write-Host

Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  cd `"$destFull`""
Write-Host "  codex          # it reads AGENTS.md on its own; give it no further context"
Write-Host ""
Write-Host "Then, back in the repo:"
Write-Host "  Copy-Item `"$destFull\output\round4-codex.json`" .\eval\corpora\"
Write-Host "  uv run python scripts/eval_classifier.py round4-codex --dry-run"
Write-Host ""
