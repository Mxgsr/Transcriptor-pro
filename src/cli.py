# Ubicación: src/cli.py
# Interfaz de línea de comandos (comando `transcriptor`).
# Todo lo que se ve en pantalla vive aquí; la lógica sigue en src/procesador.py.
import contextlib
import json
import logging
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Annotated, Optional

import typer
import typer.rich_utils
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, Progress, ProgressColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.spinner import Spinner
from rich.table import Column, Table
from rich.text import Text

from src.diarizer import parsear_nombres
from src.ffmpeg_local import asegurar_ffmpeg
from src import aviso, errores, fragmentos

# Títulos de la ayuda en español (Typer los trae en inglés)
typer.rich_utils.ARGUMENTS_PANEL_TITLE = "Argumentos"
typer.rich_utils.OPTIONS_PANEL_TITLE = "Opciones"
typer.rich_utils.COMMANDS_PANEL_TITLE = "Comandos"
typer.rich_utils.ERRORS_PANEL_TITLE = "Error"
typer.rich_utils.ABORTED_TEXT = "Cancelado."
typer.rich_utils.DEFAULT_STRING = "[por defecto: {}]"
typer.rich_utils.REQUIRED_LONG_STRING = "[obligatorio]"

app = typer.Typer(
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Pantalla normal (progreso y resumen) y pantalla de errores y avisos
consola = Console()
consola_err = Console(stderr=True)

# Archivo con el detalle del último error mostrado (None si no hubo). Se limpia al empezar cada comando;
# el menú lo usa para ofrecer «Ver el detalle» y «Copiar el error».
ultimo_error: Optional[Path] = None

# Desde cuántos segundos de trabajo se pide confirmar Ctrl+C y se avisa al terminar
SEGUNDOS_TRABAJO_LARGO = 60

PANEL_HABLANTES = "Hablantes"


@app.callback(invoke_without_command=True)
def principal(ctx: typer.Context):
    """
    🎙️  [bold]Transcriptor Pro[/]: transcribe audio y video (YouTube o archivos locales) con Whisper.

    Escribe solo [cyan]transcriptor[/] para elegir qué hacer en un menú con las flechas.

    Ejemplo: [cyan]transcriptor transcribir "https://youtu.be/..." -m small -d[/]
    """
    asegurar_ffmpeg()
    # Antes de que alguna librería importe huggingface_hub, que lee HF_HUB_OFFLINE al importarse
    from src import ajustes
    ajustes.aplicar_sin_internet()
    if ctx.invoked_subcommand is not None:
        return
    # Sin comando: en una terminal, el menú; en un script (sin nadie que responda), la ayuda
    if not _es_interactivo():
        typer.echo(ctx.get_help())
        raise typer.Exit()
    from src import menu
    menu.iniciar()


def _completar_modelo(incompleto: str) -> list:
    # Importación diferida: src.transcriber carga mlx_whisper, que tarda en importarse
    from src.transcriber import MODELOS_MLX
    return [m for m in MODELOS_MLX if m.startswith(incompleto)]


@app.command()
def transcribir(
    entrada: Annotated[str, typer.Argument(
        metavar="ENTRADA", help="URL de YouTube o ruta a un archivo de audio o video.", show_default=False)],
    modelo: Annotated[Optional[str], typer.Option(
        "--modelo", "-m", autocompletion=_completar_modelo, show_default=False,
        help="Modelo de Whisper: tiny, base, small, medium, large, turbo, o un repo de Hugging Face. "
             "Por defecto, el de la configuración.")] = None,
    hablantes: Annotated[bool, typer.Option(
        "--hablantes", "-d", rich_help_panel=PANEL_HABLANTES,
        help="Identifica quién habla en cada momento (requiere HF_TOKEN en el .env).")] = False,
    num: Annotated[Optional[int], typer.Option(
        "--num", min=1, show_default=False, rich_help_panel=PANEL_HABLANTES,
        help="Número exacto de hablantes, si lo sabes (mejora la precisión).")] = None,
    minimo: Annotated[Optional[int], typer.Option(
        "--min", min=1, show_default=False, rich_help_panel=PANEL_HABLANTES,
        help="Número mínimo de hablantes esperado.")] = None,
    maximo: Annotated[Optional[int], typer.Option(
        "--max", min=1, show_default=False, rich_help_panel=PANEL_HABLANTES,
        help="Número máximo de hablantes esperado.")] = None,
    nombres: Annotated[Optional[str], typer.Option(
        "--nombres", "-n", show_default=False, rich_help_panel=PANEL_HABLANTES,
        help='Nombres en orden de aparición ("Ana,Luis") o por número ("2=Luis,1=Ana").')] = None,
    idioma: Annotated[Optional[str], typer.Option(
        "--idioma", "-i", show_default=False,
        help="Idioma del audio (código de dos letras: es, en, pt...). Por defecto, el de la configuración (es).")] = None,
    salida: Annotated[Optional[Path], typer.Option(
        "--salida", "-o", show_default=False,
        help="Carpeta donde guardar la transcripción (por defecto, la de la configuración o junto al audio).")] = None,
    detalle: Annotated[bool, typer.Option(
        "--detalle", "-v", help="Muestra los mensajes internos de cada paso.")] = False,
    sin_preguntas: Annotated[bool, typer.Option(
        "--sin-preguntas", help="No pregunta nada al terminar (útil en scripts).")] = False,
):
    """Transcribe una URL o un archivo y guarda el texto en un [cyan].blocks.txt[/]."""
    _configurar_logs(detalle)

    # Estas opciones solo tienen sentido identificando hablantes: lo activamos, pero avisando
    usadas = [opcion for opcion, valor in
              (("--num", num), ("--min", minimo), ("--max", maximo), ("--nombres", nombres))
              if valor is not None]
    if usadas and not hablantes:
        consola_err.print(f"[yellow]ℹ Activé la identificación de hablantes porque usaste {', '.join(usadas)}.[/]")
        hablantes = True

    try:
        mapa_nombres = parsear_nombres(nombres)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--nombres") from None

    # Lo que no se indica sale de la configuración (menú Configuración, o el .env)
    from src import ajustes
    return ejecutar_transcripcion(
        entrada,
        modelo or ajustes.valor("modelo"),
        hablantes=hablantes,
        num=num,
        minimo=minimo,
        maximo=maximo,
        nombres=mapa_nombres,
        idioma=idioma or ajustes.valor("idioma"),
        salida=salida or ajustes.carpeta("carpeta_salida"),
        carpeta_descargas=ajustes.carpeta("carpeta_descargas"),
        detalle=detalle,
        sin_preguntas=sin_preguntas,
    )


def ejecutar_transcripcion(entrada: str, modelo: str, hablantes: bool = False, num: Optional[int] = None,
                           minimo: Optional[int] = None, maximo: Optional[int] = None, nombres: Optional[dict] = None,
                           idioma: str = "es", salida: Optional[Path] = None, carpeta_descargas: Optional[Path] = None,
                           detalle: bool = False, sin_preguntas: bool = False, desde_menu: bool = False,
                           titulo: Optional[str] = None, fecha=None):
    """
    Transcribe con todo ya decidido (lo usan el comando `transcribir` y el menú).
    salida=None guarda junto al audio. Retorna el Resultado; si falla, lo muestra y sale con typer.Exit.
    desde_menu: los avisos no nombran comandos (quien usa el menú no los conoce).
    titulo y fecha (date o AAAA-MM-DD) los manda el menú: nombran el archivo y ponen el encabezado.
    """
    global ultimo_error
    ultimo_error = None
    mapa_nombres = nombres or {}
    cabecera = f"\n [bold]Transcriptor Pro[/] · modelo [cyan]{modelo}[/]"
    if hablantes:
        cabecera += " · con hablantes"
    consola.print(cabecera + "\n")

    inicio = time.monotonic()
    # Con una persona delante: Ctrl+C pide confirmación pasado el primer minuto y se avisa al terminar
    con_persona = not sin_preguntas and _es_interactivo()
    confirmar = (aviso.confirmar_cancelar(despues_de=SEGUNDOS_TRABAJO_LARGO,
                                          avisar=lambda texto: consola.print(f"[yellow]{texto}[/]"))
                 if con_persona else contextlib.nullcontext())
    try:
        # Importación diferida: así `transcriptor --help` responde al instante
        from src import procesador

        # sin_dormir siempre (también en scripts y en el Grabador): no cambia nada visible
        with aviso.sin_dormir(), confirmar, _Pasos(consola, animado=not detalle) as pasos:
            resultado = procesador.procesar_entrada(
                entrada,
                modelo,
                diarizar=hablantes,
                nombres=mapa_nombres,
                num_hablantes=num,
                min_hablantes=minimo,
                max_hablantes=maximo,
                idioma=idioma,
                salida=salida,
                carpeta_descargas=carpeta_descargas,
                al_avanzar=pasos,
                al_fallar=pasos.fallar,
                # Con -v se ven las barras propias de yt-dlp y mlx-whisper
                al_progresar=None if detalle else pasos.progresar,
                silenciar_motores=not detalle,
                titulo=titulo,
                fecha=fecha,
            )
    except KeyboardInterrupt:
        consola_err.print("\n[yellow]Cancelado.[/]")
        raise typer.Exit(130)
    except Exception as e:
        _mostrar_error(e, detalle)
        raise typer.Exit(1)

    # Si tardó, la persona pudo irse a otra cosa: la avisamos ANTES de preguntar por los nombres
    if con_persona and time.monotonic() - inicio > SEGUNDOS_TRABAJO_LARGO:
        nombre_listo = Path(resultado.txt_path).name.removesuffix(".blocks.txt")
        aviso.notificar("Transcripción lista", f"Listo: {nombre_listo}, {_duracion(resultado.duracion)}")

    # Nombres dados con --nombres: los recordamos para ofrecerlos la próxima vez
    if resultado.json_path and mapa_nombres:
        _recordar_personas(mapa_nombres.values())
        _guardar_voces(mapa_nombres, resultado.huellas, resultado.json_path)

    # Con hablantes y sin nombres dados: ofrecemos escucharlos para ponerles nombre
    if resultado.json_path and not mapa_nombres and not sin_preguntas and _es_interactivo():
        try:
            from src import menu
            cuantos = len(_hablantes_en_orden(resultado.parrafos))
            consola.print()
            if _quiere_poner_nombres(menu, cuantos):
                sugerencias = _sugerir_por_voz(resultado.huellas, {}, resultado.parrafos)
                mapa = _escuchar_y_nombrar(resultado.parrafos, {}, resultado.audio_path, sugerencias)
                if mapa:
                    # Solo lo confirmado: si cortó a mitad (Ctrl+C), nada llega aquí y no se guarda nada
                    _guardar_voces(mapa, resultado.huellas, resultado.json_path)
                    _, resultado.parrafos = procesador.renombrar_hablantes(resultado.json_path, mapa)
                    _recordar_personas(mapa.values())
        except (KeyboardInterrupt, EOFError):
            if desde_menu:
                consola.print("\n[yellow]Nombres sin terminar.[/] Puedes terminarlo luego en «Cambiar nombres de hablantes».")
            else:
                consola.print("\n[yellow]Nombres sin terminar.[/] Puedes retomarlo luego con [cyan]transcriptor nombres -e[/].")

        _ofrecer_revision_dudosas(resultado, desde_menu)

    _mostrar_resumen(resultado, time.monotonic() - inicio, desde_menu)
    _anotar_en_historial(resultado)
    return resultado


@app.command("nombres")
def poner_nombres(
    archivo: Annotated[Path, typer.Argument(
        metavar="ARCHIVO", help="El [cyan].blocks.json[/] de una transcripción hecha con --hablantes.",
        show_default=False)],
    lista: Annotated[Optional[str], typer.Argument(
        metavar="LISTA", show_default=False,
        help='Nombres en orden de aparición ("Ana,Luis") o por número ("2=Luis,1=Ana"). '
             "Sin lista, rehace el .txt con los nombres que tenga el .json (por si lo editaste a mano).")] = None,
    escuchar: Annotated[bool, typer.Option(
        "--escuchar", "-e",
        help="Reproduce un fragmento de cada hablante y te pregunta su nombre.")] = False,
):
    """
    Pone nombre a los hablantes de una transcripción ya hecha, sin volver a procesar el audio.

    [cyan]transcriptor nombres archivo.blocks.json -e[/] te deja escuchar a cada hablante antes de nombrarlo.
    Si editaste los nombres directamente en el [cyan].blocks.json[/], sin lista rehace el .txt con ellos.
    """
    _configurar_logs(detalle=False)
    global ultimo_error
    ultimo_error = None

    archivo = archivo.expanduser()
    if archivo.suffix != ".json" or not archivo.exists():
        raise typer.BadParameter(f"No encuentro el archivo .json: {archivo}", param_hint="ARCHIVO")
    if escuchar and lista:
        raise typer.BadParameter("Usa una lista de nombres o --escuchar, no los dos a la vez.", param_hint="LISTA")
    if escuchar and not _es_interactivo():
        raise typer.BadParameter("--escuchar necesita una terminal interactiva.", param_hint="--escuchar")
    try:
        mapa_nombres = parsear_nombres(lista)
    except ValueError as e:
        raise typer.BadParameter(str(e).replace("En --nombres, ", ""), param_hint="LISTA") from None

    from src import procesador

    try:
        if escuchar:
            datos = procesador.leer_transcripcion(archivo)
            sugerencias = _sugerir_por_voz(datos["huellas"], datos["nombres"], datos["parrafos"])
            mapa_nombres = _escuchar_y_nombrar(datos["parrafos"], datos["nombres"], datos["audio"], sugerencias)
        txt_path, parrafos = procesador.renombrar_hablantes(archivo, mapa_nombres)
        _recordar_personas(mapa_nombres.values())
        if mapa_nombres:
            _guardar_voces_del_json(archivo, procesador)
    except (KeyboardInterrupt, EOFError):
        consola_err.print("\n[yellow]Cancelado. No se cambió nada.[/]")
        raise typer.Exit(130)
    except json.JSONDecodeError as e:
        _mostrar_error(ValueError(
            f"El archivo no es un JSON válido (línea {e.lineno}, columna {e.colno}). "
            "Revisa que no falte una coma o unas comillas cerca de ahí."), detalle=False)
        raise typer.Exit(1)
    except Exception as e:
        _mostrar_error(e, detalle=False)
        raise typer.Exit(1)

    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style="bold")
    tabla.add_column(overflow="fold")
    tabla.add_row("Transcripción", str(txt_path))
    tabla.add_row("Hablantes", _texto_hablantes(parrafos))
    titulo = "Nombres aplicados" if mapa_nombres or escuchar else "Transcripción actualizada desde el .json"
    consola.print(Panel(tabla, title=titulo, title_align="left", border_style="green", expand=False))
    return txt_path


