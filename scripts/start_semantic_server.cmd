@echo off
REM Resident semantic server with E5-large (high-accuracy model).
REM Model dir lives under the user profile (durable), not TEMP.
setlocal
set "ILANG_DISTILL_EMBED_MODEL=intfloat/multilingual-e5-large"
set "ILANG_DISTILL_MODEL_PATH=%USERPROFILE%\.ilang-models\e5-large"
set "ILANG_DISTILL_OFFLINE=1"
set "OMP_NUM_THREADS=1"
set "OPENBLAS_NUM_THREADS=1"
"%USERPROFILE%\.workbuddy-ai\binaries\python\versions\3.13.12\python.exe" "%~dp0ilang_semantic_server.py" --port 8766