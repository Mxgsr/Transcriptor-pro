# Ubicación: src/cli.py
# Interfaz de línea de comandos (comando `transcriptor`).
# Todo lo que se ve en pantalla vive aquí; la lógica sigue en src/procesador.py.
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
from src import fragmentos

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

PANEL_HABLANTES = "Hablantes"


@app.callback(invoke_without_command=True)
def principal(ctx: typer.Context):
    """
    🎙️  [bold]Transcriptor Pro[/]: transcribe audio y video (YouTube o archivos locales) con Whisper.

    Escribe solo [cyan]transcriptor[/] para elegir qué hacer en un menú con las flechas.

    Ejemplo: [cyan]transcriptor transcribir "https://youtu.be/..." -m small -d[/]
    """
    asegurar_ffmpeg()
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
                           detalle: bool = False, sin_preguntas: bool = False):
    """
    Transcribe con todo ya decidido (lo usan el comando `transcribir` y el menú).
    salida=None guarda junto al audio. Retorna el Resultado; si falla, lo muestra y sale con typer.Exit.
    """
    mapa_nombres = nombres or {}
    cabecera = f"\n [bold]Transcriptor Pro[/] · modelo [cyan]{modelo}[/]"
    if hablantes:
        cabecera += " · con hablantes"
    consola.print(cabecera + "\n")

    inicio = time.monotonic()
    try:
        # Importación diferida: así `transcriptor --help` responde al instante
        from src import procesador

        with _Pasos(consola, animado=not detalle) as pasos:
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
            )
    except KeyboardInterrupt:
        consola_err.print("\n[yellow]Cancelado.[/]")
        raise typer.Exit(130)
    except Exception as e:
        _mostrar_error(e, detalle)
        raise typer.Exit(1)

    # Con hablantes y sin nombres dados: ofrecemos escucharlos para ponerles nombre
    if resultado.json_path and not mapa_nombres and not sin_preguntas and _es_interactivo():
        try:
            hablantes = _hablantes_en_orden(resultado.parrafos)
            if _confirmar(f"\nSe detectaron {len(hablantes)} hablante(s). ¿Quieres escucharlos y ponerles nombre?"):
                mapa = _escuchar_y_nombrar(resultado.parrafos, {}, resultado.audio_path)
                if mapa:
                    _, resultado.parrafos = procesador.renombrar_hablantes(resultado.json_path, mapa)
        except (KeyboardInterrupt, EOFError):
            consola.print("\n[yellow]Nombres sin terminar.[/] Puedes retomarlo luego con [cyan]transcriptor nombres -e[/].")

    _mostrar_resumen(resultado, time.monotonic() - inicio)
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
            mapa_nombres = _escuchar_y_nombrar(datos["parrafos"], datos["nombres"], datos["audio"])
        txt_path, parrafos = procesador.renombrar_hablantes(archivo, mapa_nombres)
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


def _completar_modelo_corrector(incompleto: str) -> list:
    from src.corrector import MODELOS_CORRECTOR
    return [m for m in MODELOS_CORRECTOR if m.startswith(incompleto)]