def _anotar_en_historial(resultado):
    """Para la lista de "Mis transcripciones" del menú. Si no se puede, la transcripción sigue igual de bien."""
    try:
        from src import historial
        historial.registrar(resultado.txt_path, resultado.json_path, resultado.audio_path, resultado.duracion)
    except Exception as e:
        logging.getLogger(__name__).debug(f"No se pudo anotar en el historial: {e}")


def _es_interactivo() -> bool:
    """Solo preguntamos si hay una persona delante (no en scripts ni con la salida redirigida)."""
    return sys.stdin.isatty() and consola.is_terminal


def _recordar_personas(nombres):
    """Guarda los nombres usados para ofrecerlos la próxima vez. Un fallo aquí nunca debe romper nada."""
    try:
        from src import historial
        historial.recordar_personas(list(nombres))
    except Exception as e:
        logging.getLogger(__name__).debug(f"No se pudieron recordar las personas: {e}")


def _reconocer_voces_activo() -> bool:
    """¿Está encendido «Reconocer voces»? Ante cualquier fallo, no (nada de esto debe romper)."""
    try:
        from src import ajustes
        return bool(ajustes.valor("reconocer_voces"))
    except Exception as e:
        logging.getLogger(__name__).debug(f"No se pudo leer el ajuste de reconocer voces: {e}")
        return False


