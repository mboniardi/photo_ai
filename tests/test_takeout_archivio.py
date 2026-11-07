"""Test della lettura di un archivio Google Takeout."""
import json
import os
import zipfile

import pytest

from services.takeout_archivio import leggi, scompatta


def _voce(contenuto, nome):
    return next(v for v in contenuto.voci if v.nome == nome)


def test_legge_coordinate_e_istante_dal_json(fixture_takeout):
    v = _voce(leggi(fixture_takeout), "IMG_1.jpg")
    assert v.latitudine == pytest.approx(45.4642)
    assert v.longitudine == pytest.approx(9.19)
    assert v.scattata_il == "2023-11-14T22:13:20"
    assert v.album == os.path.join("Google Foto", "Vacanza")
    assert os.path.isfile(v.percorso_file)


def test_convenzione_vecchia_dei_nomi_dei_sidecar(fixture_takeout):
    """IMG_2.jpg.json (senza .supplemental-metadata) viene letto lo stesso."""
    v = _voce(leggi(fixture_takeout), "IMG_2.jpg")
    assert v.scattata_il == "2023-11-14T22:13:20"


def test_sidecar_dal_nome_troncato(fixture_takeout):
    """Takeout accorcia i nomi lunghi: .supplemental-metad.json."""
    d = os.path.join(fixture_takeout, "Google Foto", "Vacanza")
    os.rename(os.path.join(d, "IMG_1.jpg.supplemental-metadata.json"),
              os.path.join(d, "IMG_1.jpg.supplemental-metad.json"))
    assert _voce(leggi(fixture_takeout), "IMG_1.jpg").latitudine == pytest.approx(45.4642)


def test_coordinate_a_zero_valgono_assenti(fixture_takeout):
    voce = _voce(leggi(fixture_takeout), "IMG_2.jpg")
    assert voce.latitudine is None and voce.longitudine is None


def test_i_video_sono_saltati_e_contati(fixture_takeout):
    contenuto = leggi(fixture_takeout)
    assert contenuto.video_saltati == 1
    assert all(not v.nome.endswith(".mp4") for v in contenuto.voci)


def test_del_gemello_edited_si_tiene_la_versione_modificata(fixture_takeout):
    contenuto = leggi(fixture_takeout)
    assert [v.nome for v in contenuto.voci if v.nome.startswith("IMG_9")] == ["IMG_9-edited.jpg"]
    assert contenuto.gemelli_scartati == 2  # IMG_9 e IMG_8


def test_del_gemello_modificato_italiano_si_tiene_la_versione_modificata(fixture_takeout):
    contenuto = leggi(fixture_takeout)
    assert [v.nome for v in contenuto.voci if v.nome.startswith("IMG_8")] == ["IMG_8-modificato.jpg"]
    assert _voce(contenuto, "IMG_8-modificato.jpg").latitudine == pytest.approx(43.7)


def test_i_suffissi_si_leggono_da_config_a_ogni_chiamata(fixture_takeout, monkeypatch):
    import config
    monkeypatch.setattr(config, "TAKEOUT_SUFFISSI_MODIFICATO", ["-edited"])
    contenuto = leggi(fixture_takeout)
    assert contenuto.gemelli_scartati == 1
    assert "IMG_8.jpg" in [v.nome for v in contenuto.voci]


def test_la_versione_edited_eredita_il_json_dell_originale(fixture_takeout):
    v = _voce(leggi(fixture_takeout), "IMG_9-edited.jpg")
    assert v.latitudine == pytest.approx(41.9)


def test_json_mancante_la_voce_entra_senza_coordinate(fixture_takeout):
    v = _voce(leggi(fixture_takeout), "IMG_4.jpg")
    assert v.latitudine is None and v.longitudine is None and v.scattata_il is None


def test_json_malformato_viene_contato_e_non_solleva(fixture_takeout):
    contenuto = leggi(fixture_takeout)
    v = _voce(contenuto, "IMG_3.jpg")
    assert v.latitudine is None and v.scattata_il is None
    # IMG_3 (troncato) e IMG_4 (assente)
    assert contenuto.json_illeggibili == 2


def test_il_json_d_album_non_e_una_foto(fixture_takeout):
    assert not any(v.nome.endswith(".json") for v in leggi(fixture_takeout).voci)