@app.command()
def corregir(
    archivo: Annotated[Path, typer.Argument(
        metavar="ARCHIVO", show_default=False,
        help="El [cyan].blocks.json[/] (o el [cyan].blocks.txt[/]) de una transcripción.")],
    modelo: Annotated[Optional[str], typer.Option(
        "--modelo", "-m", autocompletion=_completar_modelo_corrector, show_default=False,
        help="Modelo de IA local: qwen3-4b (rápido), qwen3-8b, gemma4-e4b, o un repo de mlx-community. "
             "Por defecto, el de la configuración (qwen3-8b).")] = None,
    max_cambio: Annotated[int, typer.Option(
        "--max-cambio", min=1, max=100,
        help="Si el modelo cambia más de este % del texto de un párrafo, se queda el original "
             "(tildes, mayúsculas y puntuación no cuentan).")] = 15,
    revisar: Annotated[bool, typer.Option(
        "--revisar", "-r", help="Muestra cada cambio y te pregunta si aplicarlo.")] = False,
    vocabulario: Annotated[Optional[str], typer.Option(
        "--vocabulario", show_default=False,
        help='Nombres y siglas que aparecen en el audio, separados por comas ("COSAM, OSL, señorita Catalina"), '
             'para que la IA los escriba bien. Por defecto, el de la configuración; "" para no usar ninguno.')] = None,
    detalle: Annotated[bool, typer.Option(
        "--detalle", "-v", help="Muestra los mensajes internos de cada paso.")] = False,
):
    """
    Corrige ortografía, tildes, puntuación y palabras mal transcritas con una IA local (mlx-lm).

    Corrige párrafo a párrafo sin tocar las marcas de tiempo ni los hablantes, y guarda el resultado aparte en un [cyan].corregido.blocks.txt[/]; la transcripción original no cambia.

    Antes de la IA, y sin ella, quita las frases que Whisper repitió en bucle ("Gracias. Gracias. Gracias...") y escribe bien los nombres del vocabulario que Whisper oyó mal ("Cozán" -> "COSAM").

    [cyan]transcriptor corregir archivo.blocks.json -r[/] te deja revisar cada cambio antes de aplicarlo.
    """
    _configurar_logs(detalle)

    from src import ajustes, corrector, repeticiones

    modelo = modelo or ajustes.valor("modelo_corrector")
    vocabulario = corrector.preparar_vocabulario(
        vocabulario if vocabulario is not None else ajustes.valor("vocabulario"))
    try:
        repo = corrector.resolver_modelo(modelo)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--modelo") from None
    if revisar and not _es_interactivo():
        raise typer.BadParameter("--revisar necesita una terminal interactiva.", param_hint="--revisar")
    try:
        datos = corrector.leer_entrada(archivo)
    except json.JSONDecodeError as e:
        _mostrar_error(ValueError(f"El archivo no es un JSON válido (línea {e.lineno}, columna {e.colno})."), detalle)
        raise typer.Exit(1)
    except Exception as e:
        _mostrar_error(e, detalle)
        raise typer.Exit(1)

    # Sin IA: la salvaguarda rechazaría a la IA si quitara un bucle largo (cambia demasiado texto)
    antes = datos["parrafos"]
    datos["parrafos"] = repeticiones.limpiar_parrafos(antes, guardar_original=True)
    parrafos = datos["parrafos"]
    sin_bucles = sum(1 for a, b in zip(antes, parrafos) if a["text"].strip() != b["text"])
    # Sin IA: la IA casi nunca cambia un nombre mal oído por el del vocabulario
    datos["parrafos"], nombres_arreglados = corrector.aplicar_vocabulario(parrafos, vocabulario, guardar_original=True)
    parrafos = datos["parrafos"]
    consola.print(f"\n [bold]Transcriptor Pro[/] · corrigiendo con [cyan]{modelo}[/] · {len(parrafos)} párrafos\n")
    if vocabulario:
        consola.print(f" [dim]Vocabulario: {escape(vocabulario)}[/]\n")

    inicio = time.monotonic()
    correcciones, interrumpido = [], False
    try:
        with _Pasos(consola, animado=not detalle) as pasos:
            if corrector.modelo_descargado(repo):
                pasos("Cargando modelo")
            else:
                pasos("Descargando modelo")
            generar = corrector.cargar_generador(repo, silencioso=not detalle, vocabulario=vocabulario)
            pasos("Corrigiendo")
            try:
                for correccion in corrector.corregir_parrafos(parrafos, generar, max_cambio / 100, vocabulario):
                    correcciones.append(correccion)
                    pasos.progresar(len(correcciones), len(parrafos), "párrafos")
            except KeyboardInterrupt:
                interrumpido = True
                pasos.fallar("Interrumpido")
    except KeyboardInterrupt:
        consola_err.print("\n[yellow]Cancelado. No se guardó nada.[/]")
        raise typer.Exit(130)
    except Exception as e:
        _mostrar_error(e, detalle)
        raise typer.Exit(1)

    procesados = len(correcciones)
    if not procesados:
        consola_err.print("\n[yellow]Cancelado. No se guardó nada.[/]")
        raise typer.Exit(130)
    correcciones = corrector.completar(parrafos, correcciones)

    revision_cortada = False
    if revisar and not interrumpido:
        revision_cortada = _revisar_cambios(parrafos, datos["nombres"], correcciones, corrector)

    try:
        txt_path, json_path = corrector.guardar_correccion(datos, correcciones)
    except Exception as e:
        _mostrar_error(e, detalle)
        raise typer.Exit(1)

    _mostrar_resumen_correccion(txt_path, parrafos, correcciones, corrector, procesados,
                                time.monotonic() - inicio, revision_cortada, sin_bucles, nombres_arreglados)
    return txt_path


