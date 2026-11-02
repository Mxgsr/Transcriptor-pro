# Ubicación: src/menu.py
# Menú con flechas que se abre al escribir `transcriptor` sin nada más.
# Aquí solo se hacen preguntas: el trabajo lo hacen los mismos comandos de src/cli.py.
import importlib.util
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import questionary
import typer
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.text import Text

from src import actualizar, ajustes, aviso, buscar, cli, clic_derecho, historial, modelos, plataforma, sistema, vista, voces
from src.diarizer import parsear_nombres
from src.sistema import abrir
from utils.formatters import MESES_COMPLETOS, a_fecha, formato_duracion
from utils.validators import es_url, limpiar_ruta

consola = cli.consola
logger = logging.getLogger(__name__)

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
    ("turbo", "rápido y casi tan preciso como large"),
    ("large", "el más preciso, el más lento"),
    ("medium", "equilibrado"),
    ("small", "rápido, para pruebas"),
    ("base", "muy rápido, menos preciso"),
    ("tiny", "el más rápido, el menos preciso"),
]

IDIOMAS = [
    ("Español", "es"), ("Inglés", "en"), ("Portugués", "pt"), ("Francés", "fr"),
    ("Italiano", "it"), ("Alemán", "de"), ("Catalán", "ca"),
]

NO_LO_SE = "No lo sé"
CUANTOS = [NO_LO_SE, "2", "3", "4", "5 o más"]
NO_IDENTIFICAR = "no"  # respuesta a "¿Identifico quién habla?" que no es un número de personas

# Pregunta única de hablantes cuando Configuración dice "preguntar cada vez"
OPCIONES_HABLANTES = [
    ("No identificar", NO_IDENTIFICAR),
    ("Sí, no sé cuántos", NO_LO_SE),
    ("Sí, 2 personas", "2"),
    ("Sí, 3 personas", "3"),
    ("Sí, 4 personas", "4"),
    ("Sí, 5 o más", "5 o más"),
]

# Abreviados: las tres primeras letras de cada mes (ene, feb... sep, dic), derivados de la lista completa
MESES = [mes[:3] for mes in MESES_COMPLETOS]

# Cuántas transcripciones se ofrecen en las listas (las más recientes); «Ver más antiguas…» muestra las siguientes
MAX_EN_LISTA = 15
# Cuántos resultados de una búsqueda se ofrecen (más no se leen: conviene buscar con más palabras)
MAX_RESULTADOS = 50

# Quien usa el menú no maneja comandos: si falta el componente, se le dice qué hacer en simple
FALTA_DIARIZACION = "Para identificar hablantes falta un componente. Vuelve a ejecutar el instalador."

# Textos generales, sin nombrar el sistema (Finder, Explorador...): los usuarios tienen computadores distintos
MOSTRAR_EN_CARPETA = "Mostrar en su carpeta"


# --- Preguntas --------------------------------------------------------------
# "← Volver" (o Esc) lanza Atras: quien pregunta vuelve al paso anterior.
# Ctrl+C sube como KeyboardInterrupt y vuelve al menú principal.

class Atras(Exception):
    """Se eligió "← Volver" o se apretó Esc."""


class CerrarPrograma(Exception):
    """Algo (p. ej. una actualización terminada) pide cerrar el programa: sube hasta iniciar()."""


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


def elegir(mensaje: str, opciones: list, defecto=None, volver: bool = True, texto_volver: str = VOLVER):
    """
    Lista para elegir con flechas. Cada opción es un texto o una tupla (texto, valor).
    Con volver, termina con "← Volver" (y Esc hace lo mismo). texto_volver cambia ese texto
    (p. ej. "Dejar como está") cuando "volver" significa otra cosa en esa pregunta.
    """
    choices = [questionary.Choice(o[0], o[1]) if isinstance(o, tuple) else questionary.Choice(o, o)
               for o in opciones]
    # questionary falla si el valor por defecto no está entre las opciones (p. ej. una preferencia antigua)
    if defecto is not None and defecto not in [c.value for c in choices]:
        defecto = None
    if volver:
        choices.append(questionary.Choice(texto_volver, _ATRAS))
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


def clave_secreta(mensaje: str, volver: bool = True) -> str:
    """Campo para pegar una clave: no muestra lo que se escribe."""
    return _preguntar(questionary.password(_con_pista(mensaje, volver), qmark="?", style=ESTILO), volver)


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

    _avisar_version_nueva()

    acciones = {
        "preparar": flujo_preparar,
        "transcribir": flujo_transcribir,
        "nombres": flujo_nombres,
        "mis": flujo_mis_transcripciones,
        "configuracion": flujo_configuracion,
    }
    while True:
        # Se recalcula en cada vuelta: al descargar lo que falta, la opción desaparece
        opciones = [
            ("Transcribir audio o video", "transcribir"),
            ("Cambiar nombres de hablantes", "nombres"),
            ("Mis transcripciones", "mis"),
            ("Configuración", "configuracion"),
            ("Salir", "salir"),
        ]
        if _necesita_preparacion():
            opciones.insert(0, ("Preparar la app (falta descargar lo necesario)", "preparar"))
        try:
            accion = elegir("¿Qué quieres hacer?", opciones, volver=False)
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
        except CerrarPrograma:
            seguir = False
        if seguir is False:
            consola.print("[dim]Hasta luego.[/]")
            return
        consola.print()


def _necesita_preparacion() -> bool:
    try:
        return modelos.necesita_preparacion()
    except Exception as e:
        logger.debug(f"Error ignorado ({type(e).__name__}): {e}")
        return False


