# Ubicación: src/menu.py
# Menú con flechas que se abre al escribir `transcriptor` sin nada más.
# Aquí solo se hacen preguntas: el trabajo lo hacen los mismos comandos de src/cli.py.
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import questionary
import typer
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from src import ajustes, cli, historial, plataforma
from src.diarizer import parsear_nombres
from utils.validators import es_url

consola = cli.consola

# Los mismos colores que las barras de progreso
ESTILO = questionary.Style([
    ("qmark", "fg:#f92672 bold"),
    ("question", "bold"),
    ("answer", "fg:#ff9d00"),
    ("pointer", "fg:#ff9d00 bold"),
    ("highlighted", "fg:#ff9d00 bold"),
    ("selected", "fg:#ff9d00"),
    ("instruction", "fg:#858585"),
    ("text", ""),
])

MODELOS_WHISPER = [
    ("turbo", "rápido y casi tan preciso como large (recomendado)"),
    ("large", "el más preciso, el más lento"),
    ("medium", "equilibrado"),
    ("small", "rápido, para pruebas"),
    ("base", "muy rápido, menos preciso"),
    ("tiny", "el más rápido, el menos preciso"),
]

MODELOS_IA = [
    ("qwen3-8b", "equilibrado (recomendado)"),
    ("qwen3-4b", "más rápido"),
    ("gemma4-e4b", "alternativa rápida"),
]

IDIOMAS = [
    ("Español", "es"), ("Inglés", "en"), ("Portugués", "pt"), ("Francés", "fr"),
    ("Italiano", "it"), ("Alemán", "de"), ("Catalán", "ca"),
]

NO_LO_SE = "No lo sé"
CUANTOS = [NO_LO_SE, "2", "3", "4", "5 o más"]

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# Cuántas transcripciones se ofrecen en las listas (las más recientes)
MAX_EN_LISTA = 15

INSTALAR_DIARIZACION = 'uv pip install -e ".[diarizacion]"'
INSTALAR_CORRECCION = 'uv pip install -e ".[correccion]"'

NOMBRE_MOSTRAR_EN_CARPETA = {"darwin": "Mostrar en Finder", "win32": "Mostrar en el Explorador"}


# --- Preguntas --------------------------------------------------------------
# "← Volver" (o Esc) lanza Atras: quien pregunta vuelve al paso anterior.
# Ctrl+C sube como KeyboardInterrupt y vuelve al menú principal.

class Atras(Exception):
    """Se eligió "← Volver" o se apretó Esc."""


VOLVER = "← Volver"
_ATRAS = object()  # lo que responde una pregunta cuando se vuelve atrás


def _preguntar(pregunta, volver: bool):
    if volver:
        teclas = KeyBindings()

        @teclas.add("escape", eager=True)
        def _volver(evento):
            evento.app.exit(result=_ATRAS)

        app = pregunta.application
        app.key_bindings = merge_key_bindings([app.key_bindings, teclas]) if app.key_bindings else teclas
        # Esc responde al momento (sin esperar a ver si es el comienzo de otra tecla)
        app.ttimeoutlen = 0.05
    respuesta = pregunta.unsafe_ask()
    if respuesta is _ATRAS:
        raise Atras
    return respuesta


def elegir(mensaje: str, opciones: list, defecto=None, volver: bool = True):
    """
    Lista para elegir con flechas. Cada opción es un texto o una tupla (texto, valor).
    Con volver, termina con "← Volver" (y Esc hace lo mismo).
    """
    choices = [questionary.Choice(o[0], o[1]) if isinstance(o, tuple) else questionary.Choice(o, o)
               for o in opciones]
    # questionary falla si el valor por defecto no está entre las opciones (p. ej. una preferencia antigua)
    if defecto is not None and defecto not in [c.value for c in choices]:
        defecto = None
    if volver:
        choices.append(questionary.Choice(VOLVER, _ATRAS))
    return _preguntar(questionary.select(mensaje, choices, default=defecto, qmark="?", pointer="❯",
                                         instruction=" ", style=ESTILO), volver)


def si_no(mensaje: str, defecto: bool = True, volver: bool = True) -> bool:
    return elegir(mensaje, [("Sí", True), ("No", False)], defecto, volver)


def texto(mensaje: str, validar=None, defecto: str = "", volver: bool = True) -> str:
    return _preguntar(questionary.text(_con_pista(mensaje, volver), default=defecto, validate=validar,
                                       qmark="?", style=ESTILO), volver)


def ruta(mensaje: str, validar=None, solo_carpetas: bool = False, defecto: str = "", volver: bool = True) -> str:
    return _preguntar(questionary.path(_con_pista(mensaje, volver), default=defecto, validate=validar,
                                       only_directories=solo_carpetas, qmark="?", style=ESTILO), volver)


