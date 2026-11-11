import re

with open('web/src/types.ts', 'r') as f:
    content = f.read()

content = content.replace("season: number | null;", "season: number | null;\n  season_from: number | null;\n  season_to: number | null;")

with open('web/src/types.ts', 'w') as f:
    f.write(content)
