<#
.SYNOPSIS
  Restores the Agentic OS working folder on Windows and checks the memory files.

.DESCRIPTION
  Fixes: "Claude Code could not be started because there is no folder at
  C:\ahmadzayan-hub\agentic-os-final-project."

  The script clones the repository from GitHub if the folder is missing or is
  not a Git checkout, checks out the working branch, and confirms that the
  three memory files exist and are not empty: Memory.md, project-progress.md
  and session-logs.md. It never deletes anything, never force-pushes and never
  overwrites uncommitted work: if the folder already holds a checkout with
  changes, it stops and says so.

.PARAMETER Path
  Where the folder must exist. Default: the path Claude Code was looking for.

.PARAMETER Branch
  The branch to check out. Default: the working branch of this project.

.PARAMETER Launch
  Start Claude Code in the folder when everything checks out.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File restore-workspace.ps1 -Launch
#>
[CmdletBinding()]
param(
    [string]$Path = 'C:\ahmadzayan-hub\agentic-os-final-project',
    [string]$Branch = 'claude/zealous-dijkstra-oud9ix',
    [string]$Fallback = 'claude/agentic-os-final-project-53j6ql',
    [string]$Remote = 'https://github.com/ahmadzayan-hub/agentic-os-final-project.git',
    [switch]$Launch
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Message) {
    Write-Host "STOPPED: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail 'Git is not installed. Install Git for Windows from https://git-scm.com, then run this again.'
}

$parent = Split-Path -Parent $Path
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent | Out-Null
    Write-Host "Created $parent"
}

$isCheckout = Test-Path -LiteralPath (Join-Path $Path '.git')
if (-not $isCheckout) {
    if ((Test-Path -LiteralPath $Path) -and (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1)) {
        Fail "$Path exists, is not empty and is not a Git checkout. Move it aside or pass a different -Path."
    }
    Write-Host "Cloning $Remote into $Path ..."
    git clone $Remote $Path
    if ($LASTEXITCODE -ne 0) { Fail 'The clone failed. Check your network and your GitHub sign-in (git credential manager), then run this again.' }
} else {
    Write-Host "Found an existing checkout at $Path"
}

Set-Location -LiteralPath $Path

if ($isCheckout) {
    $dirty = git status --porcelain
    if ($dirty) { Fail 'The checkout has uncommitted changes. Commit or stash them first; nothing was changed.' }
}

git fetch origin
if ($LASTEXITCODE -ne 0) { Fail 'git fetch failed. Check your network and sign-in.' }

$target = $Branch
git ls-remote --exit-code --heads origin $target *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Branch $target is not on GitHub yet; using $Fallback" -ForegroundColor Yellow
    $target = $Fallback
}

git checkout $target 2> $null
if ($LASTEXITCODE -ne 0) {
    git checkout -b $target --track "origin/$target"
    if ($LASTEXITCODE -ne 0) { Fail "Could not check out $target." }
}
git merge --ff-only "origin/$target" 2> $null | Out-Null

$required = @('Memory.md', 'project-progress.md', 'session-logs.md', 'CLAUDE.md', '.claude\settings.json')
$missing = @()
foreach ($name in $required) {
    $file = Join-Path $Path $name
    if (-not (Test-Path -LiteralPath $file) -or (Get-Item -LiteralPath $file).Length -eq 0) {
        $missing += $name
        Write-Host ("MISSING or empty: {0}" -f $name) -ForegroundColor Red
    } else {
        $lines = (Get-Content -LiteralPath $file | Measure-Object -Line).Lines
        Write-Host ("OK  {0,-24} {1} lines" -f $name, $lines)
    }
}
if ($missing.Count -gt 0) {
    Fail ("Required files are missing on branch $target. Run: git log --oneline -- <file> to find where they went.")
}

$entries = (Select-String -Path (Join-Path $Path 'session-logs.md') -Pattern '^## 20\d\d-\d\d-\d\d').Count
Write-Host "session-logs.md holds $entries dated session entries"
Write-Host "Ready: $Path on branch $target" -ForegroundColor Green

if ($Launch) {
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
        Fail 'Claude Code (claude) is not on the PATH. Install it, then run: claude'
    }
    claude
}