def _con_pista(mensaje: str, volver: bool) -> str:
    """En las preguntas para escribir no hay lista: avisamos de Esc en el propio mensaje."""
    if not volver:
        return mensaje
    if mensaje.endswith("):"):
        return mensaje[:-2] + ", Esc para volver):"
    return mensaje.rstrip(":") + " (Esc para volver):"


def seguir_pasos(pasos: list):
    """
    Hace las preguntas de un flujo en orden. Si en una se vuelve atrás, repite la anterior que
    se hizo de verdad (un paso que retorna False se saltó su pregunta). Volver atrás en la primera
    lanza Atras, para que quien llama vuelva a su propia pregunta anterior.
    """
    hechos, i = [], 0
    while i < len(pasos):
        try:
            pregunto = pasos[i]()
        except Atras:
            if not hechos:
                raise
            i = hechos.pop()
            continue
        if pregunto is not False:
            hechos.append(i)
        i += 1


# --- Menú principal ---------------------------------------------------------

def iniciar():
    """Muestra el menú hasta que eliges Salir (o Ctrl+C en el menú principal)."""
    cli._configurar_logs(detalle=False)
    consola.print("\n 🎙️  [bold]Transcriptor Pro[/]")
    consola.print(" [dim]↑ ↓ para moverte · Enter para elegir · Esc o ← Volver para regresar[/]\n")

    acciones = {
        "transcribir": flujo_transcribir,
        "corregir": flujo_corregir,
        "nombres": flujo_nombres,
        "mis": flujo_mis_transcripciones,
        "configuracion": flujo_configuracion,
    }
    while True:
        try:
            accion = elegir("¿Qué quieres hacer?", [
                ("Transcribir audio o video", "transcribir"),
                ("Corregir una transcripción", "corregir"),
                ("Cambiar nombres de hablantes", "nombres"),
                ("Mis transcripciones", "mis"),
                ("Configuración", "configuracion"),
                ("Salir", "salir"),
            ], volver=False)
        except (KeyboardInterrupt, EOFError):
            accion = "salir"
        if accion == "salir":
            consola.print("[dim]Hasta luego.[/]")
            return

        try:
            seguir = acciones[accion]()
        except Atras:
            seguir = True
        except (KeyboardInterrupt, EOFError):
            consola.print("\n[dim]Volviendo al menú.[/]")
            seguir = True
        if seguir is False:
            consola.print("[dim]Hasta luego.[/]")
            return
        consola.print()


# --- Transcribir ------------------------------------------------------------

