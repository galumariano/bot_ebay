#!/usr/bin/env python3
"""
CAZADOR DE OFERTAS eBay -> Telegram  (v3 - para GitHub Actions)
===============================================================
NOVEDADES DE ESTA VERSION, en respuesta a la basura que estaba pasando:

  1. EXTRACCION DE RAM desde el titulo -> descarta los de 8GB.
     Distingue los GB de memoria de los GB de disco.
  2. EXTRACCION DE PULGADAS -> descarta los de 16 si queres el de 14.
     No se confunde con "14-core GPU".
  3. EXCLUSION DE INTEL -> solo Apple Silicon.
  4. IDIOMA EN CARTAS -> exige japonesa, descarta china y coreana.
  5. LISTA DE PROBLEMAS AMPLIADA -> pantalla, bateria, agua, reparaciones.
  6. Si el titulo no dice la RAM, se puede exigir que igual la declare.
"""

import json
import os
import re
import sys
import time
import base64
from pathlib import Path

import requests

# ===================================================================
# CREDENCIALES (vienen de los Secrets de GitHub)
# ===================================================================

EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CAT_LAPTOPS_APPLE = "111422"
CAT_CELULARES = "9355"
CAT_CARTAS = "183454"

# ===================================================================
# BUSQUEDAS
# ===================================================================
# Campos nuevos:
#   ram_minima     -> descarta si el titulo declara menos GB que esto
#   exigir_ram     -> True: si el titulo no dice la RAM, se descarta
#   pulgadas       -> lista de tamanos aceptados, ej [14]
#   exigir_pulgadas-> True: si el titulo no dice el tamano, se descarta

BUSQUEDAS = [
    {
        "nombre": "MacBook Pro 14 M2 Max",
        "query": "MacBook Pro 14 M2 Max",
        "categoria": CAT_LAPTOPS_APPLE,
        "precio_min": 700,
        "precio_max": 1500,
        "obligatorias": [["macbook"], ["m2"], ["max"]],
        "prohibidas": ["air", "m1", "m3", "m4", "m5"],
        "ram_minima": 18,
        "exigir_ram": True,
        "pulgadas": [14],
        "exigir_pulgadas": False,
    },
  
    {
        "nombre": "MacBook Pro 14 M4 Pro",
        "query": "MacBook Pro 14 M4 Pro",
        "categoria": CAT_LAPTOPS_APPLE,
        "precio_min": 800,
        "precio_max": 1500,
        "obligatorias": [["macbook"], ["m4"], ["pro"]],
        "prohibidas": ["air", "m1", "m2", "m3", "m5", "max"],
        "ram_minima": 18,
        "exigir_ram": True,
        "pulgadas": [14],
        "exigir_pulgadas": False,
    },
    {
        "nombre": "MacBook Pro 14 M5 Pro",
        "query": "MacBook Pro 14 M5 Pro",
        "categoria": CAT_LAPTOPS_APPLE,
        "precio_min": 1200,
        "precio_max": 2000,
        "obligatorias": [["macbook"], ["m5 pro", "m5pro"]],
        "prohibidas": ["air", "max"],
        "ram_minima": 24,
        "exigir_ram": True,
        "pulgadas": [14],
        "exigir_pulgadas": False,
    },
    {
        "nombre": "iPhone 17 Pro 256GB",
        "query": "iPhone 17 Pro 256GB unlocked",
        "categoria": CAT_CELULARES,
        "precio_min": 500,
        "precio_max": 850,
        "obligatorias": [["iphone"], ["17"], ["pro"], ["256gb", "256"]],
        "prohibidas": ["max", "plus", "charger", "otterbox", "16", "15", "18"],
    },
    {
        "nombre": "iPhone 17 Pro Max 256GB",
        "query": "iPhone 17 Pro Max 256GB unlocked",
        "categoria": CAT_CELULARES,
        "precio_min": 550,
        "precio_max": 950,
        "obligatorias": [["iphone"], ["17"], ["pro"], ["max"], ["256gb", "256"]],
        "prohibidas": ["charger", "otterbox", "16", "15", "18"],
    },

     {
        "nombre": "iPhone 17 Pro Max 512GB",
        "query": "iPhone 17 Pro Max 512GB unlocked",
        "categoria": CAT_CELULARES,
        "precio_min": 550,
        "precio_max": 950,
        "obligatorias": [["iphone"], ["17"], ["pro"], ["max"], ["512gb", "512"]],
        "prohibidas": ["charger", "otterbox", "16", "15", "18"],
    },

  {
        "nombre": "iPhone 17 Pro 512GB",
        "query": "iPhone 17 Pro 512GB unlocked",
        "categoria": CAT_CELULARES,
        "precio_min": 500,
        "precio_max": 850,
        "obligatorias": [["iphone"], ["17"], ["pro"], ["512gb", "512"]],
        "prohibidas": ["max", "plus", "charger", "otterbox", "16", "15", "18"],
    },
   
]

