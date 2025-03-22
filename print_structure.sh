#!/bin/bash

echo "Project Structure for Roomies:"
echo "============================"

find . -type d -not -path "*/node_modules/*" -not -path "*/venv/*" -not -path "*/__pycache__/*" -not -path "*/.git/*" -not -path "*/.next/*" -not -path "*/.vscode/*" | sort

echo ""
echo "Key Files:"
echo "========="
find . -type f -name "*.py" -o -name "*.tsx" -o -name "*.ts" -o -name "*.json" -o -name "*.md" | grep -v "node_modules" | grep -v "venv" | grep -v "__pycache__" | sort 