def flujo_transcribir():
    prefs = historial.preferencias()
    instalado_hablantes, instalado_ia = _instalado("pyannote.audio"), _instalado("mlx_lm")
    modo_hablantes, modo_correccion = ajustes.valor("modo_hablantes"), ajustes.valor("modo_correccion")
    if not instalado_hablantes and modo_hablantes != ajustes.NUNCA:
        consola.print(f"[dim]{escape(_falta_diarizacion('Para identificar hablantes, instala: '))}[/]")

    # Las respuestas: al volver atrás, cada pregunta ofrece lo que ya se había respondido.
    # Idioma, carpeta y vocabulario (para la corrección) salen de Configuración;
    # "Más opciones…" los cambia solo para esta vez.
    r = {"origen": prefs.get("origen"), "archivo": "", "enlace": "", "modelo": ajustes.valor("modelo"),
         "hablantes": False, "cuantos": None, "corregir": False,
         "idioma": ajustes.valor("idioma"), "salida": ajustes.carpeta("carpeta_salida"),
         "vocabulario": ajustes.valor("vocabulario")}

    def origen():
        r["origen"] = elegir("¿De dónde viene?", [
            ("Un archivo de mi Mac", "archivo"),
            ("Un enlace (YouTube u otro)", "enlace"),
        ], r["origen"])

    def entrada():
        if r["origen"] == "archivo":
            r["archivo"] = ruta("Arrastra el archivo aquí o escribe su ruta (Tab completa):",
                                validar=_validar_archivo, defecto=r["archivo"])
        else:
            r["enlace"] = texto("Pega el enlace:", validar=_validar_enlace, defecto=r["enlace"]).strip()

    def modelo():
        r["modelo"] = elegir("¿Qué modelo uso?", _opciones_con_descripcion(MODELOS_WHISPER, ajustes.valor("modelo")),
                             r["modelo"])

    # Con "siempre" o "nunca" en Configuración, estas preguntas no se hacen
    def hablantes():
        if not instalado_hablantes or modo_hablantes != ajustes.PREGUNTAR:
            r["hablantes"] = instalado_hablantes and modo_hablantes == ajustes.SIEMPRE
            return False
        r["hablantes"] = si_no("¿Identifico quién habla?", r.get("hablantes_dicho", prefs.get("hablantes", True)))
        r["hablantes_dicho"] = r["hablantes"]

    def cuantos():
        if not r["hablantes"]:
            r["cuantos"] = None
            return False
        r["cuantos"] = elegir("¿Cuántas personas hablan?", CUANTOS, r["cuantos"] or prefs.get("cuantos", NO_LO_SE))

    def corregir():
        if not instalado_ia or modo_correccion != ajustes.PREGUNTAR:
            r["corregir"] = instalado_ia and modo_correccion == ajustes.SIEMPRE
            return False
        r["corregir"] = si_no("¿Corrijo el texto con IA al terminar?", r.get("corregir_dicho", prefs.get("corregir", False)))
        r["corregir_dicho"] = r["corregir"]

    def empezar():
        while True:
            consola.print(_resumen_transcribir(_entrada(r), r["modelo"], r["hablantes"], r["cuantos"],
                                               r["corregir"], r["idioma"], r["salida"],
                                               r["vocabulario"] if r["corregir"] else ""))
            decision = elegir("¿Empiezo?", [
                ("Sí, empezar", "empezar"),
                ("Más opciones… (idioma, vocabulario, carpeta donde guardar)" if r["corregir"]
                 else "Más opciones… (idioma, carpeta donde guardar)", "mas"),
                ("Cancelar", "cancelar"),
            ])
            if decision != "mas":
                r["decision"] = decision
                return
            vocabulario = r["vocabulario"] if r["corregir"] else None  # sin corregir no sirve
            r["idioma"], r["salida"], vocabulario = _mas_opciones(r["idioma"], r["salida"], vocabulario)
            if vocabulario is not None:
                r["vocabulario"] = vocabulario

    seguir_pasos([origen, entrada, modelo, hablantes, cuantos, corregir, empezar])
    if r["decision"] == "cancelar":
        return True

    # Lo que se respondió queda como respuesta por defecto la próxima vez (el modelo, también en
    # Configuración). Si la pregunta no se hizo, se conserva la respuesta anterior.
    recordar = {"origen": r["origen"], "modelo": r["modelo"], "cuantos": r["cuantos"] or prefs.get("cuantos")}
    if "hablantes_dicho" in r:
        recordar["hablantes"] = r["hablantes"]
    if "corregir_dicho" in r:
        recordar["corregir"] = r["corregir"]
    historial.guardar_preferencias(**recordar)

    num, minimo = numero_de_hablantes(r["cuantos"])
    resultado = _ejecutar(cli.ejecutar_transcripcion, entrada=_entrada(r), modelo=r["modelo"],
                          hablantes=r["hablantes"], num=num, minimo=minimo, idioma=r["idioma"], salida=r["salida"],
                          carpeta_descargas=ajustes.carpeta("carpeta_descargas"))
    if resultado is None:
        return True

    if r["corregir"]:
        _ejecutar(cli.corregir, archivo=resultado.json_path or resultado.txt_path,
                  modelo=ajustes.valor("modelo_corrector"), vocabulario=r["vocabulario"])
    return acciones_sobre(resultado.txt_path, resultado.json_path, "¿Y ahora?")


def _entrada(r: dict) -> str:
    """Lo que se va a transcribir: la ruta del archivo (limpia) o el enlace."""
    return str(limpiar_ruta(r["archivo"])) if r["origen"] == "archivo" else r["enlace"]


def numero_de_hablantes(cuantos: Optional[str]) -> tuple:
    """'3' -> (3, None): exactamente 3. '5 o más' -> (None, 5): al menos 5. 'No lo sé' -> (None, None)."""
    if not cuantos or cuantos == NO_LO_SE:
        return None, None
    numero = int(cuantos.split()[0])
    return (None, numero) if "más" in cuantos else (numero, None)


def _resumen_transcribir(entrada, modelo, hablantes, cuantos, corregir, idioma, salida, vocabulario="") -> Text:
    nombre = entrada if es_url(entrada) else Path(entrada).name
    resumen = Text("\nVoy a transcribir ")
    resumen.append(nombre, style="bold")
    resumen.append(" con ")
    resumen.append(modelo, style="cyan")
    if idioma != "es":
        resumen.append(f", en {_nombre_idioma(idioma).lower()}")
    if hablantes:
        if cuantos and cuantos != NO_LO_SE:
            resumen.append(f", identificando {cuantos} hablantes")
        else:
            resumen.append(", identificando quién habla")
    resumen.append(", y luego corregir" if corregir else "")
    resumen.append(".")
    if vocabulario:
        resumen.append(f" Vocabulario para corregir: {vocabulario}.")
    if salida:
        resumen.append(f" Lo guardo en {corta(salida)}.")
    return resumen


