# Ubicación: src/vista.py
# Vista de lectura con audio: una página HTML de un solo archivo (sin internet, sin librerías ni fuentes
# externas) que se abre en el navegador del computador. Muestra la transcripción, deja buscar texto y,
# al hacer clic en un párrafo, reproduce el audio desde ese punto.
# El texto del usuario nunca se pega en el HTML: viaja como JSON escapado y el DOM se arma con textContent.
import json
import logging
import webbrowser
from pathlib import Path
from typing import Optional

from src import historial
from utils.formatters import (
    fecha_en_espanol, formato_duracion, leer_parrafos_del_txt, nombre_de_archivo_seguro,
    participantes_en_orden,
)

logger = logging.getLogger(__name__)


def _nombre_base(txt: Path) -> str:
    """'2026-10-30 Reunión.blocks.txt' -> '2026-10-30 Reunión'."""
    return Path(txt).name.removesuffix(".txt").removesuffix(".blocks")


def _audio_existente(*candidatos) -> Optional[Path]:
    """El primer candidato que exista en disco, o None."""
    for candidato in candidatos:
        if candidato:
            try:
                if Path(candidato).is_file():
                    return Path(candidato)
            except OSError:
                continue
    return None


def datos_de_vista(txt: Path, json_path: Optional[Path] = None, audio: Optional[Path] = None) -> dict:
    """
    Reúne lo que muestra la página: titulo, fecha, duracion, participantes, parrafos y audio.
    Con .blocks.json se conocen los hablantes y el audio; sin él se lee el .txt (sin hablantes).
    audio es None si el archivo no existe en disco.
    """
    txt = Path(txt)
    audio_del_json = None
    if json_path:
        from src.procesador import leer_transcripcion
        from src.diarizer import aplicar_nombres
        datos = leer_transcripcion(Path(json_path))
        parrafos = aplicar_nombres(datos["parrafos"], datos["nombres"])
        titulo = datos["titulo"] or _nombre_base(txt)
        fecha = fecha_en_espanol(datos["fecha"]) if datos["fecha"] else None
        duracion = formato_duracion(datos["duracion"]) if datos["duracion"] is not None else None
        participantes = participantes_en_orden(parrafos)
        audio_del_json = datos["audio"]
    else:
        encabezado, parrafos = leer_parrafos_del_txt(txt)
        titulo = encabezado.get("titulo") or _nombre_base(txt)
        fecha = encabezado.get("fecha") or None
        duracion = encabezado.get("duracion") or None
        participantes = [n for n in encabezado.get("participantes", "").split(", ") if n]

    limpios = [{"start": float(p.get("start") or 0), "end": p.get("end"),
                "speaker": p.get("speaker"), "text": p.get("text", "")} for p in parrafos]

    elegido = _audio_existente(audio, audio_del_json)
    if elegido is None:
        from src.fragmentos import buscar_audio
        # buscar_audio parte del nombre del .json: se lo armamos a partir del .txt
        referencia = txt.with_name(_nombre_base(txt) + ".blocks.json")
        elegido = _audio_existente(buscar_audio(referencia, None))

    return {"titulo": titulo, "fecha": fecha, "duracion": duracion, "participantes": participantes,
            "parrafos": limpios, "audio": elegido}