def _sugerir_por_voz(huellas: Optional[dict], nombres_actuales: dict, parrafos: list) -> dict:
    """
    {etiqueta: nombre} con las personas que la voz recuerda, solo para quien aún tiene nombre genérico
    ("Hablante N"). Avisa en gris a quiénes reconoció. Son solo propuestas: se confirman al escucharlas.
    Vacío si el ajuste está apagado, no hay huellas o algo falla.
    """
    if not huellas or not _reconocer_voces_activo():
        return {}
    try:
        from src import voces
        from src.diarizer import ETIQUETA_GENERICA
        en_la_charla = set(_hablantes_en_orden(parrafos))
        sugerencias = {}
        for etiqueta, (nombre, _) in voces.parecidos(huellas).items():
            actual = nombres_actuales.get(etiqueta, etiqueta)
            if etiqueta in en_la_charla and actual.startswith(f"{ETIQUETA_GENERICA} ") and actual[len(ETIQUETA_GENERICA) + 1:].isdigit():
                sugerencias[etiqueta] = nombre
        if sugerencias:
            # En el orden en que aparecen en la charla
            nombres = [sugerencias[e] for e in _hablantes_en_orden(parrafos) if e in sugerencias]
            consola.print(f"[dim]Reconocí por la voz a: {', '.join(nombres)}. Confírmalo al escuchar a cada uno.[/]")
        return sugerencias
    except Exception as e:
        logging.getLogger(__name__).debug(f"No se pudo reconocer por la voz: {e}")
        return {}


