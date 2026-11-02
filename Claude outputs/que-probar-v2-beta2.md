# Qué probar en la V2-beta2 (solo para Max, no va en la release)

En Mac:
1. Leer con el audio, en Safari y en Chrome: clic en un párrafo reproduce desde ahí, se resalta el que suena, el buscador cuenta bien. Una reunión sin audio se ve sin reproductor.
2. Buscar en todas: con y sin tildes, elegir un resultado abre la lectura en ese minuto; «Ver más antiguas…».
3. Revisar frases dudosas con una reunión real: ¿propone demasiadas? ¿Escuchar, «Es de…» y «Está bien» funcionan, y el .txt se rehace bien (con su encabezado)?
4. Preparar la app y Modelos: descargar y eliminar un modelo chico (con avance), clave de Hugging Face (pegar una mala y una buena), y con «Sin internet» el aviso «Descargarlo ahora».
5. Clic derecho: que aparezca «Transcribir con Transcriptor» (Acciones rápidas), que abra una ventana de Terminal con el avance, que al terminar pregunte los nombres, y que varios archivos vayan uno tras otro. El .workflow está escrito a mano: es lo más probable que falle. Puede que el sistema pida permiso para leer Documentos o Escritorio la primera vez.
6. Buscar actualizaciones: sin novedades, y con una (puede probarse bajando la versión local); Actualizar ahora. Ojo: en tu copia de desarrollo (el .venv de la carpeta) dirá que esa copia no se instaló con el instalador; es a propósito. Pruébalo en el Mac de tu esposa o con una instalación hecha con el instalador.
7. El Grabador, tal como lo usas siempre (sin preguntas nuevas).

En Windows (un colega):
1. Leer con el audio en Edge: reproduce desde el párrafo y el buscador funciona.
2. Clic derecho: que aparezca en «Enviar a», que la ventana muestre el avance, pregunte los nombres al terminar y espere Enter para cerrarse. Probar también un archivo con «&» en el nombre (p. ej. «Ventas&Marketing.m4a»): puede fallar.
3. Buscar actualizaciones › Actualizar ahora: que se abra la ventana aparte, espere a que se cierre Transcriptor y actualice.
4. Modelos y clave de Hugging Face: descargar y eliminar un modelo, y comprobar la clave.
5. Revisar frases dudosas y Buscar en todas: que las tildes y la ñ se vean bien.
