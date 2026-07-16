#!/bin/bash
# Double-click launcher for the AI DC Supply Chain Control Tower (macOS)
cd "$(dirname "$0")"

if ! python3 -c "import streamlit" 2>/dev/null; then
    echo "First run — installing dependencies…"
    pip3 install -r requirements.txt
fi

python3 -m streamlit run dashboard/Home.py