def _guardar_voces(nombres: dict, huellas: Optional[dict], json_path: Optional[Path] = None):
    """
    Guarda la huella de voz de quienes ya tienen nombre ({etiqueta: nombre} completo), para
    reconocerlos la próxima vez. Con json_path cada huella sabe de dónde viene: volver a guardar
    no la suma dos veces y, si se corrigió un nombre, se quita de la persona equivocada.
    Un fallo aquí nunca debe romper nada.
    """
    if not nombres or not huellas or not _reconocer_voces_activo():
        return
    try:
        from src import voces
        fuente = str(Path(json_path).expanduser().resolve()) if json_path else None
        voces.recordar_nombrados(nombres, huellas, fuente)
    except Exception as e:
        logging.getLogger(__name__).debug(f"No se pudieron guardar las voces: {e}")


def _guardar_voces_del_json(json_path: Path, procesador):
    """Tras aplicar nombres a un .blocks.json: guarda las voces con los nombres que quedaron (los del .json
    más los nuevos). Si se repite un nombre («la misma persona que…»), se guardan las dos huellas."""
    if not _reconocer_voces_activo():
        return
    try:
        datos = procesador.leer_transcripcion(json_path)
        _guardar_voces(datos["nombres"], datos["huellas"], json_path)
    except Exception as e:
        logging.getLogger(__name__).debug(f"No se pudieron guardar las voces: {e}")


def _quiere_poner_nombres(menu, cuantos: int) -> bool:
    """Pregunta (con flechas) si quiere ponerles nombre. Esc o «Ahora no» es que no."""
    mensaje = ("Se detectó 1 hablante. ¿Le pongo nombre?" if cuantos == 1
               else f"Se detectaron {cuantos} hablantes. ¿Les pongo nombre?")
    try:
        return menu.elegir(mensaje, [("Sí, escucharlos y ponerles nombre", True)], texto_volver="Ahora no")
    except menu.Atras:
        return False


def _hablantes_en_orden(parrafos: list) -> list:
    hablantes = []
    for p in parrafos:
        if p.get("speaker") and p["speaker"] not in hablantes:
            hablantes.append(p["speaker"])
    return hablantes


# Valores de las listas de _escuchar_y_nombrar
_NOMBRE, _REPETIR, _OTRO_FRAGMENTO, _MISMA, _SUGERIDO = "nombre", "repetir", "otro_fragmento", "misma", "sugerido"
_OTRO_NOMBRE = "otro_nombre"


def _validar_nombre(texto: str):
    return True if texto.strip() else "Escribe un nombre."


def _pedir_nombre(menu, ocupados: set) -> str:
    """
    Con personas guardadas: lista con ellas (menos las ya usadas en esta transcripción) y «Otro nombre…».
    Sin personas: directo a escribir. Esc (menu.Atras) sube a quien llama.
    """
    try:
        from src import historial
        guardadas = [p for p in historial.personas() if p not in ocupados]
    except Exception:
        guardadas = []
    if guardadas:
        eleccion = menu.elegir("¿Cómo se llama?", [*guardadas, ("Otro nombre…", _OTRO_NOMBRE)])
        if eleccion != _OTRO_NOMBRE:
            return eleccion
    return menu.texto("Nombre:", validar=_validar_nombre).strip()