def _mas_opciones(idioma: str, salida: Optional[Path], vocabulario: Optional[str] = None) -> tuple:
    """
    Idioma, carpeta de salida y vocabulario para esta transcripción. "← Volver" regresa a ¿Empiezo?.
    El vocabulario solo sirve para corregir: con vocabulario=None no se ofrece.
    """
    while True:
        opciones = [(f"Idioma: {_nombre_idioma(idioma)}", "idioma")]
        if vocabulario is not None:
            opciones.append((f"Vocabulario para corregir: {_texto_vocabulario(vocabulario)}", "vocabulario"))
        opciones.append((f"Carpeta donde guardar: {corta(salida) if salida else 'junto al audio'}", "carpeta"))
        try:
            opcion = elegir("¿Qué quieres cambiar?", opciones)
        except (Atras, KeyboardInterrupt, EOFError):
            return idioma, salida, vocabulario
        try:
            if opcion == "idioma":
                idioma = preguntar_idioma("¿En qué idioma está el audio?", idioma)
            elif opcion == "vocabulario":
                vocabulario = preguntar_vocabulario(vocabulario)
            else:
                elegida = ruta("Carpeta donde guardar (vacío: junto al audio):", validar=_validar_carpeta,
                               solo_carpetas=True, defecto=_para_escribir(salida)).strip()
                salida = limpiar_ruta(elegida) if elegida else None
        except (Atras, KeyboardInterrupt, EOFError):
            consola.print()


def preguntar_vocabulario(actual: str) -> str:
    """Nombres y siglas que la corrección debe escribir bien. Vacío: ninguno."""
    consola.print("[dim]Escribe los nombres, siglas o palabras raras que se dicen en el audio, separados por "
                  "comas. Al corregir, la IA los usará para escribirlos bien.[/]")
    return texto("Vocabulario (vacío: ninguno):", defecto=actual).strip()


def _texto_vocabulario(vocabulario: str, largo: int = 40) -> str:
    if not vocabulario:
        return "ninguno"
    return vocabulario if len(vocabulario) <= largo else vocabulario[:largo - 1].rstrip(" ,") + "…"


def preguntar_idioma(mensaje: str, actual: str) -> str:
    while True:
        idioma = elegir(mensaje, [*IDIOMAS, ("Otro…", "otro")], actual if actual in dict(IDIOMAS).values() else "otro")
        if idioma != "otro":
            return idioma
        try:
            return texto("Código del idioma, por ejemplo ja, ru o nl:", validar=_validar_idioma,
                         defecto="" if actual in dict(IDIOMAS).values() else actual).strip().lower()
        except Atras:
            continue


def _nombre_idioma(codigo: str) -> str:
    return next((nombre for nombre, valor in IDIOMAS if valor == codigo), codigo)


# --- Corregir y nombres -----------------------------------------------------

def flujo_corregir():
    while True:
        archivo = elegir_transcripcion("¿Cuál quieres corregir?")
        try:
            corregir_archivo(archivo)
        except Atras:
            continue  # de vuelta a ¿Cuál?
        return acciones_sobre(*_txt_y_json(archivo), "¿Y ahora?")


def flujo_nombres():
    while True:
        archivo = elegir_transcripcion("¿A cuál le cambio los nombres?", solo_con_hablantes=True)
        try:
            nombrar_archivo(archivo)
        except Atras:
            continue
        return acciones_sobre(*_txt_y_json(archivo), "¿Y ahora?")


def corregir_archivo(archivo: Path) -> Optional[Path]:
    """
    Pregunta el modelo y si revisar los cambios, y corrige. Retorna el .txt corregido (None si no se pudo).
    Volver atrás en la primera pregunta lanza Atras.
    """
    if not _instalado("mlx_lm"):
        _avisar(_falta_correccion("Para corregir con IA falta mlx-lm. Instálalo con:\n"))
        return None
    prefs = historial.preferencias()
    r = {"modelo": ajustes.valor("modelo_corrector"), "revisar": prefs.get("revisar", False)}

    def modelo():
        r["modelo"] = elegir("¿Qué modelo de IA?", _opciones_con_descripcion(MODELOS_IA, ajustes.valor("modelo_corrector")),
                             r["modelo"])

    def revisar():
        r["revisar"] = si_no("¿Quieres revisar cada cambio antes de aplicarlo?", r["revisar"])

    seguir_pasos([modelo, revisar])
    historial.guardar_preferencias(modelo_corrector=r["modelo"], revisar=r["revisar"])
    return _ejecutar(cli.corregir, archivo=archivo, modelo=r["modelo"], revisar=r["revisar"])


