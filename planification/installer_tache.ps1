# Crée (ou met à jour) la tâche planifiée « Stage Scraper » : un passage automatique chaque jour à 8 h.
# Si le PC est éteint ou en veille à 8 h, le passage se fait dès que possible après.
#
# Lancement, depuis le dossier du projet (PowerShell ou CMD) :
#   powershell -ExecutionPolicy Bypass -File planification\installer_tache.ps1
# Autre heure :
#   powershell -ExecutionPolicy Bypass -File planification\installer_tache.ps1 -Heure 07:30

param(
    [string]$Heure = "08:00",
    [string]$NomTache = "Stage Scraper"
)
$ErrorActionPreference = "Stop"

$racine = Split-Path -Parent $PSScriptRoot
$lanceur = Join-Path $PSScriptRoot "lancer_auto.cmd"
$python = Join-Path $racine ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Environnement virtuel introuvable ($python). Suis d'abord l'installation du README."
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$lanceur`"" -WorkingDirectory $racine
$declencheur = New-ScheduledTaskTrigger -Daily -At $Heure
$reglages = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew
# Tâche lancée avec ton compte Windows, quand ta session est ouverte (aucun mot de passe à donner).
$utilisateur = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $NomTache -Action $action -Trigger $declencheur -Settings $reglages `
    -Principal $utilisateur -Force `
    -Description "Stage Scraper : collecte, tri, notation IA et mails (python run.py --auto)." | Out-Null

Write-Host "Tâche « $NomTache » créée : chaque jour à $Heure (ou dès que possible si le PC était éteint)."
Write-Host "Journal des passages automatiques : $(Join-Path $racine 'logs\auto.log')"
Write-Host "Pour la tester tout de suite : Start-ScheduledTask -TaskName `"$NomTache`""