def _escuchar_y_nombrar(parrafos: list, nombres_actuales: dict, audio: Optional[Path],
                        sugerencias: Optional[dict] = None) -> dict:
    """
    Para cada hablante muestra lo que dice, reproduce un fragmento de su voz y pregunta con flechas quién es.
    parrafos lleva las etiquetas originales ("Hablante 1"...). Retorna {etiqueta: nombre} con lo que cambió.

    Punto de extensión (reconocimiento de voz): sugerencias es {etiqueta: nombre}. Si hay una para un
    hablante, la primera opción de su lista (y la elegida por defecto) es «Es <nombre>»; el resto queda igual.
    Sin sugerencias (None) no cambia nada.

    Esc en la lista de un hablante es «Dejar como está»; Esc en una sublista vuelve a esa lista.
    Ctrl+C sube como KeyboardInterrupt (quien llama decide qué hacer).
    """
    from src import menu

    sugerencias = sugerencias or {}
    comando = fragmentos.comando_reproductor() if audio else None
    if audio is None:
        consola.print("[yellow]No encuentro el audio de esta transcripción; te muestro solo el texto.[/]")
    elif comando is None:
        consola.print("[yellow]No hay un reproductor de audio disponible; te muestro solo el texto.[/]")
    reproductor = fragmentos.Reproductor(comando) if comando else None

    tiempos = {}
    for p in parrafos:
        if p.get("speaker"):
            tiempos[p["speaker"]] = tiempos.get(p["speaker"], 0.0) + max(0.0, p["end"] - p["start"])
    total = sum(tiempos.values()) or 1.0

    etiquetas = _hablantes_en_orden(parrafos)
    mapa = {}

    def nombre_de(etiqueta):
        return mapa.get(etiqueta, nombres_actuales.get(etiqueta, etiqueta))

    with tempfile.TemporaryDirectory(prefix="transcriptor-") as carpeta:
        try:
            for posicion, etiqueta in enumerate(etiquetas):
                actual = nombre_de(etiqueta)
                opciones = fragmentos.elegir_fragmentos(parrafos, etiqueta)
                anteriores = etiquetas[:posicion]
                consola.print()
                consola.rule(f"[bold]{actual}[/] · habla el {round(100 * tiempos[etiqueta] / total)} % del tiempo",
                             align="left")
                indice, mostrar = 0, True
                while True:
                    if mostrar and opciones:
                        fragmento = opciones[indice]
                        texto = fragmento["text"].strip()
                        if len(texto) > 280:
                            texto = texto[:280].rsplit(" ", 1)[0] + "…"
                        consola.print(f"[dim][{_reloj(fragmento['start'])}][/] {texto}")
                        if reproductor:
                            _reproducir_fragmento(reproductor, audio, fragmento, Path(carpeta) / f"{etiqueta}-{indice}.wav")
                    mostrar = True

                    sugerido = sugerencias.get(etiqueta)
                    # Si ese nombre ya se le dio a otro hablante en esta pasada, ya no se propone:
                    # un Enter uniría a dos personas distintas (para eso está «Es la misma persona que…»)
                    if sugerido in {nombre_de(e) for e in etiquetas if e != etiqueta}:
                        sugerido = None
                    lista = []
                    if sugerido:
                        lista.append((f"Es {sugerido}", _SUGERIDO))
                    lista.append(("Ponerle nombre", _NOMBRE))
                    if reproductor:
                        lista.append(("Escuchar otra vez", _REPETIR))
                    if len(opciones) > 1:
                        lista.append(("Otro fragmento", _OTRO_FRAGMENTO))
                    # Los anteriores con otro nombre (sin repetir): a quién más puede ser
                    candidatos = list(dict.fromkeys(nombre_de(e) for e in anteriores if nombre_de(e) != actual))
                    if candidatos:
                        lista.append(("Es la misma persona que…", _MISMA))
                    try:
                        eleccion = menu.elegir(f"¿Quién es {actual}?", lista, defecto=lista[0][1],
                                               texto_volver="Dejar como está")
                    except menu.Atras:
                        eleccion = None  # Esc / «Dejar como está»

                    if eleccion == _REPETIR:
                        continue
                    if eleccion == _OTRO_FRAGMENTO:
                        indice = (indice + 1) % len(opciones)
                        continue

                    nuevo = None
                    if eleccion == _SUGERIDO:
                        nuevo = sugerido
                    elif eleccion == _NOMBRE:
                        ocupados = {nombre_de(e) for e in etiquetas if e != etiqueta}
                        try:
                            nuevo = _pedir_nombre(menu, ocupados)
                        except menu.Atras:
                            mostrar = False
                            continue
                    elif eleccion == _MISMA:
                        try:
                            nuevo = menu.elegir("¿Con quién?", candidatos)
                        except menu.Atras:
                            mostrar = False
                            continue

                    if reproductor:
                        reproductor.detener()
                    if nuevo and nuevo != actual:
                        mapa[etiqueta] = nuevo
                    break
        finally:
            if reproductor:
                reproductor.detener()
    return mapa


def _reproducir_fragmento(reproductor, audio: Path, fragmento: dict, destino: Path):
    """Recorta (una sola vez) y reproduce hasta SEGUNDOS_POR_FRAGMENTO del párrafo elegido."""
    try:
        if not destino.exists():
            duracion = min(fragmentos.SEGUNDOS_POR_FRAGMENTO, fragmento["end"] - fragmento["start"])
            fragmentos.extraer_fragmento(audio, fragmento["start"], duracion, destino)
        reproductor.reproducir(destino)
    except Exception as e:
        consola.print(f"[yellow]No se pudo reproducir el fragmento ({e}).[/]")



# --- Revisar frases dudosas ----------------------------------------------------

def _contar_dudosas(json_path) -> int:
    """Cuántas frases dudosas tiene una transcripción (0 si no hay .json o no se puede leer)."""
    if not json_path:
        return 0
    try:
        from src import dudosas
        from utils.formatters import cargar_transcripcion
        datos = cargar_transcripcion(Path(json_path))
        return len(dudosas.buscar_dudosas(datos["parrafos"], nombres=datos["nombres"]))
    except Exception as e:
        logging.getLogger(__name__).debug(f"No se pudieron contar las frases dudosas: {e}")
        return 0


def _ofrecer_revision_dudosas(resultado, desde_menu: bool = False):
    """
    Al terminar de transcribir (solo con una persona delante): ofrece revisar las frases en las que
    se dudó de quién habla. Un fallo aquí nunca debe estropear una transcripción ya hecha.
    """
    try:
        from src import menu, procesador

        n = _contar_dudosas(resultado.json_path)
        if not n:
            return
        mensaje = (f"Hay {n} frases en las que dudé de quién habla. ¿Las revisamos?" if n > 1
                   else "Hay 1 frase en la que dudé de quién habla. ¿La revisamos?")
        consola.print()
        try:
            quiere = menu.elegir(mensaje, [("Sí, revisarlas", True)],
                                 texto_volver="Ahora no (puedes hacerlo luego desde la transcripción)")
        except menu.Atras:
            quiere = False
        if quiere and _revisar_dudosas(resultado.json_path, menu):
            # Los porcentajes del resumen deben reflejar lo corregido
            resultado.parrafos = procesador.renombrar_hablantes(resultado.json_path, {})[1]
    except (KeyboardInterrupt, EOFError):
        consola.print("\n[yellow]Revisión sin terminar.[/] Puedes retomarla luego desde la transcripción.")
    except Exception as e:
        logging.getLogger(__name__).debug(f"No se pudo ofrecer la revisión de frases dudosas: {e}")