# ===================================================================
# FILTROS GLOBALES
# ===================================================================

FEEDBACK_MINIMO = 97.0
VENTAS_MINIMAS = 20

RAM_VALIDAS = {8, 16, 18, 24, 32, 36, 48, 64, 96}

# Palabras sueltas que descalifican cualquier equipo electronico.
PALABRAS_MALAS_GLOBALES = [
    "intel", "i5", "i7", "i9", "core2", "duo",
    "broken", "cracked", "damaged", "faulty", "defective", "dented",
    "untested", "salvage", "scrap", "incomplete",
]

# Frases problematicas. Se ignoran si estan negadas ("no water damage").
FRASES_PROHIBIDAS = [
    # Estado general
    "for parts", "parts only", "parts/repair", "part or repair",
    "not working", "no power", "does not work", "doesn't work",
    "won't turn on", "wont turn on", "as is", "as-is",
    "read description", "read desc", "please read", "see description",
    "not functional", "non functional", "non-working",
    # Reparabilidad
    "cannot be repaired", "can not be repaired", "not repairable",
    "unrepairable", "beyond repair", "for repair", "needs repair",
    "repair needed", "as spares", "spares or repair",
    # Pantalla
    "screen issue", "screen issues", "screen damage", "screen problem",
    "lcd issue", "display issue", "dead pixel", "dead pixels",
    "bright spot", "dark spot", "burn in", "burn-in", "image retention",
    "ghosting", "lines on screen", "flickering", "stain on screen",
    "screen stain", "delamination", "anti glare wear", "flexgate",
    "cracked screen", "broken screen", "screen replaced",
    # Bateria y hardware
    "battery service", "service battery", "battery issue",
    "swollen battery", "battery replaced", "needs battery",
    "keyboard issue", "sticky key", "stuck key", "trackpad issue",
    "fan noise", "no audio", "speaker issue", "port issue",
    # Agua y golpes
    "water damage", "liquid damage", "corrosion", "bent frame",
    # Bloqueos
    "icloud locked", "activation locked", "carrier locked",
    "passcode locked", "bad esn", "bad imei", "blacklisted",
    "financed", "mdm", "remote management", "efi lock", "firmware lock",
    "no service", "face id not working", "no face id",
    "faceid issue", "true tone", "aftermarket screen", "aftermarket battery",
    "third party screen", "non genuine", "not genuine", "unknown part",
    "battery health 7", "battery health 6", "battery health 5",
    "back glass", "rear glass", "camera not working", "no camera",
    "speaker not working", "mic not working", "charging issue",
    "does not charge", "screen lifting", "touch not working",
    "ghost touch", "green line", "pink line", "burn mark",
    # Partes sueltas
    "logic board only", "housing only", "shell only", "empty case",
    "box only", "screen replacement", "display assembly",
    "top case", "bottom case", "no ssd", "no drive", "no hard drive",
    # Cartas
    "proxy", "custom made", "orica", "fan art", "not real", "reprint",
]

