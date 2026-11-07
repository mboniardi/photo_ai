"""Test dell'impronta percettiva (pHash a 64 bit)."""
import io

import numpy as np
import pytest
from PIL import Image, ImageFilter

from services import impronta


def _foto_sintetica(w: int, h: int, seme: int = 0) -> Image.Image:
    """Rumore deterministico sfocato: il contenuto a basse frequenze e' stabile
    come in una foto vera (il rumore bianco puro non ne ha)."""
    rng = np.random.default_rng(seme)
    # Rumore a bassa risoluzione ingrandito in modo liscio, piu' un po' di grana.
    base = rng.integers(0, 256, size=(12, 16, 3), dtype=np.uint8)
    img = Image.fromarray(base, "RGB").resize((w, h), Image.BICUBIC)
    grana = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    img = Image.blend(img, Image.fromarray(grana, "RGB"), 0.1)
    return img.filter(ImageFilter.GaussianBlur(radius=max(w, h) / 400))


def test_calcola_restituisce_16_caratteri_esadecimali():
    h = impronta.calcola(_foto_sintetica(300, 200))
    assert len(h) == 16
    assert h == h.lower()
    int(h, 16)


def test_calcola_e_deterministica():
    assert impronta.calcola(_foto_sintetica(300, 200, 3)) == impronta.calcola(
        _foto_sintetica(300, 200, 3))


def test_stessa_immagine_a_risoluzioni_diverse_ha_distanza_minima():
    grande = _foto_sintetica(2000, 1500)
    piccola = grande.resize((500, 375))
    assert impronta.distanza(impronta.calcola(grande), impronta.calcola(piccola)) <= 4


def test_ricompressione_jpeg_aggressiva_non_cambia_l_impronta():
    orig = _foto_sintetica(1200, 900)
    buf = io.BytesIO()
    orig.save(buf, "JPEG", quality=40)
    buf.seek(0)
    assert impronta.distanza(impronta.calcola(orig),
                             impronta.calcola(Image.open(buf))) <= 6


def test_immagini_diverse_hanno_distanza_grande():
    assert impronta.distanza(impronta.calcola(_foto_sintetica(800, 600, seme=1)),
                             impronta.calcola(_foto_sintetica(800, 600, seme=2))) >= 15


def test_la_luminosita_globale_non_cambia_l_impronta():
    orig = _foto_sintetica(600, 400)
    piu_chiara = Image.eval(orig, lambda v: min(255, v + 40))
    assert impronta.distanza(impronta.calcola(orig), impronta.calcola(piu_chiara)) <= 6


def test_calcola_accetta_immagini_non_rgb():
    img = _foto_sintetica(300, 200)
    assert impronta.calcola(img.convert("L")) == impronta.calcola(img.convert("L"))
    assert len(impronta.calcola(img.convert("RGBA"))) == 16
    assert len(impronta.calcola(img.convert("P"))) == 16


def test_distanza_conta_i_bit_diversi():
    assert impronta.distanza("0" * 16, "0" * 16) == 0
    assert impronta.distanza("0" * 16, "f" * 16) == 64
    assert impronta.distanza("0000000000000000", "0000000000000007") == 3


@pytest.mark.parametrize("a,b", [
    ("abc", "0" * 16),
    ("0" * 16, "abc"),
    ("g" * 16, "0" * 16),
    ("0" * 17, "0" * 16),
])
def test_distanza_rifiuta_un_formato_sbagliato(a, b):
    with pytest.raises(ValueError):
        impronta.distanza(a, b)


def test_simili_ordina_per_distanza_crescente_e_filtra_per_soglia():
    base = "0" * 16
    candidate = [
        (10, "000000000000000f"),   # 4
        (11, "0000000000000000"),   # 0
        (12, "ffffffffffffffff"),   # 64, fuori soglia
        (13, "0000000000000003"),   # 2
        (14, "00000000000000ff"),   # 8, sulla soglia
    ]
    assert impronta.simili(base, candidate, 8) == [(11, 0), (13, 2), (10, 4), (14, 8)]


def test_simili_senza_candidate_o_senza_corrispondenze():
    assert impronta.simili("0" * 16, [], 8) == []
    assert impronta.simili("0" * 16, [(1, "f" * 16)], 8) == []


def test_simili_restituisce_int_python():
    (pid, d), = impronta.simili("0" * 16, [(7, "0000000000000001")], 4)
    assert type(pid) is int and type(d) is int


def test_simili_rifiuta_impronte_malformate():
    with pytest.raises(ValueError):
        impronta.simili("abc", [(1, "0" * 16)], 4)
    with pytest.raises(ValueError):
        impronta.simili("0" * 16, [(1, "xyz")], 4)
