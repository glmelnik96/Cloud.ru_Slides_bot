@echo off
setlocal
title Slides Bot - STOP

set "ROOT=%~dp0"
set "COMPOSE_DIR=%ROOT%docker"
set "ENV_FILE=%ROOT%.env"

echo ============================================
echo   Slides Bot - stopping Docker stack
echo ============================================

docker info >nul 2>&1
if errorlevel 1 goto no_docker

cd /d "%COMPOSE_DIR%"
if errorlevel 1 goto no_dir

REM "stop.bat clean" -> also remove named volumes (redis, minio, sessions).
REM WARNING: this erases all sessions and stored data.
if /i "%~1"=="clean" (
    echo Stopping containers AND removing volumes ^(redis, minio, sessions^)...
    docker compose --env-file "%ENV_FILE%" down -v
) else (
    echo Stopping and removing containers ^(volume data is kept^)...
    docker compose --env-file "%ENV_FILE%" down
)
if errorlevel 1 goto down_fail

echo.
echo Stack stopped.  Use "stop.bat clean" to also wipe volume data.
echo.
goto end

:no_docker
echo [ERROR] Docker is not running - nothing to stop.
goto fail
:no_dir
echo [ERROR] compose dir not found: %COMPOSE_DIR%
goto fail
:down_fail
echo [ERROR] docker compose down failed.
goto fail

:fail
pause
endlocal
exit /b 1

:end
pause
endlocal
