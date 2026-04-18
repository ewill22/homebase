@echo off
REM Guapa Strains — Daily dispensary stock sync
REM Runs at 6:30 AM via Task Scheduler "Guapa Strains Sync"

cd /d C:\Users\eewil\homebase
C:\Users\eewil\AppData\Local\Programs\Python\Python314\python.exe strain_sync_run.py >> logs\strain_sync.log 2>&1
