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

  The brief itself comes from briefs\roundN.md. With no -Round, the
  highest-numbered brief is used, which is almost always what you want; pass
  -Round to re-issue an earlier one.

.EXAMPLE
  .\eval\handoff\make-handoff.ps1
  .\eval\handoff\make-handoff.ps1 -Round 4
  .\eval\handoff\make-handoff.ps1 -Destination D:\scratch\corpus -Force
#>
[CmdletBinding()]
param(
    [int]$Round,
    [string]$Destination,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# $PSScriptRoot is <repo>\eval\handoff
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $Destination) {
    $Destination = Join-Path (Split-Path $repo -Parent) '_codex-corpus-handoff'
}

# Briefs are kept per round in briefs\roundN.md rather than overwriting one
# AGENTS.md, so that what each corpus author was told stays readable next to the
# corpus they produced. A corpus is a claim about who wrote it; the brief is the
# other half of that claim, and it should not live only in git history.
# @(...) because a single brief comes back as a scalar, and a scalar does not
# index or count the way the rest of this block assumes.
$briefDir = Join-Path $PSScriptRoot 'briefs'
$briefs = @(Get-ChildItem (Join-Path $briefDir 'round*.md') -File |
    Sort-Object { [int]($_.BaseName -replace '\D', '') })
if ($briefs.Count -eq 0) { throw "No briefs found in $briefDir" }

if (-not $Round) {
    $brief = $briefs[-1]
    $Round = [int]($brief.BaseName -replace '\D', '')
} else {
    $hit = @($briefs | Where-Object { [int]($_.BaseName -replace '\D', '') -eq $Round })
    if ($hit.Count -eq 0) {
        $have = ($briefs | ForEach-Object { $_.BaseName }) -join ', '
        throw "No brief for round ${Round}. Have: $have"
    }
    $brief = $hit[0]
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

# The brief is delivered as AGENTS.md because that is the filename Codex reads
# unprompted. Its round number is deliberately not in the delivered name: the
# author has no use for it, and a "round 5" label invites them to wonder what
# rounds 1 to 4 found.
Copy-Item $brief.FullName                           (Join-Path $destFull 'AGENTS.md')
Copy-Item (Join-Path $PSScriptRoot 'FORMAT.md')     $destFull
Copy-Item (Join-Path $PSScriptRoot 'TEMPLATE.json') $destFull
Copy-Item $kb                                       $destFull

Write-Host ""
Write-Host "Brief: round $Round ($($brief.Name)), delivered as AGENTS.md" -ForegroundColor Green
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
Write-Host "Then, back in the repo (a round may produce more than one corpus):"
Write-Host "  Copy-Item `"$destFull\output\*.json`" .\eval\corpora\"
Write-Host "  uv run python scripts/eval_classifier.py --list"
Write-Host "  uv run python scripts/eval_classifier.py <corpus-id> --dry-run"
Write-Host ""
Write-Host "Run --dry-run first on every corpus. It is free, makes no API calls,"
Write-Host "and stage 1's recall on an unfamiliar corpus is the baseline the"
Write-Host "stage-2 number has to beat."
Write-Host ""
