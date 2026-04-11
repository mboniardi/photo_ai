"""Route /api/export — esporta selezione foto come ZIP in-memory."""
import io
import zipfile
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database.photos import get_photo_by_id
import config

router = APIRouter(prefix="/api/export", tags=["export"])


class ExportRequest(BaseModel):
    photo_ids: list[int]


@router.post("/zip")
def export_zip(req: ExportRequest):
    if not req.photo_ids:
        raise HTTPException(status_code=400, detail="Nessuna foto selezionata")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"foto_selezione_{timestamp}.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for photo_id in req.photo_ids:
            photo = get_photo_by_id(config.LOCAL_DB, photo_id)
            if photo is None:
                continue
            try:
                with open(photo["file_path"], "rb") as f:
                    zf.writestr(photo["filename"], f.read())
            except OSError:
                continue
    buf.seek(0)

    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )
