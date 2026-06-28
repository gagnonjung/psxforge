@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ============================================================
rem  remove_cu2.bat
rem  지정된 게임 폴더 목록에서 *.cu2 파일만 삭제합니다.
rem  (psxforge.py 를 다시 돌려서 새로 생성하기 위한 사전 작업)
rem
rem  bin/cue/bmp 등 다른 파일은 전혀 건드리지 않습니다.
rem
rem  사용법:
rem    remove_cu2.bat "Z:\game\Sony - PlayStation\roms\output"
rem    또는 output 폴더 안에 이 파일을 두고 더블클릭 실행
rem ============================================================

set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=%~dp0"
if "%TARGET:~-1%"=="\" set "TARGET=%TARGET:~0,-1%"

if not exist "%TARGET%" (
    echo [오류] 경로를 찾을 수 없습니다: "%TARGET%"
    echo.
    pause
    exit /b 1
)

rem ── 대상 폴더 목록 ──────────────────────────────────────────
set "FOLDERS[0]=Aconcagua (Japan) (2 Discs)"
set "FOLDERS[1]=Arc the Lad III (Japan) (2 Discs) (Rev 1)"
set "FOLDERS[2]=BioHazard 2 - Dual Shock Ver. (Korea) (2 Discs)"
set "FOLDERS[3]=Chase the Express (Japan, Asia) (2 Discs)"
set "FOLDERS[4]=Countdown Vampires (Japan) (2 Discs)"
set "FOLDERS[5]=Final Fantasy IX (Korea) (4 Discs)"
set "FOLDERS[6]=Final Fantasy VII International (Korea) (3 Discs)"
set "FOLDERS[7]=Final Fantasy VIII (Japan, Asia) (4 Discs)"
set "FOLDERS[8]=Kowloon's Gate - Kowloon Fuusuiden (Japan) (4 Discs)"
set "FOLDERS[9]=Metal Gear Solid - Integral (Japan, Asia) (En,Ja) (2 Discs)"
set "FOLDERS[10]=Mobile Suit Z-Gundam (2 Discs) (Japan)"
set "FOLDERS[11]=Parasite Eve (Korea) (2 Discs)"
set "FOLDERS[12]=Parasite Eve II (Japan, Asia) (2 Discs)"
set "FOLDERS[13]=Policenauts (Japan) (2 Discs)"
set "FOLDERS[14]=Soukaigi (Japan) (3 Discs)"
set "FOLDERS[15]=Star Ocean - The Second Story (Japan) (2 Discs) (Rev 1)"
set "FOLDERS[16]=Valkyrie Profile (Japan) (2 Discs) (Rev 1)"
set "FOLDERS[17]=Valkyrie Profile (Korea) (2 Discs) (Rev 1)"
set "FOLDERS[18]=Wangan Trial (2 Discs) (Japan)"
set "FOLDERS[19]=Xenogears (Japan) (2 Discs)"
set "FOLDERS[20]=Xenogears (Korea) (2 Discs)"
set "FOLDERS[21]=Yarudora Series Vol. 1 - Double Cast (Korea)"
set "FOLDERS[22]=Yarudora Series Vol. 2 - Kisetsu o Dakishimete (Korea)"
set "FOLDERS[23]=Yarudora Series Vol. 3 - Sampaguita (Korea)"
set "FOLDER_COUNT=24"

echo ============================================================
echo  CU2 삭제 스크립트
echo  대상 폴더 : "%TARGET%"
echo ============================================================
echo.
echo  아래 !FOLDER_COUNT!개 게임 폴더 안의 *.cu2 파일만 삭제합니다.
echo  (bin/cue/bmp 등은 건드리지 않습니다)
echo.

set /a IDX=0
:list_loop
if !IDX! GEQ %FOLDER_COUNT% goto list_done
echo   [!IDX!] !FOLDERS[%IDX%]!
set /a IDX+=1
goto list_loop
:list_done

echo.
set /p CONFIRM=계속해서 삭제를 진행할까요? (Y/N): 

if /i not "%CONFIRM%"=="Y" (
    echo  취소되었습니다.
    pause
    exit /b 0
)

echo.
echo ── 삭제 진행 중 ──────────────────────────────────────────
set /a TOTAL_DELETED=0
set /a FOLDER_NOT_FOUND=0

set /a IDX=0
:proc_loop
if !IDX! GEQ %FOLDER_COUNT% goto proc_done

set "GAMEDIR=%TARGET%\!FOLDERS[%IDX%]!"

if not exist "!GAMEDIR!" (
    echo   ⚠ 폴더 없음, 건너뜀: "!FOLDERS[%IDX%]!"
    set /a FOLDER_NOT_FOUND+=1
    set /a IDX+=1
    goto proc_loop
)

set /a FOUND=0
for %%F in ("!GAMEDIR!\*.cu2") do (
    if exist "%%F" (
        del /f /q "%%F"
        echo   🗑  삭제: "%%F"
        set /a FOUND+=1
        set /a TOTAL_DELETED+=1
    )
)

if !FOUND! EQU 0 (
    echo   ⏭  cu2 없음: "!FOLDERS[%IDX%]!"
)

set /a IDX+=1
goto proc_loop
:proc_done

echo.
echo ============================================================
echo  완료: cu2 삭제 !TOTAL_DELETED!개 / 폴더 없음 !FOLDER_NOT_FOUND!개
echo ============================================================
echo.
echo  참고: bin/cue 파일은 그대로 남아있습니다.
echo        psxforge.py 를 다시 실행하면 필요한 게임(CDDA 포함)만
echo        cu2가 새로 생성됩니다.
echo.
pause
