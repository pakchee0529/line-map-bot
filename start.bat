@echo off
cd /d %~dp0

if not exist .venv (
    echo .venv not found. Please run setup.bat first.
    pause
    exit /b
)

call .venv\Scripts\activate.bat

set HASH_FILE=.requirements_hash
set CURRENT_HASH=
set OLD_HASH=

for /f "skip=1 delims=" %%i in ('certutil -hashfile requirements.txt MD5 ^| findstr /v /c:"CertUtil" /c:"MD5"') do (
    if not defined CURRENT_HASH set CURRENT_HASH=%%i
)

if exist %HASH_FILE% (
    set /p OLD_HASH=<%HASH_FILE%
)

if not "%CURRENT_HASH%"=="%OLD_HASH%" (
    echo requirements.txt changed. Updating packages...
    python -m pip install --upgrade pip
    pip install --upgrade -r requirements.txt
    echo %CURRENT_HASH%>%HASH_FILE%
) else (
    echo requirements.txt unchanged. Skipping package install.
)

python app.py

pause