def _recortar_final(texto: str, largo: int = 120) -> str:
    """Las últimas palabras de un texto largo (lo que está pegado a la frase que sigue)."""
    texto = " ".join(texto.split())
    return texto if len(texto) <= largo else "…" + texto[-largo:].lstrip()


def _recortar_inicio(texto: str, largo: int = 120) -> str:
    """El principio de un texto largo."""
    texto = " ".join(texto.split())
    return texto if len(texto) <= largo else texto[:largo].rstrip() + "…"


def _mostrar_dudosa(parrafos: list, d, nombres: dict, posicion: int, total: int):
    """Muestra el párrafo anterior (atenuado), el de la frase con ella resaltada, y el siguiente (atenuado)."""
    from src import dudosas

    def nombre(etiqueta):
        return dudosas.nombre_visible(etiqueta, nombres)

    consola.print()
    consola.rule(f"[bold]Frase {posicion} de {total}[/] · [{_reloj(d.start)}]", align="left")
    if d.indice > 0:
        antes = parrafos[d.indice - 1]
        consola.print(Text(f"{nombre(antes.get('speaker') or '')}: {_recortar_final(antes.get('text', ''))}", style="dim"))
    texto = " ".join((parrafos[d.indice].get("text") or "").split())
    # La misma posición que usará mover_frase (palabras enteras; si se repite, la de su minuto)
    pos = dudosas.posicion_en_parrafo(parrafos[d.indice], d)
    linea = Text(f"{nombre(d.actual)}: ", style="bold cyan")
    if pos < 0:
        linea.append(texto)
    else:
        linea.append(texto[:pos])
        linea.append(d.texto, style="bold yellow")
        linea.append(texto[pos + len(d.texto):])
    consola.print(linea)
    if d.indice + 1 < len(parrafos):
        despues = parrafos[d.indice + 1]
        consola.print(Text(f"{nombre(despues.get('speaker') or '')}: {_recortar_inicio(despues.get('text', ''))}", style="dim"))
    consola.print()


def _revisar_dudosas(json_path: Path, menu) -> int:
    """
    Repasa una por una las frases en las que se dudó de quién habla y deja corregirlas con flechas.
    Retorna cuántas frases se pasaron a otra persona. Al terminar (fin, «Terminar la revisión», Esc o
    Ctrl+C) guarda lo hecho, así lo revisado no se vuelve a proponer.
    """
    from src import dudosas, procesador

    datos = procesador.leer_transcripcion(Path(json_path))
    parrafos, nombres, audio = datos["parrafos"], datos["nombres"], datos["audio"]
    total = len(dudosas.buscar_dudosas(parrafos, nombres=nombres))
    if not total:
        consola.print("[dim]No hay frases dudosas.[/]")
        return 0

    comando = fragmentos.comando_reproductor() if audio else None
    reproductor = fragmentos.Reproductor(comando) if comando else None
    cambiadas = revisadas = 0
    omitidas = set()  # frases que no se pudieron resolver: no se vuelven a proponer (evita repetir sin fin)

    def clave(d):
        return (d.texto, round(d.start, 2), d.otro)

    try:
        with tempfile.TemporaryDirectory(prefix="transcriptor-") as carpeta:
            while True:
                # Se recalcula cada vez: al mover una frase los índices de los párrafos cambian
                pendientes = [d for d in dudosas.buscar_dudosas(parrafos, nombres=nombres) if clave(d) not in omitidas]
                if not pendientes:
                    break
                d = pendientes[0]
                revisadas += 1
                total = max(total, revisadas)
                _mostrar_dudosa(parrafos, d, nombres, revisadas, total)

                actual, otro = dudosas.nombre_visible(d.actual, nombres), dudosas.nombre_visible(d.otro, nombres)
                demas = [e for e in _hablantes_en_orden(parrafos) if e not in (d.actual, d.otro)]
                lista = []
                if reproductor:
                    lista.append(("Escuchar", "escuchar"))
                lista.append((f"Es de {otro}", "otro"))
                lista.append((f"Está bien (es de {actual})", "bien"))
                if demas:
                    lista.append(("Es de otra persona…", "otra"))

                nuevo = None
                while True:
                    try:
                        eleccion = menu.elegir("¿De quién es la frase marcada?", lista, texto_volver="Terminar la revisión")
                    except menu.Atras:
                        eleccion = "terminar"
                    if eleccion == "escuchar":
                        fragmento = {"start": max(0.0, d.start - 0.5), "end": d.end + 0.5}
                        _reproducir_fragmento(reproductor, audio, fragmento, Path(carpeta) / f"dudosa-{revisadas}.wav")
                        continue
                    if eleccion == "otra":
                        try:
                            nuevo = menu.elegir("¿De quién es?", [(dudosas.nombre_visible(e, nombres), e) for e in demas])
                        except menu.Atras:
                            continue
                        eleccion = "mover"
                    break

                if eleccion == "terminar":
                    break
                if eleccion in ("otro", "mover"):
                    nuevo = d.otro if eleccion == "otro" else nuevo
                    nuevos = dudosas.mover_frase(parrafos, d, nuevo)
                    if nuevos != parrafos:
                        parrafos, cambiadas = nuevos, cambiadas + 1
                        continue
                    # No se pudo mover (la frase ya no está en su párrafo): se deja como está
                nuevos = dudosas.marcar_bien(parrafos, d)
                if nuevos == parrafos:
                    omitidas.add(clave(d))
                parrafos = nuevos
    except (KeyboardInterrupt, EOFError):
        consola.print("\n[dim]Revisión interrumpida: guardo lo que llevabas.[/]")
    finally:
        if reproductor:
            reproductor.detener()

    # Sin cambios ni marcas (se terminó de inmediato) no hay nada que guardar
    if not cambiadas and parrafos == datos["parrafos"]:
        return 0
    try:
        dudosas.guardar(Path(json_path), parrafos)
    except Exception as e:
        _mostrar_error(e, detalle=False)
        return 0
    if cambiadas:
        consola.print(f"[green]✓[/] Corregí {cambiadas} {'frase' if cambiadas == 1 else 'frases'}.")
    else:
        consola.print("[green]✓[/] Revisión guardada.")
    return cambiadas


