"""INV-PLT-11: external effects happen only in workers. The HTTP layer and command handlers must not import
provider clients (SMTP, S3, ClamAV, AI, messaging). Static scan, plus a negative control for the scanner."""

import ast
from pathlib import Path

from tests.conftest import API_ROOT

APP = API_ROOT / "app"

# Modules/packages that perform external effects. `app.core.mail` is the SMTP sender (P01 contract),
# `core.files.scanner` the ClamAV client, `notifications.channels` and `ai.providers` per REPO_LAYOUT.
PROVIDER_PREFIXES = (
    "smtplib",
    "aiosmtplib",
    "boto3",
    "botocore",
    "clamd",
    "twilio",
    "anthropic",
    "openai",
    "app.core.mail",
    "app.core.files.scanner",
    "app.notifications.channels",
    "app.ai.providers",
)


def api_layer_files(root: Path = APP) -> list[Path]:
    """HTTP layer + command handlers: app/api/**, **/router*.py, **/commands.py, app/core/commands/**."""
    found: set[Path] = set()
    found.update((root / "api").rglob("*.py"))
    found.update(root.rglob("router*.py"))
    found.update(root.rglob("commands.py"))
    found.update((root / "core" / "commands").rglob("*.py"))
    return sorted(p for p in found if p.is_file())


def forbidden_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    bad: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for name in names:
            if any(name == p or name.startswith(p + ".") for p in PROVIDER_PREFIXES):
                bad.append(name)
    return bad


def test_scanner_detects_a_provider_import(tmp_path: Path) -> None:
    sample = tmp_path / "router.py"
    sample.write_text("import smtplib\nfrom app.core.mail import send_email\n")
    assert forbidden_imports(sample) == ["smtplib", "app.core.mail", "app.core.mail.send_email"]


def test_api_layer_cannot_import_provider_clients() -> None:
    files = api_layer_files()
    assert any(p.parts[-2:] == ("api", "router.py") for p in files), "scan found no API layer"
    assert (APP / "core" / "mail.py").exists() or (APP / "core" / "mail").exists(), (
        "app.core.mail (the SMTP sender seam) must exist; see P01-test-contract.md"
    )
    offenders = {
        str(p.relative_to(APP)): forbidden_imports(p) for p in files if forbidden_imports(p)
    }
    assert offenders == {}
