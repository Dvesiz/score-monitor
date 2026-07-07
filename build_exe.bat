@echo off
chcp 65001 >nul
echo ========================================
echo     成绩监控 - 打包为 EXE
echo ========================================
echo.

REM 安装 PyInstaller（如未安装）
pip install pyinstaller

echo.
echo 正在打包，请耐心等待（约 1-3 分钟）…
echo.

pyinstaller --onefile --console --name "成绩监控" ^
    --hidden-import=httpx ^
    --hidden-import=playwright.async_api ^
    --hidden-import=bs4 ^
    --hidden-import=lxml ^
    --collect-all ddddocr ^
    --add-data "config.json;." ^
    --icon NONE ^
    score_monitor.py

echo.
if %ERRORLEVEL% equ 0 (
    echo ========================================
    echo 打包成功！
    echo 输出文件: dist\成绩监控.exe
    echo ========================================
    echo.
    echo 使用方法：
    echo   1. 编辑 config.json 填入学号、密码
    echo   2. 双击 成绩监控.exe 运行
    echo.
    echo 命令行参数：
    echo   成绩监控.exe --once             只检查一次
    echo   成绩监控.exe --visible          显示浏览器窗口
    echo   成绩监控.exe --interval 10      每10分钟检查一次
    echo   成绩监控.exe --student-id ...   指定学号（覆盖config.json）
    echo.
    pause
) else (
    echo 打包失败，请检查错误信息。
    pause
)
