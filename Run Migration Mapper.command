#!/bin/bash
# Double-click this file to launch Migration Mapper.
# First run sets up a private Python environment and installs dependencies;
# later runs start almost instantly.

set -e
cd "$(dirname "$0")"

PYTHON_BIN=""
for candidate in python3.11 python3.12 python3.13 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "Python 3 was not found on this Mac."
    echo "Install it from https://www.python.org/downloads/ and try again."
    read -p "Press Enter to close this window..."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Setting up Migration Mapper for the first time (this can take a minute)..."
    "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate

# Skip Streamlit's first-run "welcome email" prompt, which would otherwise
# block this window waiting for input.
mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
    printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

echo "Checking dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "Starting Migration Mapper... your browser will open automatically."
streamlit run app.py

read -p "Migration Mapper has stopped. Press Enter to close this window..."