def nombrar_archivo(json_path: Path) -> Optional[Path]:
    """Pregunta cómo poner los nombres y los aplica. Retorna el .txt actualizado (None si no se pudo)."""
    from utils.formatters import cargar_transcripcion

    try:
        datos = cargar_transcripcion(json_path)
    except Exception as e:
        _avisar(f"No pude leer {json_path.name}: {e}")
        return None
    actuales = [datos["nombres"].get(e, e) for e in cli._hablantes_en_orden(datos["parrafos"])]
    if not actuales:
        _avisar(f"{json_path.name} no tiene hablantes identificados.")
        return None
    consola.print(f"[dim]Ahora se llaman: {escape(', '.join(actuales))}[/]")

    r = {"como": None, "lista": None}

    def como():
        r["como"] = elegir("¿Cómo?", [
            ("Escuchar a cada uno y ponerle nombre", "escuchar"),
            ("Escribir los nombres en orden (Ana, Luis…)", "lista"),
            ("Usar los nombres que edité a mano en el .json", "json"),
        ], r["como"])

    def lista():
        if r["como"] != "lista":
            r["lista"] = None
            return False
        r["lista"] = texto(f"Nombres en orden de aparición, separados por comas ({len(actuales)} hablantes):",
                           validar=_validar_nombres, defecto=r["lista"] or "").strip()

    seguir_pasos([como, lista])
    como, lista = r["como"], r["lista"]
    return _ejecutar(cli.poner_nombres, archivo=json_path, lista=lista, escuchar=como == "escuchar")


def elegir_transcripcion(mensaje: str, solo_con_hablantes: bool = False) -> Path:
    """
    Ofrece las últimas transcripciones del historial y la opción de buscar otro archivo.
    Retorna el .json si existe (o el .txt). Volver atrás en la lista lanza Atras.
    """
    entradas = [e for e in historial.listar() if e["json"] or not solo_con_hablantes][:MAX_EN_LISTA]
    while True:
        if entradas:
            eleccion = elegir(mensaje, [*[(t, i) for i, t in enumerate(etiquetas(entradas))],
                                        ("Buscar otro archivo…", "buscar")])
            if eleccion != "buscar":
                return entradas[eleccion]["json"] or entradas[eleccion]["txt"]
        try:
            if solo_con_hablantes:
                pedido = ruta("Arrastra el .blocks.json aquí o escribe su ruta:", validar=_validar_json)
            else:
                pedido = ruta("Arrastra el .blocks.json o el .blocks.txt aquí, o escribe su ruta:",
                              validar=_validar_transcripcion)
        except Atras:
            if entradas:
                continue  # de vuelta a la lista
            raise
        archivo = limpiar_ruta(pedido)
        # Así aparece en la lista la próxima vez
        txt, json_path = _txt_y_json(archivo)
        if txt.exists():
            historial.registrar(txt, json_path)
        return archivo


# --- Configuración ------------------------------------------------------------

MODOS = [
    ("Preguntar cada vez", ajustes.PREGUNTAR),
    ("Siempre", ajustes.SIEMPRE),
    ("Nunca", ajustes.NUNCA),
]


def flujo_configuracion():
    """Cambia los valores por defecto. Cada cambio se guarda al momento."""
    mensaje = "¿Qué quieres cambiar?"
    while True:
        salida = ajustes.carpeta("carpeta_salida")
        try:
            opcion = _elegir_ajuste(mensaje, salida)
        except Atras:
            return True
        try:
            cambio = _cambiar_ajuste(opcion)
        except (Atras, KeyboardInterrupt, EOFError):
            consola.print()
            cambio = None
        if cambio is not None:
            ajustes.guardar(**{opcion: cambio})
            consola.print("[green]✓[/] Guardado.")
            _avisar_si_falta(opcion, cambio)
        mensaje = "¿Algo más?"