def _revisar_cambios(parrafos: list, nombres: dict, correcciones: list, corrector) -> bool:
    """
    Muestra cada cambio propuesto y pregunta si aplicarlo. Los que digas que no quedan como estaban.
    Retorna True si la revisión se cortó (Ctrl+C): los que faltaban se descartan.
    """
    pendientes = [i for i, c in enumerate(correcciones) if c.estado == corrector.APLICADA]
    if not pendientes:
        return False
    consola.print(f"\n[bold]{_plural(len(pendientes), 'párrafo')} con cambios.[/] "
                  "[dim]Enter o s: aplicar · n: dejar el original · t: aplicar todos los que quedan[/]")
    numero = 1
    try:
        for numero, i in enumerate(pendientes, 1):
            parrafo, correccion = parrafos[i], correcciones[i]
            cabecera = f"[{_reloj(parrafo['start'])}]"
            if parrafo.get("speaker"):
                cabecera += f" {nombres.get(parrafo['speaker'], parrafo['speaker'])}"
            consola.print()
            consola.rule(f"{cabecera} · {numero} de {len(pendientes)}", align="left")
            consola.print(_diferencias(correccion.original, correccion.propuesta))
            respuesta = consola.input("¿Aplicar? [bold][S/n/t][/] ").strip().lower()
            if respuesta == "t":
                break
            if respuesta in ("n", "no"):
                correccion.estado = corrector.DESCARTADA
    except (KeyboardInterrupt, EOFError):
        for i in pendientes[numero - 1:]:
            correcciones[i].estado = corrector.DESCARTADA
        consola.print("\n[yellow]Revisión cortada: los cambios que faltaban por revisar no se aplicaron.[/]")
        return True
    return False


def _diferencias(original: str, propuesta: str) -> Text:
    """El párrafo con lo quitado tachado en rojo y lo nuevo en verde."""
    import difflib

    a, b = original.split(), propuesta.split()
    texto = Text()
    for operacion, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if operacion == "equal":
            texto.append(" ".join(a[i1:i2]) + " ")
            continue
        if i2 > i1:
            texto.append(" ".join(a[i1:i2]), style="red strike")
            texto.append(" ")
        if j2 > j1:
            texto.append(" ".join(b[j1:j2]), style="bold green")
            texto.append(" ")
    texto.rstrip()
    return texto


def _mostrar_resumen_correccion(txt_path: Path, parrafos: list, correcciones: list, corrector,
                                procesados: int, segundos: float, revision_cortada: bool,
                                sin_bucles: int = 0, nombres_arreglados: int = 0):
    cuenta = {}
    for c in correcciones:
        cuenta[c.estado] = cuenta.get(c.estado, 0) + 1

    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style="bold")
    tabla.add_column(overflow="fold")
    tabla.add_row("Corregido", str(txt_path))
    tabla.add_row("Cambios", f"{cuenta.get(corrector.APLICADA, 0)} de {len(parrafos)} párrafos")
    if sin_bucles:
        tabla.add_row("Repeticiones", f"quitadas en {_plural(sin_bucles, 'párrafo')}")
    if nombres_arreglados:
        tabla.add_row("Vocabulario", f"{nombres_arreglados} "
                                     f"{'nombre corregido' if nombres_arreglados == 1 else 'nombres corregidos'}")
    if procesados < len(parrafos):
        tabla.add_row("Revisados", Text(
            f"solo los primeros {procesados}; el resto quedó como estaba.", style="yellow"))
    if cuenta.get(corrector.DESCARTADA):
        tabla.add_row("Descartados", f"{cuenta[corrector.DESCARTADA]} por ti")
    rechazados = [i for i, c in enumerate(correcciones) if c.estado == corrector.RECHAZADA]
    if rechazados:
        horas = ", ".join(_reloj(parrafos[i]["start"]) for i in rechazados[:6])
        if len(rechazados) > 6:
            horas += "…"
        tabla.add_row("Sin aplicar", Text(
            f"{_plural(len(rechazados), 'párrafo')} {'cambiaba' if len(rechazados) == 1 else 'cambiaban'} "
            f"demasiado y {'se quedó como estaba' if len(rechazados) == 1 else 'se quedaron como estaban'} ({horas}). "
            f"La propuesta está en el .json, en \"correccion_no_aplicada\".", style="yellow"))
    tabla.add_row("Tiempo total", _duracion(segundos))

    consola.print()
    if procesados < len(parrafos):
        titulo, color = "Interrumpido: se guardó lo corregido hasta ahí", "yellow"
    elif revision_cortada:
        titulo, color = "Listo, con la revisión a medias", "yellow"
    else:
        titulo, color = "Listo", "green"
    consola.print(Panel(tabla, title=titulo, title_align="left", border_style=color, expand=False))


