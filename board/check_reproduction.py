"""Check source-release integrity and report target prerequisites separately."""
from pathlib import Path
import sys,json
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'build'))
from verify_package import main
from check_external_assets import check
main()
print(json.dumps(dict(source_release='READY',target_inputs=check('runtime'),hardware_sources=check('hardware')),ensure_ascii=False,indent=2))
