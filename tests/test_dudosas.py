# Ubicación: tests/test_dudosas.py
# Pruebas de src/dudosas.py: buscar frases de hablante dudoso, moverlas, marcarlas como bien y guardar.
import copy
import json
from datetime import date

from src.dudosas import Dudosa, buscar_dudosas, guardar, marcar_bien, mover_frase, nombre_visible
from utils.formatters import cargar_transcripcion, guardar_json


def _p(start, end, texto, hablante, **extra):
    return {"start": start, "end": end, "text": texto, "speaker": hablante, **extra}


def _marca(start, end, texto, otro, motivo):
    return {"start": start, "end": end, "text": texto, "otro": otro, "motivo": motivo}


def test_nombre_visible():
    assert nombre_visible("Hablante 1", {"Hablante 1": "Ana"}) == "Ana"
    assert nombre_visible("Hablante 2", {"Hablante 1": "Ana"}) == "Hablante 2"
    assert nombre_visible("Hablante 2", {}) == "Hablante 2"


def test_buscar_ordena_por_motivo_y_tiempo_y_corta_en_el_maximo():
    parrafos = [
        _p(0, 10, "Texto largo uno. Sí.", "Hablante 1", dudosas=[_marca(9, 10, "Sí.", "Hablante 2", "borde")]),
        _p(10, 20, "Otra cosa dicha aquí. Mira esto.", "Hablante 2",
           dudosas=[_marca(18, 20, "Mira esto.", "Hablante 1", "repartida")]),
        _p(20, 30, "Algo más largo. Claro.", "Hablante 1",
           dudosas=[_marca(21, 22, "Algo más largo.", "Hablante 2", "fuera_de_turno")]),
    ]
    dudosas = buscar_dudosas(parrafos)
    assert [d.motivo for d in dudosas] == ["repartida", "fuera_de_turno", "borde"]
    assert dudosas[0] == Dudosa(1, 18, 20, "Mira esto.", "Hablante 2", "Hablante 1", "repartida")
    assert len(buscar_dudosas(parrafos, maximo=2)) == 2


def test_buscar_ignora_marcas_cuyo_texto_ya_no_esta_o_con_el_mismo_hablante():
    parrafos = [
        _p(0, 5, "Texto nuevo sin la frase.", "Hablante 1", dudosas=[_marca(1, 2, "Frase vieja.", "Hablante 2", "borde")]),
        _p(5, 9, "Hola amigos.", "Hablante 1", dudosas=[_marca(5, 9, "Hola amigos.", "Hablante 1", "borde")]),
    ]
    assert buscar_dudosas(parrafos) == []


def test_buscar_detecta_entre_otro_en_json_antiguos_sin_duplicar():
    parrafos = [
        _p(0, 10, "Una explicación larga de lo que pasó.", "Hablante 1"),
        _p(10, 11, "Sí claro.", "Hablante 2"),
        _p(11, 20, "Y seguimos con lo demás de la semana.", "Hablante 1"),
        _p(20, 21, "Ajá.", "Hablante 2", revisado=True),
        _p(21, 30, "Continúo con otro tema largo.", "Hablante 1"),
    ]
    dudosas = buscar_dudosas(parrafos)
    assert [(d.indice, d.motivo, d.actual, d.otro) for d in dudosas] == [(1, "entre_otro", "Hablante 2", "Hablante 1")]
    # Si el párrafo ya tenía una marca, no se agrega otra vez
    parrafos[1]["dudosas"] = [_marca(10, 11, "Sí claro.", "Hablante 1", "borde")]
    dudosas = buscar_dudosas(parrafos)
    assert len(dudosas) == 1 and dudosas[0].motivo == "borde"


