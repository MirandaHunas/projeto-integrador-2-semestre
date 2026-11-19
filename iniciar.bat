@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  Monitoramento da Qualidade do Ar - Sala 09
echo ============================================================

if not exist ".env" (
    echo [ERRO] Arquivo .env nao encontrado nesta pasta.
    echo        Copie o .env.exemplo para .env e preencha antes de continuar.
    pause
    exit /b 1
)

echo.
echo [1/2] Instalando/conferindo dependencias...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [ERRO] Falha ao instalar as dependencias. Confira se o Python esta instalado.
    pause
    exit /b 1
)

echo.
echo [2/2] Iniciando: MQTT (caixinha) + MySQL + Open-Meteo + Gmail + Gemini + API
echo       API em http://localhost:8080/api/status
echo       Para parar: Ctrl+C
echo.
python app.py
pause
