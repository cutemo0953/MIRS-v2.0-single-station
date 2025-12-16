"""
Vercel Serverless Entry Point for MIRS
Medical Inventory Resilience System
"""
import sys
import os
from pathlib import Path

# Add project root to Python path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from main import app

# Vercel looks for 'app' variable