NEGACIONES = ["no ", "not ", "never ", "without ", "zero ", "free of ", "0 "]
LIBERACIONES = ["removed", "unlocked", "cleared", "free", "clean", "fixed",
                "replaced with new", "brand new"]

ARCHIVO_VISTOS = Path(__file__).parent / "vistos.json"

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


# ===================================================================
# ANALISIS DEL TITULO
# ===================================================================

def tiene_palabra(texto, palabra):
    """Palabra completa, no subcadena. 'locked' no coincide con 'unlocked'."""
    patron = r"(?<![a-z0-9])" + re.escape(palabra.lower()) + r"(?![a-z0-9])"
    return re.search(patron, texto.lower()) is not None


def extraer_ram(titulo):
    """GB de memoria, ignorando los GB de disco. None si no lo dice."""
    t = titulo.lower()
    candidatos = []

    for m in re.finditer(r"(\d{1,3})\s*gb", t):
        v = int(m.group(1))
        if v in RAM_VALIDAS:
            candidatos.append(v)

    for m in re.finditer(r"(?<![0-9])(\d{1,3})\s*/\s*(\d{3,4}|1tb|2tb|4tb)", t):
        v = int(m.group(1))
        if v in RAM_VALIDAS:
            candidatos.append(v)

    return min(candidatos) if candidatos else None


def extraer_pulgadas(titulo):
    """Tamano de pantalla. No se confunde con '14-core'. None si no lo dice."""
    t = titulo.lower()

    m = re.search(r"(?<![0-9])(13|14|15|16)(?:\.\d)?\s*-?\s*(?:inch|in\b|\"|”)", t)
    if m:
        return int(m.group(1))

    for m in re.finditer(r"(?<![a-z0-9.])(13|14|15|16)(?:\.\d)?(?![a-z0-9])", t):
        siguiente = t[m.end():m.end() + 10]
        if re.match(r"\s*-?\s*(core|gb|tb|hz|mm|w\b|cpu|gpu|:)", siguiente):
            continue
        return int(m.group(1))

    return None


def frase_mala(titulo, frase):
    """Detecta la frase, salvo que este negada o aclarada como resuelta."""
    t = titulo.lower()
    for c in re.finditer(re.escape(frase), t):
        antes = t[max(0, c.start() - 16):c.start()]
        despues = t[c.end():c.end() + 16]
        if any(n in antes for n in NEGACIONES):
            continue
        if any(l in despues for l in LIBERACIONES):
            continue
        return True
    return False


def vale_la_pena(item, busqueda):
    """Devuelve (pasa, motivo). El motivo sirve para depurar."""
    titulo = item.get("title", "")
    if not titulo:
        return False, "sin titulo"

    # 1. Palabras obligatorias
    for grupo in busqueda.get("obligatorias", []):
        if not any(tiene_palabra(titulo, p) for p in grupo):
            return False, f"le falta: {'/'.join(grupo)}"

    # 2. Palabras malas globales (Intel, roto, etc.)
    for palabra in PALABRAS_MALAS_GLOBALES:
        if tiene_palabra(titulo, palabra):
            return False, f"palabra mala: {palabra}"

    # 3. Frases problematicas
    for frase in FRASES_PROHIBIDAS:
        if frase_mala(titulo, frase):
            return False, f"problema: {frase}"

    # 4. Prohibidas propias de esta busqueda
    for palabra in busqueda.get("prohibidas", []):
        if tiene_palabra(titulo, palabra):
            return False, f"prohibida: {palabra}"

    # 5. RAM minima
    ram_minima = busqueda.get("ram_minima")
    if ram_minima:
        ram = extraer_ram(titulo)
        if ram is None:
            if busqueda.get("exigir_ram"):
                return False, "no declara la RAM"
        elif ram < ram_minima:
            return False, f"solo {ram}GB de RAM"

    # 6. Pulgadas
    pulgadas_ok = busqueda.get("pulgadas")
    if pulgadas_ok:
        pulg = extraer_pulgadas(titulo)
        if pulg is None:
            if busqueda.get("exigir_pulgadas"):
                return False, "no declara el tamano"
        elif pulg not in pulgadas_ok:
            return False, f'es de {pulg}"'

    # 7. Vendedor
    vendedor = item.get("seller", {}) or {}
    try:
        feedback = float(vendedor.get("feedbackPercentage", 0))
    except (TypeError, ValueError):
        feedback = 0.0
    if feedback < FEEDBACK_MINIMO:
        return False, f"feedback {feedback}%"
    if int(vendedor.get("feedbackScore", 0) or 0) < VENTAS_MINIMAS:
        return False, "vendedor nuevo"

    return True, "ok"


