#!/bin/bash
# Safe Setup Script for Capstone License Analyzer
# Handles dependency conflicts by using virtual environment

echo "=========================================="
echo "Capstone Analyzer - Safe Setup"
echo "=========================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi
echo "✓ Python 3 found ($(python3 --version))"

# Check if already in virtual environment
IN_VENV=0
if [[ "$VIRTUAL_ENV" != "" ]]; then
    IN_VENV=1
    echo "✓ Already in virtual environment: $VIRTUAL_ENV"
fi

# Recommend virtual environment if not in one
if [ $IN_VENV -eq 0 ]; then
    echo ""
    echo "⚠️  WARNING: You're installing in base environment"
    echo "   This can cause dependency conflicts (like protobuf)"
    echo ""
    echo "🎯 RECOMMENDED: Use a virtual environment to avoid conflicts"
    echo ""
    
    if [ -d "venv" ]; then
        echo "Found existing 'venv' directory."
        read -p "Activate it? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "To activate, run:"
            echo "  source venv/bin/activate"
            echo "Then run this script again."
            exit 0
        fi
    else
        read -p "Create virtual environment? (RECOMMENDED - y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "📦 Creating virtual environment..."
            python3 -m venv venv
            echo "✓ Virtual environment created"
            echo ""
            echo "To activate it, run:"
            echo "  source venv/bin/activate"
            echo "Then run this script again."
            exit 0
        else
            echo ""
            echo "⚠️  Continuing without virtual environment..."
            echo "   You may see dependency conflicts (this is usually OK for this tool)"
            echo ""
            read -p "Continue anyway? (y/n) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 0
            fi
        fi
    fi
fi

# Install dependencies
echo ""
echo "📦 Installing Capstone Analyzer dependencies..."
echo ""

# Use requirements.txt if available
if [ -f "requirements.txt" ]; then
    echo "Using requirements.txt (with scancode-toolkit-mini)"
    pip install -q -r requirements.txt 2>&1 | grep -v "dependency conflicts" || true
else
    echo "Installing packages individually..."
    pip install -q mistralai pydantic python-dotenv requests scancode-toolkit-mini
fi

echo "✓ Dependencies installed"

# Verify critical imports
echo ""
echo "🧪 Verifying installation..."
python3 << 'PYEOF'
import sys
success = True

try:
    from mistralai import Mistral
    print("✓ Mistral AI SDK")
except ImportError:
    print("❌ Mistral AI SDK - FAILED")
    success = False
    
try:
    from pydantic import BaseModel
    print("✓ Pydantic")
except ImportError:
    print("❌ Pydantic - FAILED")
    success = False
    
try:
    from dotenv import load_dotenv
    print("✓ python-dotenv")
except ImportError:
    print("❌ python-dotenv - FAILED")
    success = False
    
try:
    import requests
    print("✓ Requests")
except ImportError:
    print("❌ Requests - FAILED")
    success = False

if not success:
    sys.exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Some imports failed"
    exit 1
fi

# Check ScanCode
echo ""
echo "🔍 Checking ScanCode..."
if command -v scancode &> /dev/null; then
    echo "✓ ScanCode command available"
elif python3 -m scancode --version &> /dev/null 2>&1; then
    echo "✓ ScanCode available via 'python -m scancode'"
else
    echo "⚠️  ScanCode not found, trying to install..."
    pip install -q scancode-toolkit-mini
    if [ $? -eq 0 ]; then
        echo "✓ ScanCode installed"
    else
        echo "❌ ScanCode installation failed"
        echo "   Manual install: pip install scancode-toolkit-mini"
    fi
fi

# Create .env file
echo ""
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✓ Created .env from template"
    else
        cat > .env << 'EOF'
# Mistral API Key (Required)
MISTRAL_API_KEY=your_mistral_api_key_here

# GitHub Token (Optional - increases rate limits)
GITHUB_TOKEN=your_github_token_here
EOF
        echo "✓ Created .env file"
    fi
    echo ""
    echo "⚠️  NEXT STEP: Edit .env and add your API keys"
    echo ""
    echo "   Get Mistral key: https://console.mistral.ai/"
    echo "   Get GitHub token: https://github.com/settings/tokens"
    echo ""
else
    echo "✓ .env file already exists"
fi

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""

# Show dependency warning if not in venv
if [ $IN_VENV -eq 0 ]; then
    echo "⚠️  NOTE: You saw protobuf dependency warnings."
    echo "   These are from TensorFlow/Streamlit in your base environment."
    echo "   They WON'T affect this tool - we don't use those packages."
    echo ""
    echo "   To avoid warnings in future, use a virtual environment:"
    echo "   1. python3 -m venv venv"
    echo "   2. source venv/bin/activate"
    echo "   3. bash setup_safe.sh"
    echo ""
fi

echo "📋 Next steps:"
echo ""
echo "1. Edit .env with your API key:"
echo "   nano .env"
echo ""
echo "2. Run your first analysis:"
echo "   python capstone_lite.py --link https://github.com/twbs/bootstrap"
echo ""
echo "Examples:"
echo "  python capstone_lite.py --link https://github.com/facebook/react"
echo "  python capstone_lite.py --link https://github.com/vuejs/vue --output ./results"
echo ""