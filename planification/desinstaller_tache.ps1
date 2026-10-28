# Supprime la tâche planifiée « Stage Scraper » (les données et le projet ne sont pas touchés).
#   powershell -ExecutionPolicy Bypass -File planification\desinstaller_tache.ps1

param([string]$NomTache = "Stage Scraper")
$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $NomTache -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $NomTache -Confirm:$false
    Write-Host "Tâche « $NomTache » supprimée."
} else {
    Write-Host "Aucune tâche « $NomTache » à supprimer."
}
