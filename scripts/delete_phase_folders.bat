@echo off
:: Batch script to take ownership and remove locked .phase temp folders
:: Must be run as Administrator
cd /d "%~dp0\.."

echo Checking for elevated permissions...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script must be run as Administrator.
    echo Please right-click this file and select "Run as administrator".
    pause
    exit /b 1
)

echo Taking ownership and removing .phase temporary folders...
for %%D in (.phase-b-tmp .phase-c-tmp .phase-d-tmp .phase-e-tmp .phase-f-tmp) do (
    if exist "%%D" (
        echo Processing %%D...
        takeown /f "%%D" /r /d y >nul 2>&1
        icacls "%%D" /grant "%USERNAME%":F /t >nul 2>&1
        icacls "%%D" /grant administrators:F /t >nul 2>&1
        rd /s /q "%%D"
        if exist "%%D" (
            echo [WARN] Could not remove %%D.
        ) else (
            echo [SUCCESS] Removed %%D.
        )
    ) else (
        echo [INFO] %%D does not exist.
    )
)

echo.
echo Done! All existing .phase folders have been processed.
pause
