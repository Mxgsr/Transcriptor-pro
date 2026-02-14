# utils/validators.py
# Valida que la URL sea legítima y funcional
from urllib.parse import urlparse
import logging

from src.config import DOMINIOS_PERMITIDOS

logger = logging.getLogger(__name__)

def es_url(s: str) -> bool:
    """Verifica si un string tiene el formato básico de una URL."""
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")

def es_url_valida(url: str) -> bool:
    """Valida que la URL sea legítima y provenga de una lista segura."""
    try:
        result = urlparse(url)
        if not all([result.scheme in ('http', 'https'), result.netloc]):
            return False
            
        if not any(dominio in result.netloc.lower() for dominio in DOMINIOS_PERMITIDOS):
            logger.warning(f"⚠️ Advertencia: dominio no está en la lista blanca: {result.netloc}")
            logger.warning("Continuando de todas formas (puedes cancelar con Ctrl+C)...")           
        return True
    except Exception as e:
        logger.error(f"Error al validar URL: {e}")
        return False