def _avisar_version_nueva():
    """Busca versiones nuevas sin esperar y, si ya se sabe de una, lo dice en una línea. Nunca impide abrir el menú."""
    try:
        actualizar.buscar_en_segundo_plano()
        novedad = actualizar.aviso_guardado()
        if novedad:
            consola.print(f" [dim]Hay una versión nueva ({escape(novedad.version)}). "
                          "Puedes instalarla en Configuración › Buscar actualizaciones.[/]\n")
    except Exception as e:
        logger.debug(f"Error ignorado ({type(e).__name__}): {e}")
        pass


# --- Transcribir ------------------------------------------------------------

def flujo_transcribir():
    prefs = historial.preferencias()
    instalado_hablantes = _instalado("pyannote.audio")
    modo_hablantes = ajustes.valor("modo_hablantes")

    # Las respuestas: al volver atrás, cada pregunta ofrece lo que ya se había respondido.
    # Idioma y carpeta salen de Configuración; "Más opciones…" los cambia solo para esta vez.
    r = {"entrada": "", "modelo": ajustes.valor("modelo"), "hablantes": False, "cuantos": None,
         "idioma": ajustes.valor("idioma"), "salida": ajustes.carpeta("carpeta_salida")}

    def entrada():
        r["entrada"] = ruta("Arrastra el archivo o pega el enlace:", validar=_validar_archivo_o_enlace,
                            defecto=r["entrada"]).strip()

    # Una sola pregunta. Con "siempre" no se ofrece "No identificar"; con "nunca" (o sin pyannote) no se pregunta
    def hablantes():
        if not instalado_hablantes or modo_hablantes == ajustes.NUNCA:
            r["hablantes"], r["cuantos"] = False, None
            return False
        if modo_hablantes == ajustes.SIEMPRE:
            respuesta = elegir("¿Cuántas personas hablan?", CUANTOS, r["cuantos"] or prefs.get("cuantos", NO_LO_SE))
        else:
            if "respuesta_hablantes" in r:
                defecto = r["respuesta_hablantes"]
            elif prefs.get("hablantes", True):
                defecto = prefs.get("cuantos") or NO_LO_SE
            else:
                defecto = NO_IDENTIFICAR
            respuesta = elegir("¿Identifico quién habla?", OPCIONES_HABLANTES, defecto)
            r["respuesta_hablantes"] = respuesta
            r["hablantes_dicho"] = respuesta != NO_IDENTIFICAR
        r["hablantes"] = respuesta != NO_IDENTIFICAR
        r["cuantos"] = respuesta if r["hablantes"] else None

    # Cómo se llama la reunión: por defecto "<fecha de grabación> Reunión". Si se cambia el archivo,
    # la propuesta se recalcula (la fecha es la de ese audio).
    def nombre():
        propuesta = f"{fecha_de_grabacion(_entrada(r)).isoformat()} Reunión"
        if r.get("nombre_para") != r["entrada"]:
            r["nombre"] = propuesta
        r["nombre"] = texto("¿Cómo se llama esta reunión?", defecto=r["nombre"]).strip()
        r["nombre_para"] = r["entrada"]
        r["fecha"], r["titulo"] = separar_fecha_y_titulo(r["nombre"], fecha_de_grabacion(_entrada(r)))

    def empezar():
        while True:
            falta_modelo = _falta_descargar(r["modelo"])
            consola.print(_resumen_transcribir(_entrada(r), r["modelo"], r["hablantes"], r["cuantos"],
                                               r["idioma"], r["salida"], f"{r['fecha'].isoformat()} {r['titulo']}",
                                               descarga=falta_modelo))
            decision = elegir("¿Empiezo?", [
                ("Sí, empezar", "empezar"),
                ("Más opciones… (modelo, idioma, carpeta)", "mas"),
                ("Cancelar", "cancelar"),
            ])
            if decision == "mas":
                r["modelo"], r["idioma"], r["salida"] = _mas_opciones(r["modelo"], r["idioma"], r["salida"])
                continue
            # Con «Sin internet» y algo sin descargar, transcribir fallaría: se ofrece descargarlo antes
            if decision == "empezar" and not _resolver_faltantes_sin_internet(r["modelo"], r["hablantes"]):
                continue
            r["decision"] = decision
            return

    seguir_pasos([entrada, hablantes, nombre, empezar])
    if r["decision"] == "cancelar":
        return True

    # Lo que se respondió queda como respuesta por defecto la próxima vez. Si la pregunta no se hizo,
    # se conserva la anterior. El modelo de "Más opciones…" es solo para esta vez, como idioma y carpeta:
    # el de por defecto se cambia en Configuración (y es el que usan los scripts y el Grabador).
    recordar = {"cuantos": r["cuantos"] or prefs.get("cuantos")}
    if "hablantes_dicho" in r:
        recordar["hablantes"] = r["hablantes_dicho"]
    historial.guardar_preferencias(**recordar)

    num, minimo = numero_de_hablantes(r["cuantos"])
    resultado = _ejecutar(cli.ejecutar_transcripcion, entrada=_entrada(r), modelo=r["modelo"],
                          hablantes=r["hablantes"], num=num, minimo=minimo, idioma=r["idioma"], salida=r["salida"],
                          carpeta_descargas=ajustes.carpeta("carpeta_descargas"), desde_menu=True,
                          titulo=r["titulo"], fecha=r["fecha"])
    if resultado is None:
        return True

    return acciones_sobre(resultado.txt_path, resultado.json_path, "¿Y ahora?")


