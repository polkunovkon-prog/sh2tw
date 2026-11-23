# install.ps1 — установщик sh2tw (Windows PowerShell 5.1+)
# Полная инструкция: docs/install.md. Запуск: powershell -ExecutionPolicy Bypass -File install.ps1
param(
    [string]$GameDir = "",
    [switch]$SkipBackup,
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor DarkYellow }
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor DarkRed }

Step "sh2tw: Stronghold 2 x Total War — установка"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repo
if (-not (Test-Path "tools\sh2tw\cli.py")) { Warn "Запустите из корня репозитория sh2tw"; exit 1 }
Ok "репозиторий: $repo"

# ---------------------------------------------------------------- Python
Step "Проверка Python 3.11+"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Warn "python не найден в PATH (https://www.python.org/downloads/, галочка Add to PATH)"; exit 1 }
& python --version
Ok "python доступен"

# ------------------------------------------------------------------- venv
Step "Виртуальное окружение .venv"
if (-not (Test-Path ".venv")) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Warn "не удалось создать .venv"; exit 1 }
}
$venvPy = ".venv\Scripts\python.exe"
Ok ".venv готов"

Step "Зависимости (pytest, pyyaml, fastapi, uvicorn, httpx)"
& $venvPy -m pip install --quiet pytest pyyaml fastapi uvicorn httpx
if ($LASTEXITCODE -ne 0) { Warn "pip install не удался — проверьте сеть"; exit 1 }
Ok "зависимости установлены"

# ------------------------------------------------------------- tests
if (-not $SkipTests) {
    Step "Тесты (полный suite)"
    & $venvPy -m pytest -q
    if ($LASTEXITCODE -ne 0) { Warn "тесты упали — установка прервана"; exit 1 }
    Ok "все тесты зелёные"
}

# ---------------------------------------------------------- config
Step "Настройка config/project.ini"
if ($GameDir -ne "" -and (Test-Path "$GameDir\Stronghold2.exe")) {
    $ini = Get-Content "config\project.ini" -Raw -Encoding UTF8
    $saves = "$env:USERPROFILE\Documents\Stronghold 2\Saves"
    $userMaps = "$env:USERPROFILE\Documents\Stronghold 2\Maps"
    $backup = "$env:USERPROFILE\Documents\sh2tw\backup"
    $ini = $ini -replace 'game_dir = .*', "game_dir = $GameDir"
    $ini = $ini -replace 'maps_dir_game = .*', "maps_dir_game = $GameDir\Maps"
    $ini = $ini -replace 'saves_dir = .*', "saves_dir = $saves"
    $ini = $ini -replace 'maps_dir_user = .*', "maps_dir_user = $userMaps"
    $ini = $ini -replace 'backup_dir = .*', "backup_dir = $backup"
    Set-Content "config\project.ini" $ini -Encoding UTF8
    Ok "project.ini настроен на $GameDir"
} else {
    Warn "game_dir не задан/не найден Stronghold2.exe — заполните config/project.ini вручную (см. docs/install.md)"
}

# ---------------------------------------------------------- backup
if (-not $SkipBackup) {
    Step "Бэкап Maps и Saves (00 §0.7)"
    $env:PYTHONPATH = "tools"
    & $venvPy -m sh2tw.cli backup
    if ($LASTEXITCODE -ne 0) {
        Warn "бэкап не выполнен (каталоги игры не настроены?) — исправьте project.ini и запустите: $venvPy -m sh2tw.cli backup"
    } else {
        Ok "бэкап выполнен"
    }
}

# ---------------------------------------------------------- финал
Step "Готово!"
Write-Host @"

Запуск кампании:
  `$env:PYTHONPATH = "tools"
  .venv\Scripts\python.exe -m sh2tw.cli campaign --campaign campaigns/main
  → браузер: http://127.0.0.1:8402

Дальше (опционально):
  - подключение живых боёв: docs/install.md §6 (шаблоны карт)
  - доктрины ИИ из ваших .aic:  docs/install.md §7
  - откат игры к ванили:       python tools/restore_vanilla.py --no-dry-run

Руководство игрока: docs/player_guide.md
"@ -ForegroundColor Gray
