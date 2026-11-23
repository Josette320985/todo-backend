from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parents[1] / "app" / "services"


def test_services_do_not_reference_fastapi() -> None:
    offenders: list[str] = [
        str(path.relative_to(SERVICES_DIR.parents[1]))
        for path in SERVICES_DIR.rglob("*.py")
        if "fastapi" in path.read_text(encoding="utf-8").lower()
    ]
    assert not offenders, (
        "app/services must stay independent of FastAPI: " + ", ".join(offenders)
    )