def test_buscar_omite_dudas_entre_dos_etiquetas_con_el_mismo_nombre():
    # «Es la misma persona que…» deja dos etiquetas con el mismo nombre: no se pregunta «¿Ana o Ana?»
    parrafos = [
        _p(0, 10, "Texto largo uno. Sí.", "Hablante 1", dudosas=[_marca(9, 10, "Sí.", "Hablante 3", "borde")]),
        _p(10, 20, "Otra cosa dicha aquí. Mira esto.", "Hablante 2",
           dudosas=[_marca(18, 20, "Mira esto.", "Hablante 1", "repartida")]),
    ]
    nombres = {"Hablante 1": "Ana", "Hablante 2": "Luis", "Hablante 3": "Ana"}
    assert [d.texto for d in buscar_dudosas(parrafos, nombres=nombres)] == ["Mira esto."]
    assert len(buscar_dudosas(parrafos)) == 2


def test_mover_frase_que_es_todo_el_parrafo_y_se_une_a_los_vecinos():
    parrafos = [
        _p(0, 10, "Largo uno.", "Hablante 1"),
        _p(10, 11, "Sí claro.", "Hablante 2", dudosas=[_marca(10, 11, "Sí claro.", "Hablante 1", "borde")]),
        _p(11, 20, "Largo dos.", "Hablante 1"),
    ]
    original = copy.deepcopy(parrafos)
    d = buscar_dudosas(parrafos)[0]
    nuevos = mover_frase(parrafos, d, "Hablante 1")
    assert parrafos == original
    assert nuevos == [_p(0, 20, "Largo uno. Sí claro. Largo dos.", "Hablante 1")]


def test_mover_frase_sin_vecino_del_hablante_nuevo_solo_cambia_el_hablante():
    parrafos = [_p(0, 5, "Hola.", "Hablante 1"), _p(5, 6, "Sí.", "Hablante 2"), _p(6, 9, "Chao.", "Hablante 3")]
    d = Dudosa(1, 5, 6, "Sí.", "Hablante 2", "Hablante 4", "borde")
    assert mover_frase(parrafos, d, "Hablante 4")[1] == _p(5, 6, "Sí.", "Hablante 4", revisado=True)


def test_mover_frase_al_inicio_se_une_al_parrafo_anterior():
    parrafos = [
        _p(0, 10, "Pregunta larga.", "Hablante 1"),
        _p(10, 30, "Sí. Y entonces yo opino otra cosa.", "Hablante 2",
           dudosas=[_marca(10, 11, "Sí.", "Hablante 1", "borde")]),
    ]
    d = buscar_dudosas(parrafos)[0]
    nuevos = mover_frase(parrafos, d, "Hablante 1")
    assert nuevos == [
        _p(0, 11, "Pregunta larga. Sí.", "Hablante 1"),
        _p(11, 30, "Y entonces yo opino otra cosa.", "Hablante 2"),
    ]


def test_mover_frase_al_inicio_sin_vecino_la_deja_en_su_propio_parrafo():
    parrafos = [_p(0, 30, "Sí. Y entonces yo opino otra cosa.", "Hablante 2")]
    d = Dudosa(0, 0, 1, "Sí.", "Hablante 2", "Hablante 1", "borde")
    assert mover_frase(parrafos, d, "Hablante 1") == [
        _p(0, 1, "Sí.", "Hablante 1", revisado=True), _p(1, 30, "Y entonces yo opino otra cosa.", "Hablante 2")]


def test_mover_frase_al_final_se_une_al_parrafo_siguiente():
    parrafos = [
        _p(0, 30, "Yo opino esto. Y tú qué dices.", "Hablante 1"),
        _p(30, 40, "Pues yo creo que no.", "Hablante 2"),
    ]
    d = Dudosa(0, 28, 30, "Y tú qué dices.", "Hablante 1", "Hablante 2", "borde")
    assert mover_frase(parrafos, d, "Hablante 2") == [
        _p(0, 28, "Yo opino esto.", "Hablante 1"),
        _p(28, 40, "Y tú qué dices. Pues yo creo que no.", "Hablante 2"),
    ]