class _ColumnaEstado(ProgressColumn):
    """Spinner mientras el paso avanza; ✓ o ✗ cuando termina."""

    def __init__(self):
        super().__init__()
        self.spinner = Spinner("dots", style="cyan")

    def render(self, task):
        if task.fields.get("fallo"):
            return Text("✗", style="red")
        if task.finished:
            return Text("✓", style="green")
        return self.spinner.render(task.get_time())


class _ColumnaDetalle(ProgressColumn):
    """Cuánto lleva el paso actual ('12:30 / 42:10' de audio, '3.1 / 12.4 MB') y cuánto falta."""

    def render(self, task):
        texto = Text(style="dim")
        unidad = task.fields.get("unidad")
        if task.total is not None and unidad == "audio":
            texto.append(f"{_reloj(task.completed)} / {_reloj(task.total)}")
        elif task.total is not None and unidad == "bytes":
            texto.append(f"{task.completed / 1e6:.1f} / {task.total / 1e6:.1f} MB")
        elif task.total is not None and unidad == "párrafos":
            texto.append(f"{int(task.completed)} / {int(task.total)} párrafos")
        restante = task.time_remaining
        if not task.finished and task.total is not None and restante is not None:
            texto.append(("  " if texto else "") + f"quedan {_duracion(restante)}", style="yellow")
        return texto


class _Pasos:
    """
    Muestra cada paso del proceso. Se llama con el nombre del paso que empieza
    (es el al_avanzar de procesar_entrada) y cierra el anterior.
    Con animado=False (modo detalle) solo escribe una línea por paso, para no pisar los logs.
    """

    def __init__(self, consola: Console, animado: bool = True):
        self.consola = consola
        self.animado = animado
        self.tarea = None
        # Mientras no hay datos de avance, la barra se mueve sin porcentaje
        self.progreso = Progress(
            TextColumn(" "),
            _ColumnaEstado(),
            TextColumn("{task.description:<23}"),
            BarColumn(bar_width=None, table_column=Column(ratio=1)),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            _ColumnaDetalle(table_column=Column(no_wrap=True)),
            console=consola,
        )

    def __call__(self, paso: str):
        if not self.animado:
            self.consola.print(f"[bold cyan]▸ {paso}[/]")
            return
        self._cerrar_paso()
        self.tarea = self.progreso.add_task(paso, total=None, unidad=None)

    def progresar(self, completado: float, total, unidad=None):
        """Avance dentro del paso actual. Sin total conocido, la barra sigue sin porcentaje."""
        if self.tarea is None:
            return
        self.progreso.update(self.tarea, completed=completado, total=total, unidad=unidad)

    def fallar(self, motivo: str):
        """Marca el paso actual con ✗ sin detener el proceso (el motivo se muestra en el resumen)."""
        if not self.animado:
            self.consola.print(f"[bold red]✗ {motivo}[/]")
            return
        self._cerrar_paso(fallo=True)

    def _cerrar_paso(self, fallo: bool = False):
        if self.tarea is None:
            return
        tarea = next(t for t in self.progreso.tasks if t.id == self.tarea)
        if fallo:
            self.progreso.update(self.tarea, fallo=True)
            self.progreso.stop_task(self.tarea)
        elif tarea.total is None:
            self.progreso.update(self.tarea, total=1, completed=1)
        else:
            self.progreso.update(self.tarea, completed=tarea.total)
        self.tarea = None

    def __enter__(self):
        if self.animado:
            self.progreso.start()
        return self

    def __exit__(self, tipo, valor, traza):
        if self.animado:
            self._cerrar_paso(fallo=tipo is not None)
            self.progreso.stop()
        return False


def _configurar_logs(detalle: bool):
    """Sin -v solo se ven los avisos; los errores ya se muestran en su propio recuadro."""
    handler = RichHandler(console=consola_err, show_path=False, log_time_format="[%X]")
    if not detalle:
        handler.addFilter(lambda registro: registro.levelno < logging.ERROR)
    if not detalle:
        # Avisos técnicos de las librerías de IA (p. ej. "std(): degrees of freedom is <= 0" de pyannote)
        warnings.filterwarnings("ignore", module=r"(pyannote|torch|torchaudio|lightning|pytorch_lightning|speechbrain)(\.|$)")
    logging.basicConfig(
        level=logging.INFO if detalle else logging.WARNING,
        format="%(message)s",
        handlers=[handler],
        force=True,
    )


def _mostrar_error(e: Exception, detalle: bool):
    global ultimo_error
    if detalle:
        consola_err.print_exception()
    mensaje = Text(errores.mensaje_simple(e) or str(e) or type(e).__name__)
    if _falta_modelo_sin_internet(e):  # tiene prioridad: la causa real es el modo «Sin internet»
        mensaje = Text("Está activado «Sin internet» y ese modelo todavía no está descargado. "
                       "Desactívalo en Configuración (o quita HF_HUB_OFFLINE del .env) para descargarlo.")
    # El detalle va a un archivo para poder pedir ayuda sin abrir la terminal con -v
    ultimo_error = errores.guardar_detalle(e)
    if ultimo_error:
        mensaje.append(f"\n\nEl detalle quedó guardado en {errores.ruta_corta(ultimo_error)}", style="dim")
    consola_err.print(Panel(mensaje, title="Error", title_align="left", border_style="red", expand=False))