def _entrada(r: dict) -> str:
    """Lo que se va a transcribir: el enlace, o la ruta del archivo (limpia)."""
    return r["entrada"] if es_url(r["entrada"]) else str(limpiar_ruta(r["entrada"]))


def numero_de_hablantes(cuantos: Optional[str]) -> tuple:
    """'3' -> (3, None): exactamente 3. '5 o más' -> (None, 5): al menos 5. 'No lo sé' -> (None, None)."""
    if not cuantos or cuantos == NO_LO_SE:
        return None, None
    numero = int(cuantos.split()[0])
    return (None, numero) if "más" in cuantos else (numero, None)


def fecha_de_grabacion(entrada: str) -> date:
    """
    Cuándo se grabó el audio. Para un enlace, hoy. Para un archivo, la fecha más antigua entre su
    creación (st_birthtime en Mac; st_ctime es la creación en Windows) y su modificación: copiar un
    archivo cambia la creación pero no la modificación. Si no se puede leer, hoy.
    """
    if es_url(entrada):
        return date.today()
    try:
        info = Path(entrada).stat()
    except OSError:
        return date.today()
    # En Linux st_ctime es el último cambio de datos, no la creación; la modificación ya lo cubre
    creacion = getattr(info, "st_birthtime", None)
    if creacion is None and plataforma.es_windows():
        creacion = info.st_ctime
    momentos = [m for m in (creacion, info.st_mtime) if m]
    return datetime.fromtimestamp(min(momentos)).date() if momentos else date.today()


def separar_fecha_y_titulo(escrito: str, fecha_propuesta: date) -> tuple:
    """
    Si lo escrito empieza con una fecha AAAA-MM-DD, esa es la fecha y el resto el título; si no,
    se usa la fecha propuesta y todo lo escrito es el título. Título vacío: "Reunión".
    """
    escrito = escrito.strip()
    coincide = re.match(r"(\d{4}-\d{2}-\d{2})(?!\d)[\s\-–:]*(.*)$", escrito, re.DOTALL)
    fecha = a_fecha(coincide.group(1)) if coincide else None
    if fecha:
        escrito = coincide.group(2).strip()
    return fecha or fecha_propuesta, escrito or "Reunión"


def _falta_descargar(modelo: str) -> bool:
    """True si el modelo de transcripción todavía no está en este computador (si no se sabe, False)."""
    try:
        return not modelos.descargado(modelo)
    except Exception as e:
        logger.debug(f"Error ignorado ({type(e).__name__}): {e}")
        return False


def _resolver_faltantes_sin_internet(modelo: str, hablantes: bool) -> bool:
    """
    Con «Sin internet» activo, si falta algún modelo ofrece descargarlo (se conecta solo durante la descarga).
    Retorna True si se puede empezar; False si no se descargó (se vuelve a «¿Empiezo?»).
    """
    try:
        if not ajustes.sin_internet_activo():
            return True
        faltan = []
        if _falta_descargar(modelo):
            faltan.append((modelo, f"el modelo {modelo}"))
        if hablantes and plataforma.hablantes_disponible() and not modelos.descargado(modelos.HABLANTES):
            faltan.append((modelos.HABLANTES, "el modelo para identificar hablantes"))
    except Exception as e:
        logger.debug(f"Error ignorado ({type(e).__name__}): {e}")
        return True
    if not faltan:
        return True
    que = " y ".join(texto_ for _, texto_ in faltan)
    try:
        elegir(f"Falta descargar {que} y está activado «Sin internet».", [("Descargarlo ahora", True)],
               texto_volver="Volver")
    except Atras:
        return False
    return all(_descargar_modelo(clave) for clave, _ in faltan)


def _resumen_transcribir(entrada, modelo, hablantes, cuantos, idioma, salida, reunion=None, descarga=False) -> Text:
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
    resumen.append(".")
    if reunion:
        resumen.append(" La reunión se llamará ")
        resumen.append(reunion, style="bold")
        resumen.append(".")
    if salida:
        resumen.append(f" Lo guardo en {corta(salida)}.")
    if descarga:
        peso = modelos.PESO_APROXIMADO.get(modelo)
        aprox = f" (≈ {modelos.texto_peso(peso)})" if peso else ""
        resumen.append(f"\nLa primera vez descargo el modelo {modelo}{aprox}; puede tardar unos minutos.", style="yellow")
    return resumen


def _mas_opciones(modelo: str, idioma: str, salida: Optional[Path]) -> tuple:
    """Modelo, idioma y carpeta de salida para esta transcripción. "← Volver" regresa a ¿Empiezo?."""
    while True:
        opciones = [
            (f"Modelo: {modelo}", "modelo"),
            (f"Idioma: {_nombre_idioma(idioma)}", "idioma"),
            (f"Carpeta donde guardar: {corta(salida) if salida else 'junto al audio'}", "carpeta"),
        ]
        try:
            opcion = elegir("¿Qué quieres cambiar?", opciones)
        except (Atras, KeyboardInterrupt, EOFError):
            return modelo, idioma, salida
        try:
            if opcion == "modelo":
                modelo = elegir("¿Qué modelo uso?", _opciones_con_descripcion(MODELOS_WHISPER, ajustes.valor("modelo")),
                                modelo)
            elif opcion == "idioma":
                idioma = preguntar_idioma("¿En qué idioma está el audio?", idioma)
            else:
                elegida = ruta("Carpeta donde guardar (vacío: junto al audio):", validar=_validar_carpeta,
                               solo_carpetas=True, defecto=_para_escribir(salida)).strip()
                salida = limpiar_ruta(elegida) if elegida else None
        except (Atras, KeyboardInterrupt, EOFError):
            consola.print()


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