def _elegir_ajuste(mensaje: str, salida: Optional[Path]) -> str:
    """La lista de ajustes, cada uno con su valor actual."""
    return elegir(mensaje, [
        (f"Idioma: {_nombre_idioma(ajustes.valor('idioma'))}", "idioma"),
        (f"Modelo de transcripción: {ajustes.valor('modelo')}", "modelo"),
        (f"Modelo de IA para corregir: {ajustes.valor('modelo_corrector')}", "modelo_corrector"),
        (f"Vocabulario para corregir: {_texto_vocabulario(ajustes.valor('vocabulario'))}", "vocabulario"),
        (f"Identificar hablantes: {_nombre_modo(ajustes.valor('modo_hablantes'))}", "modo_hablantes"),
        (f"Corregir al terminar: {_nombre_modo(ajustes.valor('modo_correccion'))}", "modo_correccion"),
        (f"Carpeta de descargas: {_texto_descargas()}", "carpeta_descargas"),
        (f"Carpeta de las transcripciones: {corta(salida) if salida else 'junto al audio'}", "carpeta_salida"),
    ])


def _cambiar_ajuste(clave: str):
    """Pregunta el nuevo valor de un ajuste. Retorna None si no cambia."""
    actual = ajustes.valor(clave)
    if clave == "idioma":
        return preguntar_idioma("Idioma por defecto del audio:", actual)
    if clave == "modelo":
        return elegir("Modelo de transcripción por defecto:", _opciones_con_descripcion(MODELOS_WHISPER, actual), actual)
    if clave == "vocabulario":
        return preguntar_vocabulario(actual)
    if clave == "modelo_corrector":
        return elegir("Modelo de IA para corregir:", _opciones_con_descripcion(MODELOS_IA, actual), actual)
    if clave == "modo_hablantes":
        return elegir("¿Identifico quién habla al transcribir?", MODOS, actual)
    if clave == "modo_correccion":
        return elegir("¿Corrijo el texto con IA al terminar de transcribir?", MODOS, actual)
    if clave == "carpeta_descargas":
        elegida = ruta("Carpeta para el audio que se descarga de YouTube (se crea si no existe):",
                       validar=_validar_carpeta_obligatoria, solo_carpetas=True,
                       defecto=_para_escribir(ajustes.carpeta("carpeta_descargas"))).strip()
        return str(limpiar_ruta(elegida).resolve())
    # carpeta_salida
    while True:
        donde = elegir("¿Dónde guardo las transcripciones?", [
            ("Junto al audio", "junto"),
            ("Siempre en la misma carpeta…", "carpeta"),
        ], "carpeta" if actual else "junto")
        if donde == "junto":
            return ""
        try:
            elegida = ruta("Carpeta para las transcripciones (se crea si no existe):",
                           validar=_validar_carpeta_obligatoria, solo_carpetas=True,
                           defecto=_para_escribir(ajustes.carpeta("carpeta_salida"))).strip()
        except Atras:
            continue
        return str(limpiar_ruta(elegida).resolve())


def _avisar_si_falta(clave: str, valor):
    if clave == "modo_hablantes" and valor != ajustes.NUNCA and not _instalado("pyannote.audio"):
        consola.print(f"[yellow]{escape(_falta_diarizacion('Para identificar hablantes falta instalar: '))}[/]")
    if clave in ("modo_correccion", "modelo_corrector") and valor != ajustes.NUNCA and not _instalado("mlx_lm"):
        consola.print(f"[yellow]{escape(_falta_correccion('Para corregir con IA falta instalar: '))}[/]")


def _nombre_modo(modo: str) -> str:
    return next(nombre for nombre, valor in MODOS if valor == modo).lower()


def _texto_descargas() -> str:
    carpeta = ajustes.carpeta("carpeta_descargas")
    if carpeta.is_absolute():
        return corta(carpeta)
    # Así viene de fábrica (DOWNLOAD_DIR del .env): relativa a donde se ejecuta el comando
    return f"{carpeta}/ (dentro de la carpeta donde ejecutas transcriptor)"


def _para_escribir(carpeta: Optional[Path]) -> str:
    """El valor actual, listo para editar en la pregunta (con ~ y / al final para seguir con Tab)."""
    if not carpeta or not carpeta.is_absolute():
        return ""
    return corta(carpeta).rstrip("/") + "/"


def corta(carpeta: Path) -> str:
    """'/Users/max/Descargas' -> '~/Descargas'."""
    carpeta = Path(carpeta)
    try:
        return "~/" + str(carpeta.relative_to(Path.home()))
    except ValueError:
        return str(carpeta)


# --- Mis transcripciones ----------------------------------------------------

def flujo_mis_transcripciones():
    entradas = historial.listar()[:MAX_EN_LISTA]
    if not entradas:
        consola.print("[dim]Todavía no hay transcripciones en tu historial. "
                      "Las que hagas a partir de ahora aparecerán aquí.[/]")
        return True
    while True:
        eleccion = elegir("¿Cuál?", [(t, i) for i, t in enumerate(etiquetas(entradas))])
        entrada = entradas[eleccion]
        try:
            return acciones_sobre(entrada["txt"], entrada["json"], f"¿Qué hago con {_nombre(entrada['txt'])}?",
                                  volver=True)
        except Atras:
            continue  # de vuelta a la lista


