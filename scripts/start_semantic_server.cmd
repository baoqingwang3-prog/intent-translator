@echo off
REM Resident semantic server with a configurable interpreter and cached E5 model.
setlocal
if not defined ILANG_SEMANTIC_PYTHON set "ILANG_SEMANTIC_PYTHON=python"
if not defined ILANG_DISTILL_EMBED_MODEL set "ILANG_DISTILL_EMBED_MODEL=intfloat/multilingual-e5-large"
if not defined ILANG_DISTILL_MODEL_PATH set "ILANG_DISTILL_MODEL_PATH=%USERPROFILE%\.ilang-models\e5-large"
if not defined ILANG_DISTILL_OFFLINE set "ILANG_DISTILL_OFFLINE=1"
if not defined OMP_NUM_THREADS set "OMP_NUM_THREADS=1"
if not defined OPENBLAS_NUM_THREADS set "OPENBLAS_NUM_THREADS=1"
"%ILANG_SEMANTIC_PYTHON%" "%~dp0ilang_semantic_server.py" --port 8766 %*
