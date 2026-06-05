<#
.SYNOPSIS
    Vypise pocty stiahnuti suborov z GitHub Releases cez GitHub CLI (gh).

.DESCRIPTION
    Verzia cez `gh api`. Vyzaduje nainstalovany a PRIHLASENY GitHub CLI
    (`gh auth login`). Vyhodou je vyssi rate-limit a pristup k privatnym repo.
    Pre verejny repo bez prihlasenia pouzi radsej tools\download_counts.ps1
    (cez verejne REST API, bez tokenu).

    Spustenie:
        powershell -ExecutionPolicy Bypass -File tools\download_counts_gh.ps1
    alebo v otvorenom PowerShell:
        .\tools\download_counts_gh.ps1
#>

[CmdletBinding()]
param(
    # Repozitar v tvare "vlastnik/nazov" (pozor: nazov je malymi pismenami).
    [string]$Repo = "Orimslav/archiv_blockov"
)

$ErrorActionPreference = "Stop"

# gh moze byt nainstalovany az po starte tohto procesu -> obnov PATH z registra,
# aby sme ho nasli aj bez restartu terminalu.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [Environment]::GetEnvironmentVariable("Path", "User")

$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Host "GitHub CLI (gh) nie je nainstalovany alebo nie je v PATH." -ForegroundColor Red
    Write-Host "Instalacia: winget install --id GitHub.cli   (potom novy terminal)" -ForegroundColor Yellow
    exit 1
}

# Overenie prihlasenia.
& gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "gh nie je prihlaseny. Spusti: gh auth login" -ForegroundColor Red
    exit 1
}

try {
    $releases = & gh api "repos/$Repo/releases" | ConvertFrom-Json
}
catch {
    Write-Host "Chyba volania 'gh api': $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

if (-not $releases -or $releases.Count -eq 0) {
    Write-Host "Repozitar '$Repo' zatial nema ziadne vydania (releases)." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "=== Pocty stiahnuti (cez gh): $Repo ===" -ForegroundColor Cyan

foreach ($r in $releases) {
    Write-Host ""
    Write-Host "[$($r.tag_name)]  ($($r.published_at))" -ForegroundColor Green
    if (-not $r.assets -or $r.assets.Count -eq 0) {
        Write-Host "  (bez prilozenych suborov)"
        continue
    }
    foreach ($a in $r.assets) {
        Write-Host ("  {0,-42} {1,6}x" -f $a.name, $a.download_count)
    }
}

$total = ($releases.assets | Measure-Object -Property download_count -Sum).Sum
if (-not $total) { $total = 0 }

Write-Host ""
Write-Host "=== SPOLU vsetky subory/verzie: $total stiahnuti ===" -ForegroundColor Cyan
Write-Host ""