# --- Nombres -----------------------------------------------------

def flujo_nombres():
    while True:
        archivo = elegir_transcripcion("¿A cuál le cambio los nombres?", solo_con_hablantes=True)
        try:
            nombrar_archivo(archivo)
        except Atras:
            continue
        return acciones_sobre(*_txt_y_json(archivo), "¿Y ahora?")


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
                pedido = ruta("Arrastra la transcripción aquí o escribe su ruta:", validar=_validar_con_hablantes)
            else:
                pedido = ruta("Arrastra la transcripción aquí o escribe su ruta:", validar=_validar_transcripcion)
        except Atras:
            if entradas:
                continue  # de vuelta a la lista
            raise
        archivo = limpiar_ruta(pedido)
        if solo_con_hablantes and archivo.suffix == ".txt":
            archivo = _txt_y_json(archivo)[1]  # validado: el .json existe al lado
        # Así aparece en la lista la próxima vez
        txt, json_path = _txt_y_json(archivo)
        if txt.exists():
            historial.registrar(txt, json_path)
        return archivo


# --- Configuración ------------------------------------------------------------

_OLVIDAR_TODAS = "olvidar_todas"

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
        except CerrarPrograma:
            return False
        except (Atras, KeyboardInterrupt, EOFError):
            consola.print()
            cambio = None
        if cambio is not None:
            ajustes.guardar(**{opcion: cambio})
            if opcion == "sin_internet":
                ajustes.aplicar_sin_internet(cambio)
            consola.print("[green]✓[/] Guardado.")
            _avisar_si_falta(opcion, cambio)
        mensaje = "¿Algo más?"


def _elegir_ajuste(mensaje: str, salida: Optional[Path]) -> str:
    """La lista de ajustes, cada uno con su valor actual."""
    return elegir(mensaje, [
        (f"Idioma: {_nombre_idioma(ajustes.valor('idioma'))}", "idioma"),
        (f"Modelo de transcripción: {ajustes.valor('modelo')}", "modelo"),
        (f"Identificar hablantes: {_nombre_modo(ajustes.valor('modo_hablantes'))}", "modo_hablantes"),
        (f"Carpeta de descargas: {_texto_descargas()}", "carpeta_descargas"),
        (f"Carpeta de las transcripciones: {corta(salida) if salida else 'junto al audio'}", "carpeta_salida"),
        (f"Sin internet: {'sí' if ajustes.valor('sin_internet') else 'no'}", "sin_internet"),
        (f"Reconocer voces: {'sí' if ajustes.valor('reconocer_voces') else 'no'}", "reconocer_voces"),
        *_entrada_voces_guardadas(),
        *_entrada_clave(),
        ("Modelos (descargar o eliminar)", "modelos"),
        ("Preparar la app", "preparar"),
        *_entrada_clic_derecho(),
        (f"Buscar actualizaciones (tienes la versión {_version()})", "actualizaciones"),
    ])


def _version() -> str:
    try:
        return actualizar.version_instalada()
    except Exception as e:
        logger.debug(f"Error ignorado ({type(e).__name__}): {e}")
        return "?"


def _entrada_clave() -> list:
    """«Clave de Hugging Face: guardada/falta», solo si identificar hablantes funciona en este computador."""
    if not plataforma.hablantes_disponible():
        return []
    return [(f"Clave de Hugging Face: {'guardada' if modelos.token_guardado() else 'falta'}", "clave_hf")]


def _entrada_clic_derecho() -> list:
    if not clic_derecho.disponible():
        return []
    return [(f"Transcribir con clic derecho: {'sí' if clic_derecho.instalado() else 'no'}", "clic_derecho")]


def _entrada_voces_guardadas() -> list:
    """«Voces guardadas: N» solo si hay alguna (si no, no hay nada que olvidar)."""
    try:
        cuantas = len(voces.conocidas())
    except Exception as e:
        logger.debug(f"Error ignorado ({type(e).__name__}): {e}")
        return []
    return [(f"Voces guardadas: {cuantas}", "voces_guardadas")] if cuantas else []


def _gestionar_voces_guardadas():
    """Olvidar a una persona o a todas. Esc vuelve a Configuración. Siempre retorna None (no es un ajuste)."""
    while True:
        nombres = voces.conocidas()
        if not nombres:
            return None
        eleccion = elegir("Voces guardadas (solo están en este computador). ¿Cuál olvido?",
                          [*nombres, ("Olvidar todas", _OLVIDAR_TODAS)])
        if eleccion == _OLVIDAR_TODAS:
            if si_no("¿Seguro que olvido todas las voces? Tendrás que volver a ponerles nombre.", defecto=False):
                voces.olvidar_todas()
                consola.print("[green]✓[/] Olvidé todas las voces.")
            continue
        if si_no(f"¿Olvido la voz de {eleccion}?", defecto=False):
            voces.olvidar(eleccion)
            consola.print(f"[green]✓[/] Olvidé la voz de {escape(str(eleccion))}.")


