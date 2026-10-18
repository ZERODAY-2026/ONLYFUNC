@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title DataMind

:: Colors only where the terminal supports them (Windows Terminal); plain tags everywhere else.
set "OK=[OK]" & set "FAIL=[FAIL]" & set "WARN=[*]"
if defined WT_SESSION (
    for /f %%a in ('powershell -NoProfile -Command "[char]27"') do set "ESC=%%a"
    set "OK=!ESC![32m[OK]!ESC![0m" & set "FAIL=!ESC![31m[FAIL]!ESC![0m" & set "WARN=!ESC![33m[*]!ESC![0m"
)

:: Live trace: every connection, network call, SQL statement, model call and workflow step is printed in this window
:: with sizes and timings. On by default here; run.bat <command> --quiet (or set DM_TRACE=0) turns it off.
if not defined DM_TRACE set "DM_TRACE=1"
for %%A in (%*) do if /i "%%~A"=="--quiet" set "DM_TRACE=0"

set "CMD=%~1"
if not defined CMD set "CMD=serve"
if /i "!CMD!"=="help" goto usage
if /i "!CMD!"=="/?" goto usage
if /i "!CMD!"=="-h" goto usage

echo.
echo   DataMind - talk to your data  (Gemma + Snowflake)
if "!DM_TRACE!"=="1" ( echo   Live trace is ON: each call is shown below with sizes and timings ^(--quiet turns it off, full log in logs\datamind.log^) ) else ( echo   Live trace is off ^(DM_TRACE=0^) )
echo.

:: ---------------------------------------------------------------- 1. Python 3.10+
echo [1/4] Python
set "VENV_PY=.venv\Scripts\python.exe"
set "PY="
if exist "%VENV_PY%" set "PY=%VENV_PY%"
if not defined PY call :find_python
if not defined PY (
    echo   !FAIL! Python 3.10+ was not found.
    echo         Install it from https://www.python.org/downloads/ ^(tick "Add Python to PATH"^), then run run.bat again.
    exit /b 1
)
for /f "tokens=*" %%v in ('"!PY!" --version 2^>^&1') do echo   !OK! %%v

:: ---------------------------------------------------------------- 2. Virtual environment
echo [2/4] Virtual environment
if not exist "%VENV_PY%" (
    echo   !WARN! Creating .venv ...
    "!PY!" -m venv .venv
    if errorlevel 1 (
        echo   !FAIL! Could not create .venv. Try deleting the .venv folder and run again.
        exit /b 1
    )
)
set "PY=%VENV_PY%"
echo   !OK! .venv ready

:: ---------------------------------------------------------------- 3. Dependencies (self-healing)
echo [3/4] Dependencies
set "PROBE=import snowflake.connector, streamlit, yaml, sqlglot, ollama, ucimlrepo, pandas, dotenv, cryptography"
"!PY!" -c "!PROBE!" >nul 2>&1
if errorlevel 1 (
    echo   !WARN! Missing packages, installing from requirements.txt ^(first run takes a few minutes^) ...
    "!PY!" -m pip install -q --upgrade pip
    "!PY!" -m pip install -q -r requirements.txt
    "!PY!" -c "!PROBE!" >nul 2>&1
    if errorlevel 1 (
        echo   !FAIL! Packages still missing. See the pip messages above, or run: run.bat repair
        exit /b 1
    )
)
echo   !OK! all packages present
if "!DM_TRACE!"=="1" "!PY!" -m datamind.trace

:: Commands that need nothing else.
if /i "!CMD!"=="keygen" "!PY!" -m datamind.keys & exit /b !errorlevel!
if /i "!CMD!"=="test"   "!PY!" -m pytest tests -q & exit /b !errorlevel!
if /i "!CMD!"=="repair" goto repair

:: ---------------------------------------------------------------- 4. Pre-flight
echo [4/4] Pre-flight
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo   !WARN! Created .env from .env.example. Fill in your Snowflake settings ^(run.bat keygen helps^), then run again.
    exit /b 1
)
set "FLAGS="
if /i "!CMD!"=="load" set "FLAGS=--no-llm"
if /i "!CMD!"=="live" set "FLAGS=--no-llm"
"!PY!" -m datamind.preflight !FLAGS!
set "PF=!errorlevel!"
if "!PF!"=="2" (
    echo   !WARN! Loading missing datasets into Snowflake ...
    "!PY!" load_data.py
    if errorlevel 1 (
        echo   !FAIL! Loading failed. See the messages above.
        exit /b 1
    )
    "!PY!" -m datamind.preflight !FLAGS!
    set "PF=!errorlevel!"
)
if not "!PF!"=="0" (
    echo.
    echo   !FAIL! Pre-flight did not pass. Fix the lines marked [FAIL] above and run run.bat again.
    exit /b 1
)
echo   !OK! ready
echo.

if /i "!CMD!"=="check" exit /b 0
if /i "!CMD!"=="load"  "!PY!" load_data.py & exit /b !errorlevel!
if /i "!CMD!"=="live"  "!PY!" live_check.py & exit /b !errorlevel!
if /i "!CMD!"=="smoke" "!PY!" -m eval.smoke & exit /b !errorlevel!
if /i "!CMD!"=="eval"  "!PY!" -m eval.run_eval %2 %3 %4 %5 %6 %7 %8 %9 & exit /b !errorlevel!
if /i "!CMD!"=="ask"   goto ask
if /i "!CMD!"=="serve" goto serve
echo   Unknown command: !CMD!
goto usage

:ask
if "%~2"=="" (
    echo   Usage: run.bat ask "your question"
    exit /b 1
)
"!PY!" -m datamind.cli %2 %3 %4 %5 %6 %7 %8 %9
exit /b !errorlevel!

:serve
set "PORT=8501"
for /f %%p in ('"!PY!" -m datamind.ports 8501') do set "PORT=%%p"
echo   DataMind is starting at http://localhost:!PORT!   ^(Ctrl+C to stop^)
echo.
if not defined DATAMIND_NO_BROWSER start "" /b cmd /c "ping 127.0.0.1 -n 5 >nul & start http://localhost:!PORT!"
"!PY!" -m streamlit run app.py --server.address 127.0.0.1 --server.port !PORT! --server.headless true --browser.gatherUsageStats false
exit /b !errorlevel!

:repair
echo   !WARN! Reinstalling all packages ...
"!PY!" -m pip install --upgrade --force-reinstall -r requirements.txt
exit /b !errorlevel!

:find_python
for %%C in (python py) do (
    if not defined PY (
        where %%C >nul 2>&1
        if not errorlevel 1 (
            %%C -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
            if not errorlevel 1 set "PY=%%C"
        )
    )
)
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" set "PY=%%D\python.exe"
)
exit /b 0

:usage
echo.
echo   Usage: run.bat [command]
echo.
echo     (none)   start the web app and open it in your browser
echo     check    run the pre-flight checks only
echo     ask      ask one question in the terminal:  run.bat ask "How many orders are there?"
echo     load     load the extra datasets into Snowflake
echo     live     prove the Snowflake layer works against your real account
echo     smoke    run the live routing cases against real Gemma and Snowflake
echo     eval     run the ground-truth evaluation ^(eval --truth-only checks the expected answers^)
echo     keygen   create a key pair and print the SQL that registers it in Snowflake
echo     test     run the automated tests
echo     repair   reinstall all packages
echo.
echo   Add --quiet to any command to hide the live trace (run.bat serve --quiet). Trace lines also go to logs\datamind.log.
echo.
echo   Self-healing: creates .venv, installs missing packages, creates .env,
echo   loads missing datasets, and picks a free port automatically.
exit /b 0