def acciones_sobre(txt: Path, json_path: Optional[Path], mensaje: str, volver: bool = False):
    """
    Lo que se puede hacer con una transcripción: abrirla, corregirla, cambiar nombres...
    Retorna False si eliges Salir (para cerrar el programa), True para volver al menú.
    Con volver, ofrece "← Volver" (lanza Atras, para regresar a la lista de donde se eligió).
    """
    from src.corrector import rutas_de_salida

    while True:
        corregido = rutas_de_salida(json_path or txt)[0]
        opciones = [("Abrir la transcripción", "abrir")]
        if corregido.exists():
            opciones.append(("Abrir la versión corregida", "abrir_corregida"))
        opciones.append(("Corregir otra vez" if corregido.exists() else "Corregir esta transcripción", "corregir"))
        if json_path:
            opciones.append(("Cambiar nombres de hablantes", "nombres"))
        opciones += [
            (NOMBRE_MOSTRAR_EN_CARPETA.get(sys.platform, "Mostrar en su carpeta"), "carpeta"),
            ("Volver al menú", "menu"),
            ("Salir", "salir"),
        ]
        try:
            opcion = elegir(mensaje, opciones, volver=volver)
        except (KeyboardInterrupt, EOFError):
            return True
        if opcion == "menu":
            return True
        if opcion == "salir":
            return False
        try:
            if opcion == "abrir":
                abrir(txt)
            elif opcion == "abrir_corregida":
                abrir(corregido)
            elif opcion == "carpeta":
                abrir(txt, revelar=True)
            elif opcion == "corregir":
                corregir_archivo(json_path or txt)
            elif opcion == "nombres":
                nombrar_archivo(json_path)
        except (Atras, KeyboardInterrupt, EOFError):
            consola.print()
        mensaje = "¿Algo más con esta transcripción?"


def etiquetas(entradas: list) -> list:
    """'entrevista   · hoy 10:42 · 1 h 10 min · Ana, Luis · corregida', alineadas por el nombre."""
    from src.corrector import rutas_de_salida
    from utils.formatters import cargar_transcripcion

    nombres = [_nombre(e["txt"]) for e in entradas]
    nombres = [n if len(n) <= 28 else n[:27] + "…" for n in nombres]
    ancho = max(len(n) for n in nombres)
    resultado = []
    for nombre, e in zip(nombres, entradas):
        partes = [nombre.ljust(ancho), cuando(e["fecha"])]
        duracion, hablantes = e["duracion"], None
        if e["json"]:
            try:
                datos = cargar_transcripcion(e["json"])
                etiquetas_hablantes = cli._hablantes_en_orden(datos["parrafos"])
                hablantes = [datos["nombres"].get(h, h) for h in etiquetas_hablantes]
                if duracion is None and datos["parrafos"]:
                    duracion = max(p["end"] for p in datos["parrafos"])
            except Exception:
                pass
        if duracion:
            partes.append(cli._duracion(duracion))
        if hablantes:
            partes.append(", ".join(hablantes) if len(hablantes) <= 3 else f"{len(hablantes)} hablantes")
        if rutas_de_salida(e["json"] or e["txt"])[0].exists():
            partes.append("corregida")
        resultado.append(" · ".join(partes))
    return resultado


def cuando(fecha: float, ahora: Optional[datetime] = None) -> str:
    """'hoy 10:42', 'ayer 18:05', '3 oct' o '3 oct 2025'."""
    momento = datetime.fromtimestamp(fecha)
    hoy = (ahora or datetime.now()).date()
    if momento.date() == hoy:
        return f"hoy {momento:%H:%M}"
    if momento.date() == hoy - timedelta(days=1):
        return f"ayer {momento:%H:%M}"
    texto = f"{momento.day} {MESES[momento.month - 1]}"
    return texto if momento.year == hoy.year else f"{texto} {momento.year}"


