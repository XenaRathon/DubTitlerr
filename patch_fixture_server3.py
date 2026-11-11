with open('web/tests/fixture_server.py', 'r') as f:
    content = f.read()

# Add json back exactly where it's needed
# It looks like the earlier patch messed up json import scope
content = "import json\n" + content

with open('web/tests/fixture_server.py', 'w') as f:
    f.write(content)
