#!/usr/bin/env python
"""Convenience script to launch Team ZENITH decision runner.

Usage:
  python run_session.py --dry-run --mock-model
  python run_session.py --dry-run
  python run_session.py --live
"""

from __future__ import annotations

import sys
from zenith.main import main

if __name__ == "__main__":
    sys.exit(main())