def test_conta_delle_voci(fixture_takeout):
    nomi = sorted(v.nome for v in leggi(fixture_takeout).voci)
    assert nomi == ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg", "IMG_4.jpg",
                    "IMG_8-modificato.jpg", "IMG_9-edited.jpg"]


@pytest.mark.parametrize("photo_taken", [
    None, {}, "boh", {"timestamp": "non-un-numero"}, {"timestamp": None},
    {"timestamp": "99999999999999999999"}, {"timestamp": ["1"]},
])
def test_istante_assente_o_di_forma_diversa_non_solleva(fixture_takeout, photo_taken):
    d = os.path.join(fixture_takeout, "Google Foto", "Vacanza")
    dati = {"title": "IMG_1.jpg", "geoData": {"latitude": 1.5, "longitude": 2.5}}
    if photo_taken is not None:
        dati["photoTakenTime"] = photo_taken
    with open(os.path.join(d, "IMG_1.jpg.supplemental-metadata.json"), "w") as fh:
        json.dump(dati, fh)
    v = _voce(leggi(fixture_takeout), "IMG_1.jpg")
    assert v.scattata_il is None
    assert v.latitudine == 1.5


def test_geodata_di_forma_diversa_non_solleva(fixture_takeout):
    d = os.path.join(fixture_takeout, "Google Foto", "Vacanza")
    with open(os.path.join(d, "IMG_1.jpg.supplemental-metadata.json"), "w") as fh:
        json.dump({"geoData": "boh"}, fh)
    v = _voce(leggi(fixture_takeout), "IMG_1.jpg")
    assert v.latitudine is None


def test_json_che_non_e_un_oggetto_conta_come_illeggibile(fixture_takeout):
    d = os.path.join(fixture_takeout, "Google Foto", "Vacanza")
    with open(os.path.join(d, "IMG_1.jpg.supplemental-metadata.json"), "w") as fh:
        fh.write("[1, 2]")
    contenuto = leggi(fixture_takeout)
    assert _voce(contenuto, "IMG_1.jpg").latitudine is None
    assert contenuto.json_illeggibili == 3


def _zip(percorso, voci):
    with zipfile.ZipFile(percorso, "w") as z:
        for nome, dati in voci.items():
            z.writestr(nome, dati)
    return str(percorso)


def test_scompatta_estrae_piu_zip_nella_stessa_destinazione(tmp_path):
    z1 = _zip(tmp_path / "a.zip", {"Takeout/Album/a.jpg": b"a"})
    z2 = _zip(tmp_path / "b.zip", {"Takeout/Album/b.jpg": b"b"})
    dest = tmp_path / "out"
    assert scompatta([z1, z2], str(dest)) == str(dest)
    assert (dest / "Takeout/Album/a.jpg").read_bytes() == b"a"
    assert (dest / "Takeout/Album/b.jpg").read_bytes() == b"b"


def test_scompatta_rifiuta_un_percorso_che_esce_dalla_destinazione(tmp_path):
    zip_malevolo = _zip(tmp_path / "m.zip", {"ok.txt": b"x", "../evaso.txt": b"x"})
    dest = tmp_path / "out"
    with pytest.raises(ValueError):
        scompatta([zip_malevolo], str(dest))
    assert not (tmp_path / "evaso.txt").exists()
    # niente viene scritto prima del rifiuto, nemmeno la voce innocua
    assert not (dest / "ok.txt").exists()


def test_scompatta_rifiuta_un_percorso_assoluto(tmp_path):
    bersaglio = tmp_path / "assoluto.txt"
    zip_malevolo = _zip(tmp_path / "m.zip", {str(bersaglio): b"x"})
    with pytest.raises(ValueError):
        scompatta([zip_malevolo], str(tmp_path / "out"))
    assert not bersaglio.exists()


def test_scompatta_rifiuta_di_scrivere_attraverso_un_symlink(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    fuori = tmp_path / "fuori"
    fuori.mkdir()
    os.symlink(str(fuori), str(dest / "link"))
    zip_malevolo = _zip(tmp_path / "m.zip", {"link/evaso.txt": b"x"})
    with pytest.raises(ValueError):
        scompatta([zip_malevolo], str(dest))
    assert not (fuori / "evaso.txt").exists()
