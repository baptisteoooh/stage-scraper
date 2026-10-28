@echo off
rem Passage automatique de Stage Scraper, lance par le Planificateur de taches chaque matin.
rem Les messages sont ajoutes a la fin de logs\auto.log (dossier du projet).
rem Arguments supplementaires transmis a run.py (ex. : lancer_auto.cmd --verifier pour tester).

cd /d "%~dp0.."
if not exist logs mkdir logs
echo ===== %date% %time% =====>> logs\auto.log
".venv\Scripts\python.exe" run.py --auto %* >> logs\auto.log 2>&1
exit /b %errorlevel%
