import os
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/browse", tags=["browse"])


@router.get("")
def browse(path: str = "/"):
    real = os.path.realpath(path)
    if not os.path.exists(real) or not os.path.isdir(real):
        raise HTTPException(status_code=400, detail=f"Invalid path: {path}")
    parent = os.path.dirname(real)
    if real == "/":
        parent = "/"
    with os.scandir(real) as entries:
        dirs = sorted(
            [{"name": e.name, "path": e.path} for e in entries if e.is_dir() and not e.name.startswith(".")],
            key=lambda d: d["name"],
        )
    return {"path": real, "parent": parent, "dirs": dirs}
