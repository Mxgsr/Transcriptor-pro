Segunda versión de prueba de la V2. Para usarla todos los días sigue estando la **V1** (es la que instalan los instaladores).

## Novedades

- **Leer con el audio:** abre una página con la transcripción, un color por hablante y un reproductor. Haces clic en un párrafo y suena desde ahí; arriba hay un buscador. Funciona sin internet.
- **Buscar en todas:** busca una palabra o frase en todas tus transcripciones y te lleva al momento exacto.
- **Revisar frases dudosas:** cuando el programa duda de quién dijo una frase, te la muestra y puedes escucharla y corregirla.
- **Clave de Hugging Face guiada:** en Configuración, con los pasos y la comprobación de la clave.
- **Modelos y «Preparar la app»:** ves qué modelos tienes y cuánto pesan, y los descargas o eliminas. Antes de transcribir te avisa si falta uno.
- **Transcribir con clic derecho:** eliges «Transcribir con Transcriptor» en un audio o video y se abre una ventana con el avance; al terminar le pones nombre a quien habla.
- **Buscar actualizaciones:** en Configuración, para pasar a las versiones nuevas sin pegar la línea del instalador.
- «Mis transcripciones» ya no se limita a las últimas 15: **Ver más antiguas…**.

Desde la línea de comandos (`transcriptor transcribir ... --sin-preguntas`) todo funciona igual que en la V1.

## Instalar esta beta

Primero instala la V1 con el instalador normal. Después, en la misma ventana donde hiciste la instalación:
```
uv tool install --force --reinstall-package transcriptor-pro --python 3.11 "transcriptor-pro[diarizacion] @ https://github.com/Mxgsr/Transcriptor-pro/archive/refs/heads/v2.zip"
```

Si ya tienes la beta 1, **Configuración › Buscar actualizaciones** todavía no sirve (la beta 1 no la tiene): pega esta misma línea una vez. De la beta 2 en adelante, las actualizaciones se hacen desde Configuración.

Para volver a la V1, ejecuta otra vez el instalador normal.
