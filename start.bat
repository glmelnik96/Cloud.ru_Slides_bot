@echo off
setlocal
title Slides Bot - START

REM Repo root = folder of this .bat (trailing backslash included).
set "ROOT=%~dp0"
set "COMPOSE_DIR=%ROOT%docker"
set "ENV_FILE=%ROOT%.env"

echo ============================================
echo   Slides Bot - starting Docker stack
echo ============================================

REM --- Docker engine reachable? ---
docker info >nul 2>&1
if errorlevel 1 goto no_docker

REM --- .env present? ---
if not exist "%ENV_FILE%" goto no_env

cd /d "%COMPOSE_DIR%"
if errorlevel 1 goto no_dir

REM "start.bat build" -> rebuild worker and bot images first.
if /i "%~1"=="build" (
    echo Rebuilding worker and bot images...
    docker compose --env-file "%ENV_FILE%" build worker bot
    if errorlevel 1 goto build_fail
)

echo Starting containers ^(redis, minio, bot, worker^)...
docker compose --env-file "%ENV_FILE%" up -d
if errorlevel 1 goto up_fail

echo.
echo --- Container status ---
docker compose --env-file "%ENV_FILE%" ps

echo.
echo Bot is running.
echo   stop.bat            - stop the stack
echo   start.bat build     - start with image rebuild
echo   docker compose --env-file "%ENV_FILE%" logs -f bot worker
echo.
goto end

:no_docker
echo [ERROR] Docker is not running. Start Docker Desktop and retry.
goto fail
:no_env
echo [ERROR] .env not found: %ENV_FILE%
echo Copy .env.example to .env and fill in the keys.
goto fail
:no_dir
echo [ERROR] compose dir not found: %COMPOSE_DIR%
goto fail
:build_fail
echo [ERROR] image build failed.
goto fail
:up_fail
echo [ERROR] docker compose up failed.
goto fail

:fail
pause
endlocal
exit /b 1

:end
pause
endlocal
