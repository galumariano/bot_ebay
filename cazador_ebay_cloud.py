#!/usr/bin/env python3
"""
CAZADOR DE OFERTAS eBay -> Telegram  (v2)
=========================================
Cambios respecto de la v1:

  1. FILTRO POR CATEGORIA -> la solucion principal. Las fundas, teclados,
     protectores y repuestos estan en categorias distintas a las notebooks.
     Filtrando por categoria desaparecen solos.

  2. PRECIO MINIMO -> un accesorio de $25 nunca llega a tu aviso.

  3. PALABRAS OBLIGATORIAS -> el titulo TIENE que contener ciertas palabras.
     Filtrar por lo que si debe estar es mucho mas confiable que por lo que no.

  4. COINCIDENCIA POR PALABRA COMPLETA -> "locked" ya no coincide con
     "unlocked", ni "intel" con "intelligence", ni "air" con "repair".

  5. DETECCION DE NEGACIONES -> "no icloud lock" y "activation lock removed"
     ya no se descartan: son listados BUENOS.

  6. Los "-menos" salieron de la query: la Browse API no los soporta.

-------------------------------------------------------------------
SEGURIDAD
-------------------------------------------------------------------
Este archivo tiene tus claves adentro. Protegelo:
    chmod 600 cazador_ebay_v2.py
Y nunca lo subas a GitHub ni lo pegues en un chat.
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
# CREDENCIALES  (REGENERALAS: las anteriores quedaron expuestas)
# ===================================================================

EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "PEGA_TU_CLIENT_ID")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "PEGA_TU_CLIENT_SECRET")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "PEGA_TU_TOKEN_NUEVO")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PEGA_TU_CHAT_ID")

# ===================================================================
# CATEGORIAS DE eBAY
# ===================================================================
# Como verificar una categoria: abri un listado bueno en eBay y mira las
# migas de pan arriba de todo. O usa la Taxonomy API:
#   /commerce/taxonomy/v1/category_tree/0/get_category_subtree
# Si una categoria te filtra de mas, poné None y confia en el resto.

CAT_LAPTOPS_APPLE = "111422"   # Apple Laptops
CAT_CELULARES = "9355"         # Cell Phones & Smartphones
CAT_CARTAS = "183454"          # CCG Individual Cards

# ===================================================================
# BUSQUEDAS
# ===================================================================
# query        -> solo palabras positivas, SIN signos menos
# obligatorias -> lista de grupos. El titulo debe tener al menos una palabra
#                 de CADA grupo. Ej: [["macbook"], ["m2"], ["max"]]
# prohibidas   -> palabras completas que descartan el listado
# precio_min   -> tu mejor filtro anti-accesorio

BUSQUEDAS = [
    {
        "nombre": "MacBook Pro M2 Max 32GB",
        "query": "MacBook Pro M2 Max",
        "categoria": CAT_LAPTOPS_APPLE,
        "precio_min": 700,
        "precio_max": 1200,
        "obligatorias": [["macbook"], ["m2"], ["max"]],
        "prohibidas": ["air", "pro max only", "keyboard", "trackpad", "battery"],
    },
    {
        "nombre": "MacBook Pro M3 Pro",
        "query": "MacBook Pro M3 Pro",
        "categoria": CAT_LAPTOPS_APPLE,
        "precio_min": 700,
        "precio_max": 1400,
        "obligatorias": [["macbook"], ["m3"], ["pro"]],
        "prohibidas": ["air", "keyboard", "trackpad", "battery"],
    },
    {
        "nombre": "MacBook Pro M4 Pro",
        "query": "MacBook Pro M4 Pro",
        "categoria": CAT_LAPTOPS_APPLE,
        "precio_min": 800,
        "precio_max": 1500,
        "obligatorias": [["macbook"], ["m4"], ["pro"]],
        "prohibidas": ["air", "keyboard", "trackpad", "battery"],
    },
    {
        "nombre": "MacBook Pro M5 Pro",
        "query": "MacBook Pro M5 Pro",
        "categoria": CAT_LAPTOPS_APPLE,
        "precio_min": 1200,
        "precio_max": 2000,
        # OJO: exigimos la FRASE "m5 pro" junta. Si solo pidieramos ["m5"] y
        # ["pro"], entraria cualquier "MacBook Pro M5" base (el de $1.999),
        # porque el "Pro" del nombre del equipo ya cumple la condicion.
        "obligatorias": [["macbook"], ["m5 pro", "m5pro"]],
        "prohibidas": ["air", "max", "keyboard", "trackpad", "battery"],
    },
    {
        "nombre": "MacBook Pro M2 Max 16 pulgadas",
        "query": "MacBook Pro 16 M2 Max",
        "categoria": CAT_LAPTOPS_APPLE,
        "precio_min": 800,
        "precio_max": 1500,
        "obligatorias": [["macbook"], ["m2"], ["max"], ["16", "16.2"]],
        "prohibidas": ["air", "keyboard", "trackpad", "battery"],
    },
    {
        "nombre": "iPhone 17 Pro 256GB",
        "query": "iPhone 17 Pro 256GB unlocked",
        "categoria": CAT_CELULARES,
        "precio_min": 500,
        "precio_max": 800,
        # "17" obligatorio evita que entren 15, 16 y 18
        "obligatorias": [["iphone"], ["17"], ["pro"], ["256gb", "256"]],
        # sin "max": si querés el Max, esta la busqueda de abajo
        "prohibidas": ["max", "plus", "charger", "otterbox"],
    },
    {
        "nombre": "iPhone 17 Pro Max 256GB",
        "query": "iPhone 17 Pro Max 256GB unlocked",
        "categoria": CAT_CELULARES,
        "precio_min": 550,
        "precio_max": 900,
        "obligatorias": [["iphone"], ["17"], ["pro"], ["max"], ["256gb", "256"]],
        "prohibidas": ["charger", "otterbox"],
    },
    {
        "nombre": "Latias ex 239/191",
        "query": "Latias ex 239 japanese",
        "categoria": CAT_CARTAS,
        "precio_min": 20,
        "precio_max": 150,
        "obligatorias": [["latias"], ["239"]],
        "prohibidas": ["psa", "bgs", "cgc", "graded", "slab", "proxy",
                       "custom", "metal", "orica", "lot", "bundle"],
    },
    {
        "nombre": "Blastoise ex SAR 202/165",
        "query": "Blastoise ex SAR 202 165",
        "categoria": CAT_CARTAS,
        "precio_min": 20,
        "precio_max": 130,
        "obligatorias": [["blastoise"], ["202"]],
        "prohibidas": ["psa", "bgs", "cgc", "graded", "slab", "proxy",
                       "custom", "metal", "orica", "lot", "bundle"],
    },
    {
        "nombre": "Greninja 090/066",
        "query": "Greninja 090 066 japanese",
        "categoria": CAT_CARTAS,
        "precio_min": 30,
        "precio_max": 230,
        "obligatorias": [["greninja"], ["090"]],
        "prohibidas": ["psa", "bgs", "cgc", "graded", "slab", "proxy",
                       "custom", "metal", "orica", "lot", "bundle"],
    },
]

# ===================================================================
# FILTROS GLOBALES
# ===================================================================

FEEDBACK_MINIMO = 97.0
VENTAS_MINIMAS = 20

# Frases que siempre son malas, en cualquier categoria.
# Ojo: van como FRASES, no palabras sueltas, para no producir falsos positivos.
FRASES_PROHIBIDAS = [
    "for parts", "parts only", "not working", "no power", "as is",
    "as-is", "cracked", "broken", "damaged", "faulty", "defective",
    "read description", "read desc", "icloud locked", "activation locked",
    "carrier locked", "passcode locked", "bad esn", "blacklisted",
    "financed", "mdm", "no ssd", "no drive", "logic board only",
    "housing only", "shell only", "empty case", "box only",
    "screen replacement", "display assembly", "for repair", "needs repair",
]

# Si alguna de estas aparece cerca de una frase prohibida, NO se descarta.
# Ej: "no icloud lock", "activation lock removed", "clean esn"
NEGACIONES = ["no ", "not ", "never ", "without ", "clean ", "free of "]
LIBERACIONES = ["removed", "unlocked", "cleared", "free", "clean"]

ARCHIVO_VISTOS = Path(__file__).parent / "vistos.json"

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


# ===================================================================
# COINCIDENCIA POR PALABRA COMPLETA
# ===================================================================

def tiene_palabra(texto, palabra):
    """
    Busca la palabra completa, no como subcadena.

    Esto es lo que arregla el bug principal de la v1:
      tiene_palabra("iphone 17 pro unlocked", "locked")  -> False
      tiene_palabra("macbook pro repair kit", "air")     -> False
      tiene_palabra("apple intelligence ready", "intel") -> False
    """
    patron = r"(?<![a-z0-9])" + re.escape(palabra.lower()) + r"(?![a-z0-9])"
    return re.search(patron, texto.lower()) is not None


def frase_mala(titulo, frase):
    """Detecta una frase prohibida, salvo que este negada o liberada."""
    titulo = titulo.lower()
    for coincidencia in re.finditer(re.escape(frase), titulo):
        antes = titulo[max(0, coincidencia.start() - 14):coincidencia.start()]
        despues = titulo[coincidencia.end():coincidencia.end() + 14]

        if any(neg in antes for neg in NEGACIONES):
            continue  # "no icloud locked" -> es un listado BUENO
        if any(lib in despues for lib in LIBERACIONES):
            continue  # "activation locked ... removed" -> tambien bueno
        return True
    return False


def vale_la_pena(item, busqueda):
    """Devuelve (True/False, motivo) para poder depurar que se descarta."""
    titulo = item.get("title", "")
    if not titulo:
        return False, "sin titulo"

    # 1. Palabras obligatorias: cada grupo debe tener al menos una coincidencia
    for grupo in busqueda.get("obligatorias", []):
        if not any(tiene_palabra(titulo, palabra) for palabra in grupo):
            return False, f"le falta: {'/'.join(grupo)}"

    # 2. Frases prohibidas globales
    for frase in FRASES_PROHIBIDAS:
        if frase_mala(titulo, frase):
            return False, f"frase prohibida: {frase}"

    # 3. Palabras prohibidas propias de esta busqueda
    for palabra in busqueda.get("prohibidas", []):
        if tiene_palabra(titulo, palabra):
            return False, f"palabra prohibida: {palabra}"

    # 4. Reputacion del vendedor
    vendedor = item.get("seller", {}) or {}
    try:
        feedback = float(vendedor.get("feedbackPercentage", 0))
    except (TypeError, ValueError):
        feedback = 0.0
    if feedback < FEEDBACK_MINIMO:
        return False, f"feedback bajo: {feedback}%"
    if int(vendedor.get("feedbackScore", 0) or 0) < VENTAS_MINIMAS:
        return False, "vendedor con pocas ventas"

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
    precio_min = busqueda.get("precio_min", 0)
    precio_max = busqueda["precio_max"]

    filtros = ",".join([
        f"price:[{precio_min}..{precio_max}]",
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

    # El filtro mas importante de todos
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

    envio = "?"
    opciones_envio = item.get("shippingOptions") or []
    if opciones_envio:
        costo = opciones_envio[0].get("shippingCost", {}) or {}
        valor_envio = costo.get("value")
        if valor_envio is not None:
            try:
                envio = "gratis" if float(valor_envio) == 0 else f"${valor_envio}"
            except (TypeError, ValueError):
                envio = "?"

    opciones = item.get("buyingOptions", []) or []
    acepta_ofertas = "SI - regatea!" if "BEST_OFFER" in opciones else "no"

    vendedor = item.get("seller", {}) or {}
    condicion = item.get("condition", "?")
    ubicacion = (item.get("itemLocation", {}) or {}).get("stateOrProvince", "?")

    mensaje = (
        f"<b>[{nombre_busqueda}]</b>\n\n"
        f"{item.get('title', 'Sin titulo')}\n\n"
        f"<b>Precio:</b> {valor} {moneda}\n"
        f"<b>Envio:</b> {envio}\n"
        f"<b>Condicion:</b> {condicion}\n"
        f"<b>Acepta ofertas:</b> {acepta_ofertas}\n"
        f"<b>Vendedor:</b> {vendedor.get('feedbackPercentage', '?')}% "
        f"({vendedor.get('feedbackScore', '?')} ventas)\n"
        f"<b>Ubicacion:</b> {ubicacion}\n\n"
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


# ===================================================================
# PERSISTENCIA
# ===================================================================

def cargar_vistos():
    if ARCHIVO_VISTOS.exists():
        try:
            return set(json.loads(ARCHIVO_VISTOS.read_text()))
        except (ValueError, OSError):
            return set()
    return set()


def guardar_vistos(vistos):
    try:
        ARCHIVO_VISTOS.write_text(json.dumps(list(vistos)[-5000:]))
    except OSError as e:
        print(f"AVISO: no pude guardar vistos.json: {e}")


# ===================================================================
# CICLO PRINCIPAL
# ===================================================================

def una_ronda(silencioso=False, depurar=False):
    """Una pasada completa. Devuelve (avisos_enviados, listados_revisados)."""
    vistos = cargar_vistos()
    nuevos = 0
    revisados = 0

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
                if depurar:
                    print(f"    descartado ({motivo}): {item.get('title', '')[:70]}")
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
    return nuevos, revisados


def enviar_latido(enviados, revisados):
    """Mensaje diario para saber que el bot esta vivo."""
    mensaje = (
        f"<b>Latido diario</b>\n\n"
        f"El cazador esta funcionando.\n"
        f"Listados revisados hoy: {revisados}\n"
        f"Avisos enviados en esta ronda: {enviados}\n\n"
        f"<i>Si algun dia no llega este mensaje, algo se rompio.</i>"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"No pude enviar el latido: {e}")


def main():
    """Una sola ronda. El scheduler de GitHub Actions se encarga de repetir."""
    silencioso = "--silencioso" in sys.argv or os.environ.get("SILENCIOSO") == "1"
    depurar = "--depurar" in sys.argv or os.environ.get("DEPURAR") == "1"
    latido = "--latido" in sys.argv or os.environ.get("LATIDO") == "1"

    faltantes = [n for n, v in [
        ("EBAY_CLIENT_ID", EBAY_CLIENT_ID),
        ("EBAY_CLIENT_SECRET", EBAY_CLIENT_SECRET),
        ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
        ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
    ] if not v or v.startswith("PEGA_")]

    if faltantes:
        print(f"ERROR: faltan estos secrets: {', '.join(faltantes)}")
        print("Configuralos en: Settings -> Secrets and variables -> Actions")
        return 1

    try:
        enviados, revisados = una_ronda(silencioso=silencioso, depurar=depurar)
    except requests.RequestException as e:
        print(f"Error de red: {e}")
        return 1
    except Exception as e:
        print(f"Error inesperado: {e}")
        return 1

    estado = "cargados sin avisar" if silencioso else "avisos enviados"
    print(f"Ronda completa: {enviados} {estado}, {revisados} listados revisados.")

    if latido:
        enviar_latido(enviados, revisados)

    return 0


if __name__ == "__main__":
    sys.exit(main())
