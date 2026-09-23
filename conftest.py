"""Put the repo root and tools/ on sys.path so tests can `import reflow`, `import
ordering`, `import sns_extract`, etc. regardless of pytest's import mode / invocation
directory."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
