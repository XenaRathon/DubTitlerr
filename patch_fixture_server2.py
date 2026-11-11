import re

with open('web/tests/fixture_server.py', 'r') as f:
    content = f.read()

old_fixture_reqs = '''                    import json
                    from datetime import datetime, timezone
                    import uuid'''

new_fixture_reqs = ""

content = content.replace(old_fixture_reqs, new_fixture_reqs)

# add import json at top if not there
if "import json" not in content[:300]:
    content = "import json\n" + content

# we need datetime, timezone, uuid globally
content = content.replace('import time', 'import time\nimport uuid\nfrom datetime import datetime, timezone')

with open('web/tests/fixture_server.py', 'w') as f:
    f.write(content)
