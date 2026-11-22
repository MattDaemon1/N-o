@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

title NÉO — Assistant formateur IA local

echo ==================================================
echo   NÉO (Nouvel Équipier Opérationnel)
echo   Serveur local : http://127.0.0.1:7860
echo ==================================================
echo.

REM 1. Vérifier Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas détecté dans le PATH Windows.
    echo Installez Python 3.11+ depuis https://www.python.org/downloads/
    pause
    exit /b 1
)

python --version

REM 2. Vérifier / activer l'environnement virtuel .venv
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] Environnement virtuel .venv absent. Création en cours...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Impossible de créer l'environnement virtuel .venv.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERREUR] Échec de l'activation de .venv.
    pause
    exit /b 1
)

REM 3. Vérifier les dépendances sans lancer de téléchargement implicite de modèle
python scripts\check_env.py
if errorlevel 1 (
    echo.
    echo [ACTION REQUISE] Installez les paquets Python avec :
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo [OK] Lancement du dashboard local sur http://127.0.0.1:7860
echo [INFO] Appuyez sur Ctrl+C pour arrêter NÉO proprement.
echo.

python -m uvicorn app.main:app --host 127.0.0.1 --port 7860

if errorlevel 1 (
    echo.
    echo [ERREUR] Le serveur NÉO s'est arrêté de manière inattendue.
    pause
    exit /b 1
)

endlocal