def _cambiar_ajuste(clave: str):
    """Pregunta el nuevo valor de un ajuste. Retorna None si no cambia."""
    if clave == "voces_guardadas":  # no es un ajuste con valor: es la lista de voces para olvidar
        return _gestionar_voces_guardadas()
    # Tampoco son ajustes con valor: acciones. Siempre retornan None (no hay nada que guardar)
    if clave == "clave_hf":
        _configurar_clave()
        return None
    if clave == "modelos":
        _gestionar_modelos()
        return None
    if clave == "preparar":
        flujo_preparar()
        return None
    if clave == "clic_derecho":
        _cambiar_clic_derecho()
        return None
    if clave == "actualizaciones":
        if _buscar_actualizaciones():
            raise CerrarPrograma
        return None
    actual = ajustes.valor(clave)
    if clave == "idioma":
        return preguntar_idioma("Idioma por defecto del audio:", actual)
    if clave == "modelo":
        return elegir("Modelo de transcripción por defecto:", _opciones_con_descripcion(MODELOS_WHISPER, actual), actual)
    if clave == "modo_hablantes":
        return elegir("¿Identifico quién habla al transcribir?", MODOS, actual)
    if clave == "sin_internet":
        return elegir("¿Uso solo los modelos ya descargados?", [
            ("No: revisa si hay versiones nuevas y descarga los modelos que falten", False),
            ("Sí: no se conecta a Hugging Face (YouTube igual necesita internet)", True),
        ], bool(actual))
    if clave == "reconocer_voces":
        return elegir("¿Reconozco por la voz a quien ya nombraste antes?", [
            ("Sí: propone el nombre de quien ya nombraste antes (las voces se guardan solo en este computador)", True),
            ("No: deja de proponer y de guardar voces (las ya guardadas no se borran)", False),
        ], bool(actual))
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


# --- Modelos, clave y «Preparar la app» ---------------------------------------

def _descargar_modelo(clave: str) -> bool:
    """
    Descarga un modelo con barra de avance. Retorna True si quedó descargado. Un fallo se explica en
    simple (y el detalle se guarda) sin cerrar el programa; Ctrl+C sube y vuelve al menú.
    """
    nombre = "el modelo para identificar hablantes" if clave == modelos.HABLANTES else f"el modelo {clave}"
    peso = modelos.PESO_APROXIMADO.get(clave)
    consola.print(f"Descargando {nombre}" + (f" (≈ {modelos.texto_peso(peso)})" if peso else "") + "…")
    if ajustes.sin_internet_activo():
        consola.print("[dim]Tienes «Sin internet» activado: me conecto solo durante la descarga.[/]")
    columnas = (SpinnerColumn(), TextColumn("Descargando…"), BarColumn(bar_width=None), DownloadColumn(),
                TimeElapsedColumn())
    try:
        with Progress(*columnas, console=consola, transient=True) as progreso:
            tarea = progreso.add_task("descarga", total=None)  # sin total: barra que se mueve, hasta que llegue el avance

            def al_progresar(hecho, total):
                progreso.update(tarea, completed=hecho, total=total or None)

            modelos.descargar(clave, al_progresar)
    except RuntimeError as e:
        _avisar(str(e))
        return False
    except (KeyboardInterrupt, EOFError):
        raise
    except Exception as e:
        cli._mostrar_error(e, detalle=False)
        return False
    consola.print(f"[green]✓[/] Descargué {nombre}.")
    return True


def _abrir_pagina(url: str):
    if not sistema.abrir_pagina(url):
        consola.print(f"Ábrela en tu navegador: [cyan]{url}[/]")


def _configurar_clave() -> bool:
    """Explica para qué sirve la clave de Hugging Face y la pide. Retorna True si quedó guardada."""
    consola.print(
        "\nLa clave sirve para identificar quién habla en cada audio. Es gratis y se guarda solo en este computador.\n"
        "Pasos: 1) crea una cuenta gratis en Hugging Face y una clave de tipo «lectura»; "
        "2) abre la página del modelo y acepta sus condiciones.\n")
    while True:
        opcion = elegir("¿Qué hago?", [("Abrir las dos páginas", "paginas"), ("Pegar la clave", "pegar")])
        if opcion == "paginas":
            _abrir_pagina(modelos.PAGINA_TOKENS)
            _abrir_pagina(modelos.PAGINA_MODELO)
            continue
        try:
            token = clave_secreta("Pega la clave aquí:").strip()
        except Atras:
            continue
        if not token:
            continue
        if any(c.isspace() for c in token):
            _avisar("La clave no debe tener espacios. Revisa que la copiaste completa.")
            continue
        with consola.status("Comprobando…"):
            resultado = modelos.comprobar_token(token)
        if resultado == "ok":
            if _guardar_clave(token):
                consola.print("[green]✓[/] La clave funciona. La guardé solo en este computador.")
                return True
        elif resultado == "invalida":
            _avisar("Esa clave no sirve. Revisa que la copiaste completa.")
        elif resultado == "sin_acceso":
            _avisar("La clave sirve, pero falta aceptar las condiciones del modelo. "
                    "Abre su página, acepta y vuelve a intentarlo.")
            try:
                if elegir("¿Abro la página del modelo?", [("Abrir la página", True)], texto_volver="Ahora no"):
                    _abrir_pagina(modelos.PAGINA_MODELO)
            except Atras:
                pass
        else:  # sin_internet o desconocido
            try:
                guardar = si_no("No pude comprobarla (¿hay internet?). ¿La guardo igual?", defecto=False)
            except Atras:
                guardar = False
            if guardar and _guardar_clave(token):
                consola.print("[green]✓[/] Guardé la clave solo en este computador.")
                return True


def _guardar_clave(token: str) -> bool:
    try:
        modelos.guardar_token(token)
        return True
    except ValueError:
        _avisar("La clave está vacía o tiene espacios. Revisa que la copiaste completa.")
    except OSError:
        _avisar("No pude guardar la clave en este computador.")
    return False


