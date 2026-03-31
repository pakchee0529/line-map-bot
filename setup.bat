@echo off
cd /d %~dp0

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
) else (
    echo .venv already exists.
)

call .venv\Scripts\activate.bat

echo Upgrading pip...
python -m pip install --upgrade pip

echo Installing packages from requirements.txt...
pip install --upgrade -r requirements.txt

for /f "skip=1 delims=" %%i in ('certutil -hashfile requirements.txt MD5 ^| findstr /v /c:"CertUtil" /c:"MD5"') do (
    if not defined CURRENT_HASH set CURRENT_HASH=%%i
)
echo %CURRENT_HASH%>.requirements_hash

echo Setup finished.
pause