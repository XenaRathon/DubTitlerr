"""Put the repo root on sys.path so tests can `import reflow`, `import ordering`, etc.
regardless of pytest's import mode / invocation directory."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