def test_mover_frase_en_medio_parte_en_tres_y_reparte_las_otras_marcas():
    parrafos = [_p(0, 30, "Uno dos. Está en medio. Tres cuatro.", "Hablante 1", dudosas=[
        _marca(0, 5, "Uno dos.", "Hablante 2", "borde"),
        _marca(10, 20, "Está en medio.", "Hablante 2", "repartida"),
        _marca(25, 30, "Tres cuatro.", "Hablante 3", "borde"),
    ])]
    d = Dudosa(0, 10, 20, "Está en medio.", "Hablante 1", "Hablante 2", "repartida")
    nuevos = mover_frase(parrafos, d, "Hablante 2")
    assert nuevos == [
        _p(0, 10, "Uno dos.", "Hablante 1", dudosas=[_marca(0, 5, "Uno dos.", "Hablante 2", "borde")]),
        _p(10, 20, "Está en medio.", "Hablante 2", revisado=True),
        _p(20, 30, "Tres cuatro.", "Hablante 1", dudosas=[_marca(25, 30, "Tres cuatro.", "Hablante 3", "borde")]),
    ]


def test_mover_frase_no_parte_una_palabra_que_contiene_la_frase():
    # «no.» está dentro de «Bueno.»: antes se partía ahí y quedaba «Bue» / «no.» / «no.»
    parrafos = [
        _p(0, 5, "Bueno. no.", "Hablante 1", dudosas=[_marca(4, 5, "no.", "Hablante 2", "borde")]),
        _p(6, 9, "Sí, claro.", "Hablante 2"),
    ]
    d = buscar_dudosas(parrafos)[0]
    assert mover_frase(parrafos, d, "Hablante 2") == [
        _p(0, 4, "Bueno.", "Hablante 1"),
        _p(4, 9, "no. Sí, claro.", "Hablante 2"),
    ]


def test_buscar_ignora_una_marca_que_solo_calza_dentro_de_otra_palabra():
    parrafos = [_p(0, 5, "Bueno, bueno.", "Hablante 1", dudosas=[_marca(4, 5, "no.", "Hablante 2", "borde")])]
    assert buscar_dudosas(parrafos) == []


def test_mover_frase_repetida_mueve_la_de_su_minuto():
    parrafos = [_p(0, 30, "Sí. Hablamos de muchas cosas importantes hoy. Sí.", "Hablante 1")]
    d = Dudosa(0, 29, 30, "Sí.", "Hablante 1", "Hablante 2", "borde")
    assert mover_frase(parrafos, d, "Hablante 2") == [
        _p(0, 29, "Sí. Hablamos de muchas cosas importantes hoy.", "Hablante 1"),
        _p(29, 30, "Sí.", "Hablante 2", revisado=True),
    ]


def test_mover_frase_no_junta_los_parrafos_posteriores_separados_por_pausas():
    parrafos = [
        _p(0, 2, "Hola a todos los presentes hoy.", "Hablante 1"),
        _p(2, 30, "Primer párrafo.", "Hablante 2"),
        _p(35, 60, "Segundo párrafo tras una pausa.", "Hablante 2"),
        _p(65, 90, "Tercero tras otra pausa.", "Hablante 2"),
    ]
    d = Dudosa(0, 0, 2, "Hola a todos los presentes hoy.", "Hablante 1", "Hablante 2", "borde")
    assert mover_frase(parrafos, d, "Hablante 2") == [
        _p(0, 30, "Hola a todos los presentes hoy. Primer párrafo.", "Hablante 2"),
        _p(35, 60, "Segundo párrafo tras una pausa.", "Hablante 2"),
        _p(65, 90, "Tercero tras otra pausa.", "Hablante 2"),
    ]


def test_una_frase_movida_no_se_vuelve_a_proponer():
    # Al partir el párrafo, la frase movida queda corta y entre dos trozos de la otra persona:
    # sin «revisado» se proponía de nuevo como «entre_otro» (devolverla adonde estaba)
    parrafos = [_p(0, 10, "Esto es largo y sigue. Yo creo que sí. Y después sigue más.", "Hablante 1",
                   dudosas=[_marca(4, 6, "Yo creo que sí.", "Hablante 2", "repartida")])]
    d = buscar_dudosas(parrafos)[0]
    nuevos = mover_frase(parrafos, d, "Hablante 2")
    assert [p["speaker"] for p in nuevos] == ["Hablante 1", "Hablante 2", "Hablante 1"]
    assert buscar_dudosas(nuevos) == []