def _etiqueta_modelo(m, ancho: int, usado: str) -> str:
    if m.descargado:
        texto_ = f"{m.nombre.ljust(ancho)} · descargado"
        if m.bytes:
            texto_ += f" · {modelos.texto_peso(m.bytes)}"
        if m.clave == usado:
            texto_ += " · el que usas"
        return texto_
    peso = modelos.PESO_APROXIMADO.get(m.clave)
    return f"{m.nombre.ljust(ancho)} · sin descargar" + (f" (≈ {modelos.texto_peso(peso)})" if peso else "")


def _gestionar_modelos():
    """Lista de modelos con su estado; elegir uno permite descargarlo o eliminarlo. Esc vuelve a Configuración."""
    while True:
        lista = modelos.estado()
        usado = ajustes.valor("modelo")
        ancho = max((len(m.nombre) for m in lista), default=0)
        clave = elegir("Modelos (se guardan en este computador). ¿Cuál?",
                       [(_etiqueta_modelo(m, ancho, usado), m.clave) for m in lista])
        m = next(m for m in lista if m.clave == clave)
        try:
            if not m.descargado:
                _descargar_desde_lista(m)
            else:
                _eliminar_desde_lista(m, usado)
        except Atras:
            continue


def _descargar_desde_lista(m):
    peso = modelos.PESO_APROXIMADO.get(m.clave)
    elegir(f"{m.nombre}", [(f"Descargar (≈ {modelos.texto_peso(peso)})" if peso else "Descargar", True)])
    if m.clave == modelos.HABLANTES and not modelos.token_guardado():
        elegir("Para este modelo hace falta la clave gratuita de Hugging Face.", [("Configurar la clave ahora", True)])
        if not _configurar_clave():
            return
    _descargar_modelo(m.clave)


def _eliminar_desde_lista(m, usado: str):
    liberado = modelos.texto_peso(m.bytes) if m.bytes else "espacio"
    elegir(f"{m.nombre}", [(f"Eliminar (libera {liberado})", True)])
    aviso_ = ""
    if m.clave == usado:
        aviso_ = " Es el que usas: se volverá a descargar al transcribir."
    if not si_no(f"¿Elimino {m.nombre}?{aviso_}", defecto=False):
        return
    try:
        modelos.eliminar(m.clave)
    except Exception as e:
        logger.warning(f"No se pudo eliminar el modelo {m.clave}: {e}")
        _avisar("No pude eliminar el modelo.")
        return
    consola.print(f"[green]✓[/] Eliminé {m.nombre} (liberé {liberado}).")


def flujo_preparar():
    """Deja la app lista: clave de hablantes (si hace falta) y los modelos que faltan por descargar."""
    quedo = []
    hablantes = plataforma.hablantes_disponible() and _instalado("pyannote.audio")
    if hablantes and not modelos.token_guardado():
        consola.print("\nPara identificar quién habla hace falta una clave gratuita de Hugging Face.")
        try:
            try:
                elegir("¿Qué hago?", [("Configurarla ahora", True)],
                       texto_volver="Ahora no (transcribir sin identificar hablantes)")
            except Atras:
                historial.guardar_preferencias(**{modelos.SIN_CLAVE_ELEGIDO: True})
                raise
            _configurar_clave()
        except Atras:
            pass  # «Ahora no», o Esc dentro de la clave: se sigue con lo demás
    modelo = ajustes.valor("modelo")
    if _falta_descargar(modelo) and not _descargar_modelo(modelo):
        quedo.append(f"el modelo {modelo}")
    if hablantes and modelos.token_guardado() and not modelos.descargado(modelos.HABLANTES):
        if not _descargar_modelo(modelos.HABLANTES):
            quedo.append("el modelo para identificar hablantes")
    if hablantes and not modelos.token_guardado():
        quedo.append("la clave para identificar hablantes")
    if quedo:
        consola.print(f"Falta: {', '.join(quedo)}. Puedes terminarlo en Configuración.")
    else:
        consola.print("[green]✓[/] Todo listo para transcribir.")
    return True


def _cambiar_clic_derecho():
    activo = clic_derecho.instalado()
    try:
        quiere = elegir("¿Transcribir con clic derecho?", [
            ("Sí: aparece «Transcribir con Transcriptor» al hacer clic derecho en un audio o video", True),
            ("No: quitarlo", False),
        ], activo)
    except Atras:
        return
    if quiere == activo:
        return
    if (clic_derecho.instalar() if quiere else clic_derecho.quitar()):
        consola.print("[green]✓[/] Listo." if not quiere else f"[green]✓[/] Listo. {escape(clic_derecho.TEXTO_DONDE)}")
    else:
        _avisar("No pude activarlo en este computador." if quiere else "No pude quitarlo en este computador.")


