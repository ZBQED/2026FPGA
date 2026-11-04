from pathlib import Path
import json,re
root=Path(__file__).resolve().parents[1]
standard={'README.md','SKILL.md','LICENSE','NOTICE','COPYING','CMakeLists.txt','Makefile'}
names=[line.split('  ',1)[1]for line in(root/'files.sha256').read_text('ascii').splitlines()]+['files.sha256']
bad=[name for name in names if any(part not in standard and(part!=part.lower()or not re.fullmatch(r'[a-z0-9_.+-]+',part))for part in Path(name).parts)]
assert not bad,bad
print(json.dumps(dict(status='PASS',files=len(names),path_policy='lowercase_ascii',standard_tool_names=sorted(standard))))