def test_mover_frase_con_texto_ausente_o_mismo_hablante_no_cambia_nada():
    parrafos = [_p(0, 5, "Hola.", "Hablante 1")]
    assert mover_frase(parrafos, Dudosa(0, 0, 1, "Otra.", "Hablante 1", "Hablante 2", "borde"), "Hablante 2") == parrafos
    assert mover_frase(parrafos, Dudosa(0, 0, 1, "Hola.", "Hablante 1", "Hablante 2", "borde"), "Hablante 1") == parrafos
    assert mover_frase(parrafos, Dudosa(9, 0, 1, "Hola.", "Hablante 1", "Hablante 2", "borde"), "Hablante 2") == parrafos


def test_marcar_bien_quita_la_marca_y_no_se_vuelve_a_proponer():
    parrafos = [_p(0, 10, "Largo aquí. Sí.", "Hablante 1", dudosas=[_marca(9, 10, "Sí.", "Hablante 2", "borde")])]
    d = buscar_dudosas(parrafos)[0]
    nuevos = marcar_bien(parrafos, d)
    assert "dudosas" in parrafos[0]
    assert "dudosas" not in nuevos[0]
    assert buscar_dudosas(nuevos) == []


def test_marcar_bien_entre_otro_guarda_revisado():
    parrafos = [_p(0, 10, "Largo uno.", "Hablante 1"), _p(10, 11, "Sí.", "Hablante 2"), _p(11, 20, "Largo dos.", "Hablante 1")]
    d = buscar_dudosas(parrafos)[0]
    nuevos = marcar_bien(parrafos, d)
    assert nuevos[1]["revisado"] is True and "revisado" not in parrafos[1]
    assert buscar_dudosas(nuevos) == []


def _json_de_ejemplo(tmp_path, con_titulo):
    ruta = tmp_path / "reunion.blocks.json"
    parrafos = [_p(0, 10, "Hola a todos.", "Hablante 1"), _p(10, 12, "Sí.", "Hablante 2")]
    datos = dict(audio=tmp_path / "reunion.wav", nombres={"Hablante 1": "Ana"}, huellas={"Hablante 1": [0.5, 0.5]})
    if con_titulo:
        datos.update(titulo="Mi reunión", fecha=date(2026, 3, 4), duracion=125.0)
    guardar_json(parrafos, ruta, **datos)
    return ruta


def test_guardar_conserva_las_claves_y_rehace_el_txt_sin_titulo(tmp_path):
    ruta = _json_de_ejemplo(tmp_path, con_titulo=False)
    nuevos = [_p(0, 12, "Hola a todos. Sí.", "Hablante 1")]
    txt, parrafos = guardar(ruta, nuevos)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["parrafos"] == nuevos
    assert datos["nombres"] == {"Hablante 1": "Ana"}
    assert datos["huellas"] == {"Hablante 1": [0.5, 0.5]}
    assert datos["audio"] == str(tmp_path / "reunion.wav")
    assert "titulo" not in datos
    assert txt == tmp_path / "reunion.blocks.txt"
    assert txt.read_text(encoding="utf-8").strip() == "[00:00:00] Ana: Hola a todos. Sí."
    assert parrafos[0]["speaker"] == "Ana"


def test_guardar_con_titulo_conserva_titulo_fecha_duracion_y_encabezado(tmp_path):
    ruta = _json_de_ejemplo(tmp_path, con_titulo=True)
    txt, _ = guardar(ruta, [_p(0, 12, "Hola a todos. Sí.", "Hablante 1")])
    datos = cargar_transcripcion(ruta)
    assert (datos["titulo"], datos["fecha"], datos["duracion"]) == ("Mi reunión", date(2026, 3, 4), 125.0)
    assert txt.read_text(encoding="utf-8").startswith("# Mi reunión")