def _buscar_actualizaciones() -> bool:
    """Busca una versión nueva y ofrece instalarla. Retorna True si hay que cerrar el programa."""
    version = _version()
    try:
        with consola.status("Buscando…"):
            novedad = actualizar.buscar()
    except actualizar.SinConexion:
        _avisar("No pude revisar: no hay conexión a internet.")
        return False
    except Exception as e:
        logger.warning(f"No se pudo buscar actualizaciones: {e}")
        _avisar("No pude revisar si hay una versión nueva.")
        return False
    if novedad is None:
        consola.print(f"[green]✓[/] Tienes la última versión ({escape(version)}).")
        return False
    consola.print(f"Hay una versión nueva: {escape(novedad.version)} (tienes {escape(version)}).")
    try:
        elegir("¿Qué hago?", [("Actualizar ahora", True)], texto_volver="Ahora no")
    except Atras:
        return False
    if actualizar.como_se_instalo() != "uv_tool":
        _avisar(actualizar.MENSAJE_OTRA_INSTALACION)
        return False
    if not actualizar.buscar_uv():
        _avisar(actualizar.MENSAJE_SIN_UV)
        return False
    resultado = actualizar.actualizar(novedad, salida=consola.print)
    if resultado == "listo":
        consola.print("[green]✓[/] Actualizado. Abre Transcriptor de nuevo para usar la nueva versión.")
        return True
    if resultado == "reiniciar_aparte":
        consola.print("Se abrió una ventana que termina la actualización. Transcriptor se cerrará ahora.")
        return True
    _avisar("No se pudo actualizar. Inténtalo más tarde o vuelve a ejecutar el instalador.")
    return False


def _avisar_si_falta(clave: str, valor):
    if clave == "modo_hablantes" and valor != ajustes.NUNCA and not _instalado("pyannote.audio"):
        consola.print(f"[yellow]{escape(_falta_diarizacion())}[/]")


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
    todas = historial.listar()
    if not todas:
        consola.print("[dim]Todavía no hay transcripciones en tu historial. "
                      "Las que hagas a partir de ahora aparecerán aquí.[/]")
        return True
    pagina = 0
    while True:
        inicio = pagina * MAX_EN_LISTA
        entradas = todas[inicio:inicio + MAX_EN_LISTA]
        opciones = [("Buscar en todas…", "buscar")]
        if pagina > 0:
            opciones.append(("Ver más recientes…", "recientes"))
        opciones += [(t, i) for i, t in enumerate(etiquetas(entradas))]
        if inicio + MAX_EN_LISTA < len(todas):
            opciones.append(("Ver más antiguas…", "antiguas"))
        eleccion = elegir("¿Cuál?", opciones)
        if eleccion == "buscar":
            try:
                _buscar_en_todas()
            except Atras:
                pass
            continue
        if eleccion == "recientes":
            pagina -= 1
            continue
        if eleccion == "antiguas":
            pagina += 1
            continue
        entrada = entradas[eleccion]
        try:
            return acciones_sobre(entrada["txt"], entrada["json"], f"¿Qué hago con {_nombre(entrada['txt'])}?",
                                  volver=True)
        except Atras:
            continue  # de vuelta a la lista


def _buscar_en_todas():
    """Pregunta qué buscar y muestra los párrafos que lo contienen. Esc en la pregunta vuelve a la lista."""
    while True:
        consulta = texto("¿Qué busco? (una o varias palabras)").strip()
        if not consulta:
            continue
        with consola.status("Buscando…"):
            resultados = buscar.buscar(consulta)
        if not resultados:
            consola.print(f"No encontré «{escape(consulta)}» en tus transcripciones.")
            continue
        _elegir_resultado(resultados)


def _elegir_resultado(resultados: list):
    """Lista de resultados: elegir uno abre la lectura en ese momento y vuelve a la lista. Esc vuelve a la pregunta."""
    if len(resultados) > MAX_RESULTADOS:
        consola.print(f"[dim]Muestro las primeras {MAX_RESULTADOS}: prueba con más palabras.[/]")
    mostrados = resultados[:MAX_RESULTADOS]
    while True:
        try:
            eleccion = elegir("¿Cuál abro?", [(buscar.etiqueta(c), i) for i, c in enumerate(mostrados)])
        except Atras:
            return
        c = mostrados[eleccion]
        leer_con_audio(c.txt, c.json, c.audio, ir_a=c.inicio)


def leer_con_audio(txt: Path, json_path: Optional[Path], audio: Optional[Path] = None, ir_a: Optional[float] = None) -> bool:
    """Crea la vista de lectura (texto + audio) y la abre en el navegador. Retorna True si se pudo abrir."""
    try:
        ruta_vista = vista.crear_vista(txt, json_path, audio, ir_a=ir_a)
    except Exception as e:
        logger.warning(f"No se pudo crear la vista: {e}")
        _avisar("No pude preparar la lectura de esta transcripción.")
        return False
    try:
        if vista.datos_de_vista(txt, json_path, audio)["audio"] is None:
            consola.print("[yellow]No encuentro el audio: se verá sin audio.[/]")
    except Exception as e:
        logger.debug(f"Error ignorado ({type(e).__name__}): {e}")
        pass
    if vista.abrir_en_navegador(ruta_vista):
        consola.print("[green]✓[/] La abrí en el navegador. Haz clic en un párrafo para escucharlo.")
        return True
    _avisar(f"No pude abrir la vista. Está guardada en {corta(ruta_vista)}.")
    return False