# ===================================================================
# eBAY
# ===================================================================

def obtener_token():
    credenciales = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()
    cabeceras = {
        "Authorization": "Basic " + base64.b64encode(credenciales).decode(),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    datos = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }
    r = requests.post(OAUTH_URL, headers=cabeceras, data=datos, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def buscar(token, busqueda):
    filtros = ",".join([
        f"price:[{busqueda.get('precio_min', 0)}..{busqueda['precio_max']}]",
        "priceCurrency:USD",
        "conditions:{USED|SELLER_REFURBISHED|CERTIFIED_REFURBISHED"
        "|EXCELLENT_REFURBISHED|VERY_GOOD_REFURBISHED|GOOD_REFURBISHED}",
        "buyingOptions:{FIXED_PRICE|BEST_OFFER}",
        "itemLocationCountry:US",
    ])

    parametros = {
        "q": busqueda["query"],
        "filter": filtros,
        "sort": "newlyListed",
        "limit": 50,
    }
    if busqueda.get("categoria"):
        parametros["category_ids"] = busqueda["categoria"]

    cabeceras = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    r = requests.get(BROWSE_URL, headers=cabeceras, params=parametros, timeout=30)
    r.raise_for_status()
    return r.json().get("itemSummaries", []) or []


# ===================================================================
# TELEGRAM
# ===================================================================

def avisar(item, nombre_busqueda):
    precio = item.get("price", {}) or {}
    valor = precio.get("value", "?")
    moneda = precio.get("currency", "USD")
    titulo = item.get("title", "Sin titulo")

    envio = "?"
    opciones_envio = item.get("shippingOptions") or []
    if opciones_envio:
        costo = opciones_envio[0].get("shippingCost", {}) or {}
        v = costo.get("value")
        if v is not None:
            try:
                envio = "gratis" if float(v) == 0 else f"${v}"
            except (TypeError, ValueError):
                envio = "?"

    opciones = item.get("buyingOptions", []) or []
    acepta = "SI - regatea!" if "BEST_OFFER" in opciones else "no"
    vendedor = item.get("seller", {}) or {}

    # Datos extraidos del titulo
    ram = extraer_ram(titulo)
    pulg = extraer_pulgadas(titulo)
    detalle = []
    if ram:
        detalle.append(f"{ram}GB RAM")
    if pulg:
        detalle.append(f'{pulg}"')
    linea_detalle = f"<b>Detectado:</b> {', '.join(detalle)}\n" if detalle else ""

    mensaje = (
        f"<b>[{nombre_busqueda}]</b>\n\n"
        f"{titulo}\n\n"
        f"<b>Precio:</b> {valor} {moneda}\n"
        f"<b>Envio:</b> {envio}\n"
        f"{linea_detalle}"
        f"<b>Condicion:</b> {item.get('condition', '?')}\n"
        f"<b>Acepta ofertas:</b> {acepta}\n"
        f"<b>Vendedor:</b> {vendedor.get('feedbackPercentage', '?')}% "
        f"({vendedor.get('feedbackScore', '?')} ventas)\n"
        f"<b>Ubicacion:</b> "
        f"{(item.get('itemLocation', {}) or {}).get('stateOrProvince', '?')}\n\n"
        f"{item.get('itemWebUrl', '')}"
    )

    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    r.raise_for_status()


def enviar_latido(enviados, revisados, descartados):
    mensaje = (
        f"<b>Latido diario</b>\n\n"
        f"El cazador esta funcionando.\n"
        f"Listados revisados: {revisados}\n"
        f"Descartados por los filtros: {descartados}\n"
        f"Avisos enviados: {enviados}\n\n"
        f"<i>Si un dia no llega este mensaje, algo se rompio.</i>"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"No pude enviar el latido: {e}")


# ===================================================================
# PERSISTENCIA
# ===================================================================

def cargar_vistos():
    if ARCHIVO_VISTOS.exists():
        try:
            datos = json.loads(ARCHIVO_VISTOS.read_text())
            return set(datos) if isinstance(datos, list) else set()
        except (ValueError, OSError):
            return set()
    return set()


def guardar_vistos(vistos):
    try:
        ARCHIVO_VISTOS.write_text(json.dumps(sorted(vistos)[-5000:]))
    except OSError as e:
        print(f"AVISO: no pude guardar vistos.json: {e}")


# ===================================================================
# PRINCIPAL
# ===================================================================

def una_ronda(silencioso=False, depurar=False):
    vistos = cargar_vistos()
    nuevos = 0
    revisados = 0
    descartados = 0

    token = obtener_token()

    for busqueda in BUSQUEDAS:
        try:
            resultados = buscar(token, busqueda)
        except requests.RequestException as e:
            print(f"  ERROR en '{busqueda['nombre']}': {e}")
            continue

        revisados += len(resultados)
        aceptados = 0

        for item in resultados:
            item_id = item.get("itemId")
            if not item_id or item_id in vistos:
                continue

            vistos.add(item_id)
            pasa, motivo = vale_la_pena(item, busqueda)

            if not pasa:
                descartados += 1
                if depurar:
                    print(f"    [{motivo}] {item.get('title', '')[:65]}")
                continue

            aceptados += 1
            nuevos += 1
            if silencioso:
                continue

            try:
                avisar(item, busqueda["nombre"])
                time.sleep(1)
            except requests.RequestException as e:
                print(f"  ERROR enviando a Telegram: {e}")

        print(f"  {busqueda['nombre']}: {len(resultados)} crudos -> {aceptados} utiles")

    guardar_vistos(vistos)
    return nuevos, revisados, descartados


def main():
    silencioso = "--silencioso" in sys.argv or os.environ.get("SILENCIOSO") == "1"
    depurar = "--depurar" in sys.argv or os.environ.get("DEPURAR") == "1"
    latido = "--latido" in sys.argv or os.environ.get("LATIDO") == "1"

    faltantes = [n for n, v in [
        ("EBAY_CLIENT_ID", EBAY_CLIENT_ID),
        ("EBAY_CLIENT_SECRET", EBAY_CLIENT_SECRET),
        ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
        ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
    ] if not v]

    if faltantes:
        print(f"ERROR: faltan estos secrets: {', '.join(faltantes)}")
        return 1

    try:
        enviados, revisados, descartados = una_ronda(silencioso, depurar)
    except requests.RequestException as e:
        print(f"Error de red: {e}")
        return 1
    except Exception as e:
        print(f"Error inesperado: {e}")
        return 1

    print(f"\nRonda completa: {revisados} revisados, "
          f"{descartados} descartados, {enviados} avisos.")

    if latido:
        enviar_latido(enviados, revisados, descartados)

    return 0


if __name__ == "__main__":
    sys.exit(main())
