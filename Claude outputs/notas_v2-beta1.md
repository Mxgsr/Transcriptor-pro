Versión de prueba de la V2. Para usarla todos los días sigue estando la **V1** (es la que instalan los instaladores).

## Novedades

- **Transcribir en 3 pasos:** arrastras el archivo o pegas el enlace en un solo campo, dices si identifico a quién habla (y cuántas personas son) y le pones nombre a la reunión. El modelo, el idioma y la carpeta están en «Más opciones…» y se cambian solo para esa vez.
- **Archivos con fecha y encabezado:** desde el menú, la transcripción se guarda como `2026-11-01 Reunión.blocks.txt` y arriba lleva el título, la fecha, la duración y los participantes.
- **Poner nombres con las flechas:** Ponerle nombre, Escuchar otra vez, Otro fragmento, Es la misma persona que… o Dejar como está. Los nombres que ya usaste se recuerdan para elegirlos de una lista.
- **Reconoce voces:** cuando le pones nombre a alguien, guarda su huella de voz solo en tu computador. La próxima vez te propone «Es Ana» y tú lo confirmas. Se apaga y se borran las voces en Configuración.
- **Copiar la transcripción** desde «¿Y ahora?» y «Mis transcripciones», para pegarla en Claude y hacer la minuta.
- **Errores más claros:** mensajes simples (falta la clave de Hugging Face, no hay internet, el archivo no es audio, el disco está lleno). El detalle queda en `~/.transcriptor/errores/` y se puede ver o copiar desde el menú.
- **No se duerme y avisa:** el computador no se suspende mientras transcribe, suena un aviso al terminar (si tardó más de un minuto) y, pasado el primer minuto, Ctrl+C pide confirmación.
- Menos jerga en el menú y textos generales, iguales en cualquier computador.

Desde la línea de comandos (`transcriptor transcribir ... --sin-preguntas`) todo funciona igual que en la V1.

## Instalar esta beta

Primero instala la V1 con el instalador normal. Después:

En la misma ventana donde hiciste la instalación:
```
uv tool install --force --reinstall-package transcriptor-pro --python 3.11 "transcriptor-pro[diarizacion] @ https://github.com/Mxgsr/Transcriptor-pro/archive/refs/heads/v2.zip"
```

Para volver a la V1, ejecuta otra vez el instalador normal.
