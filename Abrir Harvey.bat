@echo off
rem Dois cliques para abrir o painel do Harvey no navegador.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Primeira vez: instalando o Harvey. Isso leva alguns minutos...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo Nao encontrei o Python. Instale o Python 3.11 ou mais novo em https://www.python.org/downloads/
    echo e marque a opcao "Add python.exe to PATH". Depois abra este arquivo de novo.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -e .
)

echo Abrindo o painel em http://127.0.0.1:5555 ...
echo Deixe esta janela aberta enquanto usa o Harvey. Para fechar, feche esta janela.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5555/"
".venv\Scripts\harvey.exe" dashboard
pause