def acciones_sobre(txt: Path, json_path: Optional[Path], mensaje: str, volver: bool = False):
    """
    Lo que se puede hacer con una transcripción: abrirla, cambiar nombres...
    Retorna False si eliges Salir (para cerrar el programa), True para volver al menú.
    Con volver, ofrece "← Volver" (lanza Atras, para regresar a la lista de donde se eligió).
    """
    while True:
        opciones = [("Abrir la transcripción", "abrir"), ("Leer con el audio", "leer"),
                    ("Copiar la transcripción", "copiar")]
        if json_path:
            opciones.append(("Cambiar nombres de hablantes", "nombres"))
            dudosas_n = cli._contar_dudosas(json_path)
            if dudosas_n:
                opciones.append((f"Revisar frases dudosas ({dudosas_n})", "dudosas"))
        opciones += [
            (MOSTRAR_EN_CARPETA, "carpeta"),
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
            elif opcion == "leer":
                leer_con_audio(txt, json_path)
            elif opcion == "dudosas":
                cli._revisar_dudosas(json_path, sys.modules[__name__])
            elif opcion == "copiar":
                copiar_transcripcion(txt)
            elif opcion == "carpeta":
                abrir(txt, revelar=True)
            elif opcion == "nombres":
                nombrar_archivo(json_path)
        except (Atras, KeyboardInterrupt, EOFError):
            consola.print()
        mensaje = "¿Algo más con esta transcripción?"


def copiar_transcripcion(txt: Path) -> bool:
    """Copia el contenido del .txt (con su encabezado, si lo tiene) al portapapeles."""
    try:
        # utf-8-sig quita la marca BOM; un .txt guardado como ANSI (cp1252) se lee como tal para no perder las tildes
        try:
            contenido = Path(txt).read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            contenido = Path(txt).read_text(encoding="cp1252", errors="replace")
    except (OSError, ValueError):
        contenido = None
    if contenido is not None and aviso.copiar_al_portapapeles(contenido):
        consola.print("[green]✓[/] Copiada. Puedes pegarla en Claude para hacer la minuta.")
        return True
    _avisar("No pude copiar la transcripción. Puedes abrirla y copiarla a mano.")
    return False


def etiquetas(entradas: list) -> list:
    """'entrevista   · hoy 10:42 · 1 h 10 min · Ana, Luis', alineadas por el nombre."""
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
            except Exception as e:
                logger.debug(f"Error ignorado ({type(e).__name__}): {e}")
                pass
        if duracion:
            partes.append(formato_duracion(duracion))
        if hablantes:
            partes.append(", ".join(hablantes) if len(hablantes) <= 3 else f"{len(hablantes)} hablantes")
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


# --- Utilidades -------------------------------------------------------------

def _ejecutar(comando, **opciones):
    """
    Corre un comando de la CLI. Si falla o se cancela, el comando ya mostró el motivo:
    retornamos None y el menú sigue.
    """
    cli.ultimo_error = None
    try:
        return comando(**opciones)
    except typer.Exit as salida:
        # Código 1 = falló y el recuadro ya lo explicó; 130 = canceló, no hay nada que preguntar
        if salida.exit_code == 1 and cli.ultimo_error:
            _que_hago_con_el_error(cli.ultimo_error)
        return None
    except typer.BadParameter as e:
        _avisar(e.format_message())
        return None


def _que_hago_con_el_error(archivo: Path):
    """
    Después de un error: ver el detalle, copiarlo para pedir ayuda, o volver. Se repite hasta volver (o Esc).
    «Ver el detalle» lo imprime aquí mismo en gris en vez de abrir el archivo: abrir un .txt lanza otro
    programa (Bloc de notas, TextEdit...) y quien no es técnico se pierde; en pantalla se lee al instante.
    """
    while True:
        try:
            decision = elegir("¿Qué hago?", [("Ver el detalle", "ver"), ("Copiar el error", "copiar")],
                              texto_volver="Volver al menú")
        except Atras:
            return
        try:
            contenido = Path(archivo).read_text(encoding="utf-8-sig", errors="replace")
        except (OSError, ValueError):
            _avisar(f"No pude leer el archivo del detalle. Debería estar en {cli.errores.ruta_corta(archivo)}")
            continue
        if decision == "ver":
            consola.print()
            consola.print(Text(contenido, style="dim"))
            consola.print()
        elif aviso.copiar_al_portapapeles(contenido):
            consola.print("[green]✓ Copiado.[/] Puedes pegarlo en un mensaje para pedir ayuda.")
        else:
            _avisar(f"No pude copiarlo. Puedes abrir el archivo a mano: {cli.errores.ruta_corta(archivo)}")


def _avisar(mensaje: str):
    cli.consola_err.print(Panel(Text(mensaje), border_style="yellow", expand=False))


def _falta_diarizacion() -> str:
    """Qué hacer si falta la diarización, o por qué no se puede en este computador."""
    if not plataforma.hablantes_disponible():
        return plataforma.SIN_HABLANTES
    return FALTA_DIARIZACION


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


def _validar_archivo(texto: str):
    if not texto.strip():
        return "Escribe la ruta o arrastra el archivo aquí."
    archivo = limpiar_ruta(texto)
    if archivo.is_dir():
        return "Eso es una carpeta: elige un archivo de audio o video."
    if not archivo.exists():
        return "No encuentro ese archivo."
    return True


def _validar_archivo_o_enlace(texto: str):
    """Un solo campo para las dos cosas: si empieza con http es un enlace, si no, un archivo."""
    if not texto.strip():
        return "Arrastra el archivo aquí o pega el enlace."
    if es_url(texto):
        return True
    return _validar_archivo(texto)


def _validar_transcripcion(texto: str):
    valido = _validar_archivo(texto)
    if valido is True and limpiar_ruta(texto).suffix not in (".json", ".txt"):
        return "Elige una transcripción hecha con Transcriptor (termina en .blocks.txt)."
    return valido


def _validar_con_hablantes(texto: str):
    """Para cambiar nombres: vale el .json, o el .txt si al lado está el .json."""
    valido = _validar_transcripcion(texto)
    if valido is not True:
        return valido
    archivo = limpiar_ruta(texto)
    if archivo.suffix == ".txt" and not _txt_y_json(archivo)[1]:
        return "Esa transcripción no tiene hablantes identificados: elige una hecha identificando quién habla."
    return True


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
