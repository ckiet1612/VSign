from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel, ConfigDict, StrictBool


class ModalGpuPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


def read_policy(path: Path) -> bool:
    try:
        state = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return True
    if state not in {"on", "off"}:
        raise ValueError("Invalid Modal GPU policy")
    return state == "on"


def write_policy(path: Path, enabled: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="ascii", dir=path.parent, prefix=f".{path.name}.", delete=False) as temp:
        staged = Path(temp.name)
        try:
            temp.write("on\n" if enabled else "off\n")
            temp.close()
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)
