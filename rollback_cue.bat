@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ============================================================
rem  rollback_cue.bat
rem  psxforge.py 의 cu2 보충 작업을 되돌리는 스크립트.
rem
rem  동작:
rem    1) output\ 안의 모든 *.cue.bak 을 찾는다.
rem    2) 같은 폴더, 같은 이름의 *.cu2 가 있으면 삭제한다.
rem    3) *.cue.bak 을 원래 이름 *.cue 로 되돌린다.
rem
rem  주의:
rem    - bin 파일은 건드리지 않습니다 (이름이 그대로였으므로).
rem    - .cue.bak 이 없는 폴더는 그대로 둡니다 (원래부터 정상이었거나
rem      cu2 보충 자체가 일어나지 않은 폴더).
rem
rem  사용법:
rem    rollback_cue.bat "Z:\game\Sony - PlayStation\roms\output"
rem    또는 output 폴더 안에 이 파일을 두고 더블클릭 실행
rem ============================================================

set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=%~dp0"

rem 끝에 붙은 백슬래시 제거
if "%TARGET:~-1%"=="\" set "TARGET=%TARGET:~0,-1%"

if not exist "%TARGET%" (
    echo [오류] 경로를 찾을 수 없습니다: "%TARGET%"
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo  CUE 롤백 스크립트
echo  대상 폴더 : "%TARGET%"
echo ============================================================
echo.
echo  이 폴더 안의 모든 *.cue.bak 파일을 찾아서:
echo    - 짝이 되는 *.cu2 파일을 삭제하고
echo    - *.cue.bak 을 *.cue 로 이름을 되돌립니다.
echo.
echo  bin 파일은 건드리지 않습니다.
echo.

rem ── 먼저 대상 목록만 보여주고 확인 받기 ──────────────────────
set /a COUNT=0
for /r "%TARGET%" %%F in (*.cue.bak) do (
    set /a COUNT+=1
    echo   [!COUNT!] %%F
)

if !COUNT! EQU 0 (
    echo  *.cue.bak 파일을 찾지 못했습니다. 되돌릴 항목이 없습니다.
    echo.
    pause
    exit /b 0
)

echo.
echo  총 !COUNT!개의 .cue.bak 파일을 찾았습니다.
echo.
set /p CONFIRM=계속해서 롤백을 진행할까요? (Y/N): 

if /i not "%CONFIRM%"=="Y" (
    echo  취소되었습니다.
    pause
    exit /b 0
)

echo.
echo ── 롤백 진행 중 ──────────────────────────────────────────
set /a DONE=0
set /a CU2_REMOVED=0

for /r "%TARGET%" %%F in (*.cue.bak) do (
    set "BAKFILE=%%F"
    set "CUEFILE=%%~dpnF"
    rem %%~dpnF 는 .bak을 뺀 경로+파일명 (즉 원래 .cue 경로와 동일)
    set "CU2FILE=!CUEFILE:~0,-4!.cu2"

    if exist "!CU2FILE!" (
        del /f /q "!CU2FILE!"
        echo   🗑  삭제: "!CU2FILE!"
        set /a CU2_REMOVED+=1
    )

    move /y "!BAKFILE!" "!CUEFILE!" >nul
    echo   ↩  복원: "!CUEFILE!"
    set /a DONE+=1
)

echo.
echo ============================================================
echo  완료: cue 복원 !DONE!개 / cu2 삭제 !CU2_REMOVED!개
echo ============================================================
echo.
echo  참고: MULTIDISC.LST 는 건드리지 않았습니다.
echo        (cu2 파일명이 적혀 있어 내용이 안 맞을 수 있습니다.
echo         psxforge.py 를 다시 실행하면 자동으로 다시 보충/생성됩니다.)
echo.
pause
