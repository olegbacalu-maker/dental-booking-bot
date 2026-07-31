@echo off
title DentPilot Admin
cd /d D:\bot-sandbox\dental-demo
docker info >nul 2>&1
if errorlevel 1 (
  echo Docker ne zapushchen. Zapusti: wscript D:\Docker\start-docker.vbs i podozhdi ikonku kita, potom povtori.
  pause
  exit /b 1
)
docker compose up -d
start "" http://localhost:8088/admin
