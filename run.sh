#!/usr/bin/env bash
# Return & Refund Chaser - 1-Click Launcher for macOS & Linux

set -e

echo "========================================================"
echo "  Return & Refund Chaser - 1-Click Launcher"
echo "========================================================"

# 1. Detect Python
if command -v python3 &>/dev/null; then
    PY_CMD="python3"
elif command -v python &>/dev/null; then
    PY_CMD="python"
else
    echo "[ERROR] Python is not installed. Please install Python 3.10+."
    exit 1
fi

echo "[OK] Found Python: $PY_CMD ($($PY_CMD --version))"

# 2. Virtual Environment
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtual environment (.venv)..."
    $PY_CMD -m venv .venv
fi

source .venv/bin/activate

# 3. Dependencies
echo "[INFO] Verifying dependencies from requirements.txt..."
pip install -q -r requirements.txt

# 4. Open default browser in background
(
    sleep 2
    if [[ "$OSTYPE" == "darwin"* ]]; then
        open "http://localhost:8000"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v xdg-open &>/dev/null; then
            xdg-open "http://localhost:8000"
        fi
    fi
) &

# 5. Start Server
echo "[INFO] Starting server at http://localhost:8000 ..."
python main.py --server