def abrir(archivo: Path, revelar: bool = False):
    """Abre el archivo con su programa (o muestra dónde está, con revelar)."""
    if sys.platform == "darwin":
        comando = ["open", "-R", str(archivo)] if revelar else ["open", str(archivo)]
    elif sys.platform == "win32":
        if not revelar:
            os.startfile(str(archivo))
            return
        # explorer quiere la ruta pegada a /select, entre comillas (por los espacios)
        comando = f'explorer /select,"{archivo}"'
    elif shutil.which("xdg-open"):
        comando = ["xdg-open", str(archivo.parent if revelar else archivo)]
    else:
        consola.print(f"Está en [cyan]{escape(str(archivo))}[/]")
        return
    subprocess.run(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


# --- Utilidades -------------------------------------------------------------

def _ejecutar(comando, **opciones):
    """
    Corre un comando de la CLI. Si falla o se cancela, el comando ya mostró el motivo:
    retornamos None y el menú sigue.
    """
    try:
        return comando(**opciones)
    except typer.Exit:
        return None
    except typer.BadParameter as e:
        _avisar(e.format_message())
        return None


def _avisar(mensaje: str):
    cli.consola_err.print(Panel(Text(mensaje), border_style="yellow", expand=False))


def _falta_diarizacion(como_instalar: str) -> str:
    """Cómo instalar la diarización, o por qué no se puede en este computador."""
    if not plataforma.hablantes_disponible():
        return plataforma.SIN_HABLANTES
    return como_instalar + INSTALAR_DIARIZACION


def _falta_correccion(como_instalar: str) -> str:
    """Cómo instalar la corrección con IA, o por qué no se puede en este computador."""
    if not plataforma.correccion_disponible():
        return plataforma.SIN_CORRECCION
    return como_instalar + INSTALAR_CORRECCION


def _instalado(modulo: str) -> bool:
    try:
        return importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


def _opciones_con_descripcion(modelos: list, por_defecto: str) -> list:
    """[('turbo   · rápido y...', 'turbo'), ...]; si el modelo del .env no está en la lista, se añade."""
    if por_defecto not in [nombre for nombre, _ in modelos]:
        modelos = [*modelos, (por_defecto, "el de tu .env")]
    ancho = max(len(nombre) for nombre, _ in modelos)
    return [(f"{nombre.ljust(ancho)}  · {descripcion}", nombre) for nombre, descripcion in modelos]


def _nombre(txt: Path) -> str:
    """'entrevista.blocks.txt' -> 'entrevista'."""
    nombre = Path(txt).name
    for sufijo in (".blocks.txt", ".txt"):
        if nombre.endswith(sufijo):
            return nombre[:-len(sufijo)]
    return nombre


def _txt_y_json(archivo: Path) -> tuple:
    """Para un .blocks.json o .blocks.txt: (el .txt, el .json si existe)."""
    archivo = Path(archivo)
    json_path = archivo.with_suffix(".json")
    return archivo.with_suffix(".txt"), json_path if json_path.exists() else None


def limpiar_ruta(texto: str) -> Path:
    """
    Acepta rutas escritas o arrastradas a la terminal: "entre comillas" o con los espacios
    escapados como hace la Terminal del Mac (Mi\\ audio.m4a).
    En Windows la \\ separa carpetas (C:\\Users\\...), así que ahí no se toca.
    """
    texto = texto.strip()
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "'\"":
        texto = texto[1:-1]
    elif sys.platform != "win32":
        texto = re.sub(r"\\(.)", r"\1", texto)
    return Path(texto).expanduser()


def _validar_archivo(texto: str):
    if not texto.strip():
        return "Escribe la ruta o arrastra el archivo aquí."
    archivo = limpiar_ruta(texto)
    if archivo.is_dir():
        return "Eso es una carpeta: elige un archivo de audio o video."
    if not archivo.exists():
        return "No encuentro ese archivo."
    return True


def _validar_transcripcion(texto: str):
    valido = _validar_archivo(texto)
    if valido is True and limpiar_ruta(texto).suffix not in (".json", ".txt"):
        return "Necesito el .blocks.json o el .blocks.txt de una transcripción."
    return valido


def _validar_json(texto: str):
    valido = _validar_archivo(texto)
    if valido is True and limpiar_ruta(texto).suffix != ".json":
        return "Necesito el .blocks.json (solo existe si identificaste a los hablantes)."
    return valido


def _validar_enlace(texto: str):
    return True if es_url(texto) else "Pega un enlace que empiece con http:// o https://"


def _validar_carpeta(texto: str):
    if texto.strip() and limpiar_ruta(texto).is_file():
        return "Eso es un archivo: elige una carpeta."
    return True


def _validar_carpeta_obligatoria(texto: str):
    if not texto.strip():
        return "Escribe la ruta de una carpeta o arrástrala aquí."
    return _validar_carpeta(texto)


def _validar_idioma(texto: str):
    texto = texto.strip()
    return True if texto.isalpha() and 2 <= len(texto) <= 3 else "Escribe el código del idioma, como en, ja o ru."


def _validar_nombres(texto: str):
    if not texto.strip():
        return "Escribe al menos un nombre."
    try:
        parsear_nombres(texto)
    except ValueError as e:
        return str(e).replace("En --nombres, ", "")
    return True