def _json_seguro(valor) -> str:
    """JSON apto para ir dentro de <script>: '<', '>' y '&' escapados, así '</script>' no cierra la etiqueta."""
    texto = json.dumps(valor, ensure_ascii=False)
    # U+2028/2029 rompen literales en JS antiguo; JSON.parse los acepta escapados
    return (texto.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def generar_html(datos: dict, ir_a: Optional[float] = None) -> str:
    """Arma el HTML completo de la vista. ir_a: segundo al que se salta al abrir (sin reproducir)."""
    audio = datos.get("audio")
    para_json = {
        "titulo": datos.get("titulo") or "Transcripción",
        "fecha": datos.get("fecha"),
        "duracion": datos.get("duracion"),
        "participantes": datos.get("participantes") or [],
        "parrafos": datos.get("parrafos") or [],
        "audio": Path(audio).resolve().as_uri() if audio else None,
        "irA": ir_a,
    }
    titulo_html = (para_json["titulo"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (_PLANTILLA.replace("__TITULO__", titulo_html)
            .replace("__DATOS__", _json_seguro(para_json)))


def crear_vista(txt: Path, json_path: Optional[Path] = None, audio: Optional[Path] = None,
                ir_a: Optional[float] = None) -> Path:
    """Escribe la vista en <carpeta de datos>/vistas/<nombre>.html (se sobrescribe) y retorna su ruta."""
    datos = datos_de_vista(txt, json_path, audio)
    carpeta = historial.carpeta() / "vistas"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / (nombre_de_archivo_seguro(_nombre_base(txt)) + ".html")
    ruta.write_text(generar_html(datos, ir_a), encoding="utf-8")
    logger.info(f"Vista guardada en: {ruta}")
    return ruta


def abrir_en_navegador(ruta: Path) -> bool:
    """Abre la página en el navegador. Sin '#' en la URL: en algunos sistemas se pierde al abrir archivos."""
    try:
        return bool(webbrowser.open(Path(ruta).resolve().as_uri()))
    except Exception as e:
        logger.warning(f"No se pudo abrir el navegador: {e}")
        return False


_PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__</title>
<style>
:root {
  --fondo: #fbfaf7; --texto: #1f2328; --suave: #5f6670; --borde: #dcd8cf; --barra: #f1eee7;
  --actual: #fff1c2; --marca: #ffd84d; --marca-activa: #ff9f43; --enlace: #1f5fbf;
  --c0: #1f5fbf; --c1: #b4380f; --c2: #1a7f4b; --c3: #8a3fbf; --c4: #8a6a00; --c5: #0e7490;
}
@media (prefers-color-scheme: dark) {
  :root {
    --fondo: #16181c; --texto: #e6e3dc; --suave: #9aa1ab; --borde: #33373d; --barra: #1e2126;
    --actual: #3a3418; --marca: #6b5a10; --marca-activa: #b8650f; --enlace: #7fb0ff;
    --c0: #7fb0ff; --c1: #ff9b78; --c2: #6fd69b; --c3: #cfa0f5; --c4: #e6c453; --c5: #5fd0e8;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--fondo); color: var(--texto);
  font: 1.0625rem/1.65 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
#barra { position: sticky; top: 0; z-index: 5; background: var(--barra); border-bottom: 1px solid var(--borde);
  padding: .6rem 1rem; }
#barra .interior { max-width: 46rem; margin: 0 auto; display: flex; flex-direction: column; gap: .5rem; }
audio { width: 100%; }
.buscar { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.buscar input { flex: 1 1 14rem; font: inherit; font-size: 1rem; padding: .4rem .6rem; color: inherit;
  background: var(--fondo); border: 1px solid var(--borde); border-radius: .4rem; }
#cuenta { color: var(--suave); font-size: .9rem; min-height: 1.3em; }
main { max-width: 46rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
h1 { font-size: 1.6rem; line-height: 1.25; margin: 0 0 .3rem; }
#sub { color: var(--suave); margin: 0 0 1.2rem; }
#sin-audio { background: var(--barra); border: 1px solid var(--borde); border-radius: .4rem;
  padding: .5rem .8rem; margin: 0 0 1rem; color: var(--suave); }
.parrafo { padding: .55rem .75rem; margin: 0 -.75rem; border-radius: .5rem; }
.con-audio .parrafo { cursor: pointer; }
.con-audio .parrafo:hover { background: var(--barra); }
.parrafo.actual, .con-audio .parrafo.actual:hover { background: var(--actual); }
.meta { font-size: .85rem; color: var(--suave); margin-bottom: .1rem; }
.minuto { font-variant-numeric: tabular-nums; color: var(--enlace); margin-right: .5rem; }
.hablante { font-weight: 600; }
.texto { overflow-wrap: anywhere; }
mark { background: var(--marca); color: inherit; border-radius: .15rem; padding: 0 .05rem; }
mark.activa { background: var(--marca-activa); }
@media (max-width: 30rem) { body { font-size: 1rem; } h1 { font-size: 1.35rem; } }
</style>
</head>
<body>
<div id="barra"><div class="interior">
  <audio id="reproductor" controls preload="metadata" hidden></audio>
  <div class="buscar">
    <input id="buscador" type="search" placeholder="Buscar en la transcripción" aria-label="Buscar en la transcripción" autocomplete="off">
    <span id="cuenta" aria-live="polite"></span>
  </div>
</div></div>
<main>
  <h1 id="titulo"></h1>
  <p id="sub"></p>
  <p id="sin-audio" hidden>No encontré el audio de esta transcripción; puedes leerla igual.</p>
  <div id="parrafos"></div>
</main>
<script type="application/json" id="datos">__DATOS__</script>
<script>
(function () {
  "use strict";
  var datos = JSON.parse(document.getElementById("datos").textContent);
  var reproductor = document.getElementById("reproductor");
  var buscador = document.getElementById("buscador");
  var cuenta = document.getElementById("cuenta");
  var contenedor = document.getElementById("parrafos");
  var hayAudio = !!datos.audio;

  document.getElementById("titulo").textContent = datos.titulo;
  var partes = [datos.fecha, datos.duracion, (datos.participantes || []).join(", ")].filter(Boolean);
  document.getElementById("sub").textContent = partes.join(" · ");
  if (!partes.length) document.getElementById("sub").hidden = true;

  if (hayAudio) {
    reproductor.src = datos.audio;
    reproductor.hidden = false;
    document.body.classList.add("con-audio");
  } else {
    document.getElementById("sin-audio").hidden = false;
  }

  function dos(n) { return (n < 10 ? "0" : "") + n; }
  function hora(s) {
    s = Math.max(0, Math.round(s));
    return "[" + dos(Math.floor(s / 3600)) + ":" + dos(Math.floor(s % 3600 / 60)) + ":" + dos(s % 60) + "]";
  }

  // Un color por hablante, por orden de aparición
  var colores = {};
  function colorDe(h) {
    if (!(h in colores)) colores[h] = Object.keys(colores).length % 6;
    return "var(--c" + colores[h] + ")";
  }

  var parrafos = datos.parrafos;
  var nodos = parrafos.map(function (p, i) {
    var caja = document.createElement("div");
    caja.className = "parrafo";
    var meta = document.createElement("div");
    meta.className = "meta";
    var minuto = document.createElement("span");
    minuto.className = "minuto";
    minuto.textContent = hora(p.start);
    meta.appendChild(minuto);
    if (p.speaker) {
      var h = document.createElement("span");
      h.className = "hablante";
      h.style.color = colorDe(p.speaker);
      h.textContent = p.speaker;
      meta.appendChild(h);
    }
    var texto = document.createElement("div");
    texto.className = "texto";
    texto.textContent = p.text;
    caja.appendChild(meta);
    caja.appendChild(texto);
    caja.addEventListener("click", function () {
      if (!hayAudio || (window.getSelection && String(window.getSelection()))) return;
      reproductor.currentTime = p.start;
      reproductor.play().catch(function () {});
    });
    contenedor.appendChild(caja);
    return { caja: caja, texto: texto, original: p.text };
  });

  // --- Párrafo que está sonando ---
  var actual = -1;
  function indiceEn(segundo) {
    var r = -1;
    for (var i = 0; i < parrafos.length; i++) { if (parrafos[i].start <= segundo) r = i; else break; }
    return r;
  }
  function marcarActual(i, desplazar) {
    if (i === actual) return;
    if (actual >= 0) nodos[actual].caja.classList.remove("actual");
    actual = i;
    if (i >= 0) {
      nodos[i].caja.classList.add("actual");
      if (desplazar) nodos[i].caja.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }
  if (hayAudio) {
    reproductor.addEventListener("timeupdate", function () { marcarActual(indiceEn(reproductor.currentTime), false); });
  }

  // --- Búsqueda sin distinguir mayúsculas ni tildes ---
  // Se normaliza carácter a carácter para que las posiciones coincidan con el texto original
  function normal(c) { return c.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
  function normalizarConMapa(texto) {
    var salida = "", mapa = [];
    for (var i = 0; i < texto.length; i++) {
      var n = normal(texto[i]);
      for (var k = 0; k < n.length; k++) { salida += n[k]; mapa.push(i); }
    }
    return { texto: salida, mapa: mapa };
  }
  var marcas = [], posicion = -1;

  function limpiarMarcas() {
    nodos.forEach(function (n) { if (n.texto.childNodes.length !== 1 || n.texto.firstChild.nodeType !== 3) n.texto.textContent = n.original; });
    marcas = []; posicion = -1;
  }
  function buscar() {
    limpiarMarcas();
    var q = normalizarConMapa(buscador.value.trim()).texto;
    if (!q) { cuenta.textContent = ""; return; }
    nodos.forEach(function (n) {
      var t = normalizarConMapa(n.original);
      var desde = 0, rangos = [], i;
      while ((i = t.texto.indexOf(q, desde)) !== -1) {
        rangos.push([t.mapa[i], t.mapa[i + q.length - 1] + 1]);
        desde = i + q.length;
      }
      if (!rangos.length) return;
      var frag = document.createDocumentFragment(), fin = 0;
      rangos.forEach(function (r) {
        var ini = Math.max(r[0], fin);
        if (ini > fin) frag.appendChild(document.createTextNode(n.original.slice(fin, ini)));
        var m = document.createElement("mark");
        m.textContent = n.original.slice(ini, r[1]);
        frag.appendChild(m);
        marcas.push(m);
        fin = r[1];
      });
      if (fin < n.original.length) frag.appendChild(document.createTextNode(n.original.slice(fin)));
      n.texto.textContent = "";
      n.texto.appendChild(frag);
    });
    cuenta.textContent = marcas.length ? marcas.length + (marcas.length === 1 ? " coincidencia" : " coincidencias") : "Sin coincidencias";
  }
  function saltar(paso) {
    if (!marcas.length) return;
    if (posicion >= 0) marcas[posicion].classList.remove("activa");
    posicion = (posicion + paso + marcas.length) % marcas.length;
    marcas[posicion].classList.add("activa");
    marcas[posicion].scrollIntoView({ behavior: "smooth", block: "center" });
  }
  buscador.addEventListener("input", buscar);
  buscador.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); saltar(e.shiftKey ? -1 : 1); }
  });

  // --- Barra espaciadora: pausa o reanuda (si el foco no está escribiendo) ---
  document.addEventListener("keydown", function (e) {
    if (!hayAudio || (e.key !== " " && e.code !== "Space")) return;
    var f = document.activeElement, tag = f && f.tagName;
    if (f === buscador || tag === "INPUT" || tag === "TEXTAREA" || tag === "BUTTON" || tag === "AUDIO") return;
    e.preventDefault();
    if (reproductor.paused) reproductor.play().catch(function () {}); else reproductor.pause();
  });

  // --- Posición inicial: sin reproducir ---
  if (typeof datos.irA === "number" && parrafos.length) {
    var i0 = Math.max(0, indiceEn(datos.irA));
    marcarActual(i0, false);
    nodos[i0].caja.scrollIntoView({ block: "center" });
    if (hayAudio) {
      var poner = function () { try { reproductor.currentTime = datos.irA; } catch (e) {} };
      if (reproductor.readyState >= 1) poner(); else reproductor.addEventListener("loadedmetadata", poner, { once: true });
    }
  }
})();
</script>
</body>
</html>
"""