def _falta_modelo_sin_internet(e: Exception) -> bool:
    """True si el error es de huggingface_hub porque el modelo no está descargado y no puede ir a buscarlo."""
    from src import ajustes
    if not ajustes.sin_internet_activo():
        return False
    while e is not None:
        if type(e).__name__ in ("OfflineModeIsEnabled", "LocalEntryNotFoundError"):
            return True
        e = e.__cause__ or e.__context__
    return False


def _mostrar_resumen(resultado, segundos: float, desde_menu: bool = False):
    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style="bold")
    tabla.add_column(overflow="fold")
    tabla.add_row("Transcripción", str(resultado.txt_path))
    tabla.add_row("Audio", _duracion(resultado.duracion))
    if resultado.error_hablantes:
        tabla.add_row("Hablantes", Text(
            f"no se pudieron identificar ({resultado.error_hablantes}). "
            "La transcripción se guardó sin ellos.", style="yellow"))
    elif resultado.json_path:
        tabla.add_row("Hablantes", _texto_hablantes(resultado.parrafos))
    tabla.add_row("Tiempo total", _duracion(segundos))
    if resultado.json_path and not desde_menu:
        tabla.add_row("", "")
        tabla.add_row("Cambiar nombres", f'transcriptor nombres "{resultado.json_path}" -e')

    consola.print()
    if resultado.error_hablantes:
        titulo, color = "Listo, sin hablantes", "yellow"
    else:
        titulo, color = "Listo", "green"
    consola.print(Panel(tabla, title=titulo, title_align="left", border_style=color, expand=False))


def _texto_hablantes(parrafos: list) -> str:
    """'Ana (61 %), Luis (39 %)': cuánto tiempo habla cada uno, en orden de aparición."""
    tiempos = {}
    for p in parrafos:
        if p.get("speaker"):
            tiempos[p["speaker"]] = tiempos.get(p["speaker"], 0.0) + max(0.0, p["end"] - p["start"])
    total = sum(tiempos.values())
    if not tiempos:
        return "ninguno detectado"
    if not total:
        return ", ".join(tiempos)
    return ", ".join(f"{nombre} ({round(100 * t / total)} %)" for nombre, t in tiempos.items())


def _reloj(segundos: float) -> str:
    """Convierte segundos a '42:10' o '1:02:05'."""
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _duracion(segundos: float) -> str:
    """Convierte segundos a un texto corto: '3 s', '1 min 48 s', '1 h 02 min'."""
    segundos = int(round(segundos))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


# ---------------------------------------------------------------------------
# Clic derecho: «Transcribir con Transcriptor» (comando oculto, ver src/clic_derecho.py)
# ---------------------------------------------------------------------------
def _hablantes_para_clic_derecho() -> bool:
    """Con hablantes si Configuración no dice «nunca» y se puede: disponible aquí, pyannote instalado y con clave."""
    import importlib.util
    from src import ajustes, config, plataforma

    if ajustes.valor("modo_hablantes") == ajustes.NUNCA:
        return False
    if not plataforma.hablantes_disponible() or not config.HF_TOKEN:
        return False
    try:
        return importlib.util.find_spec("pyannote.audio") is not None
    except (ImportError, ValueError):
        return False


@app.command("en-fila", hidden=True)
def en_fila(
    archivos: Annotated[list[Path], typer.Argument(metavar="ARCHIVO...", show_default=False,
                                                   help="Audios o videos a transcribir, uno tras otro.")],
):
    """Lo llama el clic derecho: transcribe los archivos uno tras otro, sin preguntas, y avisa al terminar cada uno."""
    from src import ajustes, clic_derecho

    # Nadie mira la terminal: cada resultado se avisa con una notificación
    algun_fallo = False
    candado = clic_derecho.tomar_candado(
        al_esperar=lambda: consola.print("[yellow]Hay otra transcripción en curso: espero mi turno…[/]"))
    try:
        for archivo in archivos:
            if not archivo.is_file():
                consola_err.print(f"[yellow]Salto {escape(archivo.name or str(archivo))}: no encuentro el archivo.[/]")
                continue
            if not clic_derecho.es_audio_o_video(archivo):
                consola_err.print(f"[yellow]Salto {escape(archivo.name)}: no parece un audio ni un video.[/]")
                continue

            from src import menu  # importación diferida: solo para fecha_de_grabacion
            try:
                resultado = ejecutar_transcripcion(
                    str(archivo),
                    ajustes.valor("modelo"),
                    hablantes=_hablantes_para_clic_derecho(),
                    idioma=ajustes.valor("idioma"),
                    salida=ajustes.carpeta("carpeta_salida"),
                    carpeta_descargas=ajustes.carpeta("carpeta_descargas"),
                    sin_preguntas=True,
                    desde_menu=True,
                    titulo=archivo.stem,
                    fecha=menu.fecha_de_grabacion(str(archivo)),
                )
            except (typer.Exit, Exception):  # el detalle ya lo guardó _mostrar_error
                algun_fallo = True
                aviso.notificar("No pude transcribir", f"{archivo.name}. Abre Transcriptor para ver el detalle.")
                continue
            aviso.notificar("Transcripción lista", f"Listo: {archivo.stem}, {_duracion(resultado.duracion or 0)}")
    finally:
        clic_derecho.soltar_candado(candado)

    raise typer.Exit(1 if algun_fallo else 0)
