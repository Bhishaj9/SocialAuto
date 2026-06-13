@echo off
echo [DEMO ORCHESTRATOR] Initializing visible presentation mode...

:: Step 1: Launch the API Server in a separate visible window
echo [DEMO ORCHESTRATOR] Spawning Visible API Server Gateway (Port 8000)...
start "AutoBVB API Server Gateway" cmd /k "set AUTOBVB_MOCK_PIPELINE=False && set PYTHONIOENCODING=utf-8 && .\venv\Scripts\uvicorn api:app --port 8000 --host 127.0.0.1"

:: Wait 4 seconds for the server socket to bind cleanly to localhost
timeout /t 4 /nobreak

:: Step 2: Launch the Playwright Facebook Worker Node in a separate visible window
echo [DEMO ORCHESTRATOR] Spawning Visible Multi-Tenant Post Muscle...
start "AutoBVB Multi-Tenant Post Muscle" cmd /k "set WORKER_HEADLESS=False && set SHADOW_MODE=True && set AUTOBVB_MOCK_WORKER=False && set PYTHONIOENCODING=utf-8 && .\venv\Scripts\python worker.py"

:: Wait 2 seconds for the worker queue polling loop to safely initialize
timeout /t 2 /nobreak

:: Step 3: Launch the interactive presentation browser automation script in this console window
echo [DEMO ORCHESTRATOR] Launching presentation browser driver...
.\venv\Scripts\python run_presentation.py

echo [DEMO ORCHESTRATOR] Live presentation sequence completed.
pause
