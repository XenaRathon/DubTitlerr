with open('web/tests/fixture_server.py', 'r') as f:
    content = f.read()

# Make sure `json` is available inside `do_POST`
# Currently it's throwing UnboundLocalError
content = content.replace("            def do_POST(self):", "            def do_POST(self):\n                import json\n")

with open('web/tests/fixture_server.py', 'w') as f:
    f.write(content)