def _anotar_en_historial(resultado):
    """Para la lista de "Mis transcripciones" del menú. Si no se puede, la transcripción sigue igual de bien."""
    try:
        from src import historial
        historial.registrar(resultado.txt_path, resultado.json_path, resultado.audio_path, resultado.duracion)
    except Exception as e:
        logging.getLogger(__name__).debug(f"No se pudo anotar en el historial: {e}")


def _plural(cantidad: int, palabra: str) -> str:
    return f"{cantidad} {palabra}" + ("" if cantidad == 1 else "s")


def _es_interactivo() -> bool:
    """Solo preguntamos si hay una persona delante (no en scripts ni con la salida redirigida)."""
    return sys.stdin.isatty() and consola.is_terminal


def _confirmar(pregunta: str) -> bool:
    respuesta = consola.input(f"{pregunta} [bold][S/n][/] ").strip().lower()
    return respuesta in ("", "s", "si", "sí", "y", "yes")


def _hablantes_en_orden(parrafos: list) -> list:
    hablantes = []
    for p in parrafos:
        if p.get("speaker") and p["speaker"] not in hablantes:
            hablantes.append(p["speaker"])
    return hablantes


def _escuchar_y_nombrar(parrafos: list, nombres_actuales: dict, audio: Optional[Path]) -> dict:
    """
    Para cada hablante muestra lo que dice y reproduce un fragmento de su voz; luego pregunta su nombre.
    parrafos lleva las etiquetas originales ("Hablante 1"...). Retorna {etiqueta: nombre} con lo que cambió.
    """
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

    consola.print("[dim]Escribe el nombre y Enter · Enter solo: dejarlo como está · "
                  "r: repetir el fragmento · o: escuchar otro fragmento[/]")
    mapa = {}
    with tempfile.TemporaryDirectory(prefix="transcriptor-") as carpeta:
        try:
            for etiqueta in _hablantes_en_orden(parrafos):
                actual = nombres_actuales.get(etiqueta, etiqueta)
                opciones = fragmentos.elegir_fragmentos(parrafos, etiqueta)
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
                    respuesta = consola.input(f"Nombre para [bold]{actual}[/]: ").strip()
                    mostrar = True
                    if respuesta.lower() == "r":
                        continue
                    if respuesta.lower() == "o":
                        if len(opciones) > 1:
                            indice = (indice + 1) % len(opciones)
                        else:
                            consola.print("[dim]No hay más fragmentos de este hablante.[/]")
                            mostrar = False
                        continue
                    if reproductor:
                        reproductor.detener()
                    if respuesta and respuesta != actual:
                        mapa[etiqueta] = respuesta
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
    if detalle:
        consola_err.print_exception()
    mensaje = Text(str(e) or type(e).__name__)
    if not detalle:
        mensaje.append("\n\nVuelve a ejecutarlo con -v para ver el detalle.", style="dim")
    consola_err.print(Panel(mensaje, title="Error", title_align="left", border_style="red", expand=False))


def _mostrar_resumen(resultado, segundos: float):
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
    if resultado.json_path:
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
