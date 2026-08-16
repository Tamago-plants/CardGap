import sys
from pathlib import Path

# cardgap/ プロジェクトルートを import パスに追加(どこから pytest を実行しても通るように)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
