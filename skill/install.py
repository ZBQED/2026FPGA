"""Install the verified skill without changing global Python."""
import importlib.util
from pathlib import Path


def main(argv=None):
    bundle = Path(__file__).resolve().parent
    source = bundle / "pynq-evidence-audit" / "scripts" / "install_skill.py"
    spec = importlib.util.spec_from_file_location("pynq_skill_installer", source)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    return installer.main(argv, bundle=bundle)


if __name__ == "__main__":
    raise SystemExit(main())
