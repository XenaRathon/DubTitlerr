import re
with open('web/tests/fixture_server.py', 'r') as f:
    content = f.read()
# Add back import json at the very top (it was removed incorrectly by my patch)
if "import json" not in content[:300]:
    content = "import json\n" + content
with open('web/tests/fixture_server.py', 'w') as f:
    f.write(content)
