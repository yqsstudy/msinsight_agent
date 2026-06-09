"""测试配置"""

import pytest
import sys
import os

# Add project root to path so tests can import the package as `src.*`.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
