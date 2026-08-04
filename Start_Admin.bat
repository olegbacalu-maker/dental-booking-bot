@echo off
title DentPilot Admin
rem %~dp0 = papka etogo faila: ne lomaetsya pri pereezde proekta
cd /d %~dp0
docker info >nul 2>&1
if errorlevel 1 (
  echo Docker ne zapushchen. Zapusti: wscript D:\Docker\start-docker.vbs i podozhdi ikonku kita, potom povtori.
  pause
  exit /b 1
)
docker compose up -d
start "" http://localhost:8088/admin
