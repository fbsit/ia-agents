"""
Genera los documentos de conocimiento de Emporio Sura a partir de los archivos crudos
exportados del sistema (catalogo CSV + politicas MD) y los deja en
backend/knowledge_base/demo-ventas-wsp/.

Reglas:
- Se conservan los SKU tal cual: los usa el checkout (ClubHx). Solo se normalizan nombre,
  categoria, marca, moneda y se extrae la presentacion (170 g, 750 ml) cuando esta en el nombre.
- No se inventa nada. Lo que no esta en el sistema queda en PENDIENTES-DUENO.md (no se indexa)
  y en el documento de politicas se instruye al agente a derivar a un humano.

Uso: python backend/scripts/build_emporio_sura_knowledge.py <carpeta_origen> [<carpeta_destino>]
"""
from __future__ import annotations

import csv
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Felipe\Desktop\emporio-sura-rag")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "backend/knowledge_base/demo-ventas-wsp")
DST.mkdir(parents=True, exist_ok=True)

STORE = "Emporio Sura"
# Tarifas de despacho por sector (configuracion real de zonas; todas con entrega el mismo dia).
DESPACHO = [
    ("Coronel Centro", 1000), ("Escuadron", 1500), ("Schwager", 2000), ("Escuadron Sur", 2000),
    ("Villa Mora", 2500), ("Yobilo", 3000), ("Lagunillas", 3500), ("Camilo Olavarria", 4000),
    ("Lo Rojas", 4500), ("Maule", 5000),
]

# --- normalizacion de secciones (categoria_padre) y categorias -----------------------------
SECCION_ALIAS = {
    "aseo hogar": "Limpieza y aseo del hogar",
    "limpieza": "Limpieza y aseo del hogar",
    "hogar": "Hogar",
    "cafe": "Cafe",
    "café": "Cafe",
    "te": "Te",
    "cuidado personal": "Cuidado personal",
    "higiene personal": "Higiene personal",
    "despensa": "Despensa",
    "lacteos y huevos": "Lacteos y huevos",
    "lácteos y huevos": "Lacteos y huevos",
    "huevos": "Lacteos y huevos",
    "servilletas": "Limpieza y aseo del hogar",
    "sin categoria": "",
    "": "",
}
CATEGORIA_ALIAS = {
    "producto": "",
    "instantáneo": "Instantaneo",
    "instantaneo": "Instantaneo",
    "soluble": "Cafe soluble",
    "polvo": "Te en polvo",
    "lácteos": "Lacteos",
}
# Filas exportadas sin categoria: se completan solo cuando el nombre lo hace evidente.
FIX_BY_SKU = {
    "biofrescura-azul": {"marca": "BioFrescura", "categoria": "Desinfectante", "seccion": "Limpieza y aseo del hogar"},
    "impeke-clorogel-900ml": {"marca": "Impeke", "categoria": "Cloro gel", "seccion": "Limpieza y aseo del hogar", "nombre": "Impeke Clorogel 900 ml"},
    "lysoform-900cc": {"marca": "Lysoform", "categoria": "Desinfectante", "seccion": "Limpieza y aseo del hogar", "nombre": "Lysoform desinfectante 900 cc"},
    "manga-confort-noble": {"marca": "Confort", "categoria": "Papel higienico", "seccion": "Limpieza y aseo del hogar", "nombre": "Manga de papel higienico Confort Noble"},
    "manga-confort-suan": {"marca": "Swan", "categoria": "Papel higienico", "seccion": "Limpieza y aseo del hogar", "nombre": "Manga de papel higienico Confort Swan"},
    "poet-lavanda-900ml": {"marca": "Poett", "categoria": "Limpiadores", "seccion": "Limpieza y aseo del hogar", "nombre": "Poett limpiador lavanda 900 ml"},
    "clorinda": {"marca": "Clorinda", "categoria": "Cloro", "seccion": "Limpieza y aseo del hogar", "nombre": "Clorinda cloro"},
    "quix-500ml": {"marca": "Quix", "categoria": "Lavalozas", "seccion": "Limpieza y aseo del hogar", "nombre": "Quix lavalozas 500 ml"},
    "f6feea2c-8ee3-4bef-b453-b3034ac92de9": {"marca": "Emubaby", "categoria": "Toallas humedas", "seccion": "Cuidado personal", "nombre": "Toallas humedas Emubaby"},
    "shampo-ballerina-manzanilla": {"nombre": "Shampoo Ballerina manzanilla"},
    "acondicionador-ballerina": {"nombre": "Acondicionador Ballerina"},
    "sobrekiller": {"nombre": "Killer insecticida en sobre"},
    "cepillo": {"nombre": "Cepillo dental Pepsodent"},
    "milo": {"nombre": "Milo bebida en polvo"},
    "TE-CANELA-LATA-30G": {"marca": "Sin marca"},
    "NESCAFE-FINA-SELECCION": {"nombre": "Cafe Nescafe Fina Seleccion"},
    "GOLD-CAFE-DESC-170": {"nombre": "Cafe en polvo descafeinado Gold tarro 170 g"},
    "GOLD-CAFE-PRIMERA-SELECCION-TARRO-220": {"nombre": "Cafe instantaneo Gold Primera Seleccion tarro 220 g"},
    "DOLCA-CAFE-INST-170G": {"nombre": "Cafe instantaneo Dolca tarro 170 g"},
}
PRESENTACION_RE = re.compile(r"(\d+(?:[.,]\d+)?\s?(?:g|gr|kg|ml|cc|l|lt|un|uds|unidades|u)\b)", re.IGNORECASE)


def clp(value: int | str) -> str:
    return "$" + f"{int(value):,}".replace(",", ".")


def strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def clean(text: str) -> str:
    return " ".join((text or "").replace('"', "").split())


def presentacion(nombre: str, sku: str) -> str:
    for source in (nombre, sku.replace("-", " ")):
        m = PRESENTACION_RE.search(source)
        if m:
            return m.group(1).replace(",", ".").upper().replace("UDS", "un").replace("UNIDADES", "un").replace("UN", "un").replace("GR", "g").replace("G", "g").replace("ML", "ml").replace("CC", "cc").replace("KG", "kg").replace("LT", "L")
    return ""


rows_in = list(csv.DictReader((SRC / "emporio-sura-catalogo.csv").open(encoding="utf-8")))
products: list[dict[str, str]] = []
warnings: list[str] = []
for raw in rows_in:
    sku = clean(raw["sku"])
    fix = FIX_BY_SKU.get(sku, {})
    nombre = clean(fix.get("nombre") or raw["nombre"])
    seccion_raw = strip_accents(clean(raw["categoria_padre"])).lower()
    seccion = fix.get("seccion") or SECCION_ALIAS.get(seccion_raw, clean(raw["categoria_padre"]))
    categoria_raw = clean(raw["categoria"])
    categoria = fix.get("categoria") or CATEGORIA_ALIAS.get(categoria_raw.lower(), categoria_raw)
    categoria = strip_accents(categoria)
    marca = clean(fix.get("marca") or raw["marca"])
    if marca.lower() in {"", "meal prep"}:
        marca = "Sin marca"
        warnings.append(f"{sku}: marca vacia o placeholder en el export")
    if not seccion:
        seccion = "Otros"
        warnings.append(f"{sku}: sin seccion en el export, quedo en 'Otros'")
    precio = int(float(clean(raw["precio"])))
    if clean(raw["moneda"]) != "CLP":
        warnings.append(f"{sku}: moneda '{raw['moneda']}' normalizada a CLP")
    products.append({
        "sku": sku,
        "producto": strip_accents(nombre),
        "seccion": seccion,
        "categoria": categoria,
        "marca": strip_accents(marca),
        "presentacion": presentacion(nombre, sku),
        "precio_clp": str(precio),
    })

# duplicados por nombre normalizado
seen: dict[str, str] = {}
for p in products:
    key = strip_accents(p["producto"]).lower()
    if key in seen:
        warnings.append(f"posible duplicado: {p['sku']} y {seen[key]} ({p['producto']})")
    seen.setdefault(key, p["sku"])

products.sort(key=lambda p: (p["seccion"], p["categoria"], p["producto"]))

# --- 1) catalogo.csv (ordenado por seccion para que los chunks queden tematicos) --------------
with (DST / "emporio-sura-catalogo.csv").open("w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["sku", "producto", "seccion", "categoria", "marca", "presentacion", "precio_clp"])
    w.writeheader()
    w.writerows(products)

# --- 2) resumen de surtido (que vendemos, por seccion) ----------------------------------------
by_section: dict[str, list[dict[str, str]]] = defaultdict(list)
for p in products:
    by_section[p["seccion"]].append(p)
lines = [f"# Que vende {STORE}", "", f"{STORE} es una tienda de abarrotes y productos de hogar en Coronel. Vende {len(products)} productos en {len(by_section)} secciones. Los precios estan en pesos chilenos (CLP).", ""]
for seccion, items in by_section.items():
    marcas = sorted({p["marca"] for p in items if p["marca"] != "Sin marca"})
    cats = sorted({p["categoria"] for p in items if p["categoria"]})
    precios = [int(p["precio_clp"]) for p in items]
    plural = "producto" if len(items) == 1 else "productos"
    lines += [f"## {seccion}", "", f"{len(items)} {plural}. Categorias: {', '.join(cats) or 'varias'}. Marcas: {', '.join(marcas) or 'sin marca'}. Precios desde {clp(min(precios))} hasta {clp(max(precios))}.", ""]
    for p in items:
        pres = f" ({p['presentacion']})" if p["presentacion"] else ""
        lines.append(f"- {p['producto']}{pres}: {clp(p['precio_clp'])} (sku {p['sku']})")
    lines.append("")
(DST / "emporio-sura-surtido.md").write_text("\n".join(lines), encoding="utf-8")

# --- 2b) ficha por producto: un encabezado por item => un chunk por producto -------------------
# Las consultas por marca o producto suelto ("precio del omo", "tienen papel higienico") se
# recuperan mucho mejor con un chunk corto y especifico que con filas agrupadas.
ficha = [f"# Productos de {STORE}", "", f"Una ficha por producto. Precios en pesos chilenos (CLP).", ""]
for p in products:
    partes = [f"{p['producto']} es un producto de la marca {p['marca']}" if p["marca"] != "Sin marca" else f"{p['producto']} es un producto sin marca"]
    partes.append(f"de la categoria {p['categoria']} en la seccion {p['seccion']}" if p["categoria"] else f"de la seccion {p['seccion']}")
    frase = ", ".join(partes) + "."
    if p["presentacion"]:
        frase += f" Presentacion: {p['presentacion']}."
    frase += f" Precio: {clp(p['precio_clp'])}. SKU: {p['sku']}."
    ficha += [f"## {p['producto']} ({p['marca']}) - {clp(p['precio_clp'])}", "", frase, ""]
(DST / "emporio-sura-productos.md").write_text("\n".join(ficha), encoding="utf-8")

# --- 3) politicas: solo hechos confirmados + instruccion de derivar en lo no definido ----------
politicas = f"""# Politicas de {STORE}

## Zona de despacho a domicilio

{STORE} despacha a domicilio unicamente dentro de la comuna de Coronel, en 10 sectores. La entrega es el mismo dia. El reparto lo realiza Logistic Kronix. No hay despacho fuera de Coronel ni a otras comunas.

## Costo de despacho por sector

El costo de despacho depende del sector de Coronel. Todos los sectores se entregan el mismo dia.

| Sector | Costo de despacho |
|---|---|
| Coronel Centro | $1.000 |
| Escuadron | $1.500 |
| Schwager | $2.000 |
| Escuadron Sur | $2.000 |
| Villa Mora | $2.500 |
| Yobilo | $3.000 |
| Lagunillas | $3.500 |
| Camilo Olavarria | $4.000 |
| Lo Rojas | $4.500 |
| Maule | $5.000 |

No existe envio gratis ni monto minimo configurado: cada sector cobra siempre su tarifa.

## Retiro en tienda

El retiro en tienda no tiene costo. El cliente elige retiro al hacer el pedido y pasa a buscarlo a la tienda. Si el cliente pregunta la direccion exacta o el horario de retiro, el agente debe derivar a un humano porque ese dato no esta cargado.

## Medios de pago

Se aceptan dos medios de pago: transferencia bancaria y Mercado Pago. Con Mercado Pago el pago se completa con el link que genera el asistente al confirmar el pedido. Si el cliente pide los datos de la cuenta para transferir, cuotas, pago en efectivo o pago contra entrega, el agente debe derivar a un humano porque esa informacion no esta definida.

## Cambios, devoluciones y garantia

La politica de cambios, devoluciones y garantia no esta definida en el sistema. Ante cualquier reclamo por producto en mal estado, vencido, equivocado o faltante, el agente debe pedir el numero de pedido y una descripcion del problema, y derivar a un humano. No debe prometer plazos ni reembolsos.

## Horario de atencion

El horario de atencion de la tienda y de WhatsApp no esta definido en el sistema. Si el cliente lo pregunta, el agente debe derivar a un humano.
"""
(DST / "emporio-sura-politicas.md").write_text(politicas, encoding="utf-8")

# --- 4) FAQ derivadas solo de hechos confirmados ---------------------------------------------
faq_sectores = []
for sector, costo in DESPACHO:
    faq_sectores.append(f"## Cuanto cuesta el despacho a {sector}?\n\nEl despacho a {sector} cuesta {clp(costo)} y llega el mismo dia. {sector} es uno de los 10 sectores de Coronel con reparto a domicilio.\n")
by_cat: dict[str, list[dict[str, str]]] = defaultdict(list)
for p in products:
    if p["categoria"]:
        by_cat[p["categoria"]].append(p)
faq_categorias = []
for cat, items in sorted(by_cat.items()):
    lista = "; ".join(f"{i['producto']} a {clp(i['precio_clp'])}" for i in items)
    faq_categorias.append(f"## Tienen {cat.lower()}?\n\nSi. En {cat.lower()} {STORE} tiene: {lista}.\n")
faq_generadas = "\n".join(faq_sectores + faq_categorias)

faq = f"""# Preguntas frecuentes de {STORE}

{faq_generadas}

## Hacen despacho a domicilio?

Si. {STORE} despacha a domicilio dentro de Coronel, en 10 sectores, con entrega el mismo dia. El costo va de $1.000 en Coronel Centro a $5.000 en Maule, segun el sector.

## Despachan fuera de Coronel?

No. El despacho es solo dentro de la comuna de Coronel. Fuera de Coronel no hay reparto.

## El despacho es gratis si compro mucho?

No. No hay envio gratis por monto: cada sector tiene su tarifa fija.

## Cuanto demora el despacho?

La entrega es el mismo dia del pedido, en todos los sectores de Coronel.

## Puedo retirar en la tienda?

Si. El retiro en tienda es gratis. Para la direccion y el horario de retiro, un humano del equipo te confirma.

## Como puedo pagar?

Con transferencia bancaria o con Mercado Pago. Con Mercado Pago recibes un link de pago al confirmar el pedido.

## Aceptan tarjeta de credito o debito?

El pago con tarjeta se hace a traves de Mercado Pago. Para consultas de cuotas, un humano del equipo te confirma.

## Aceptan efectivo o pago contra entrega?

Esa opcion no esta definida. Un humano del equipo te confirma.

## Que productos venden?

Productos de limpieza y aseo del hogar, cuidado e higiene personal, cafe, te, despensa, lacteos y huevos, e insecticidas y articulos para el hogar. Marcas como Nescafe, Omo, Confort, Poett, Quix, Head & Shoulders, Kotex, Milo y Nido, entre otras.

## Que cafes tienen?

Cafe soluble e instantaneo en tarro: Nescafe Tradicion 400 g ($13.000), Nescafe Fina Seleccion ($12.000), Nescafe Decaf 170 g ($7.800), Gold descafeinado 170 g ($7.800), Gold Primera Seleccion 220 g ($7.800), Dolca 170 g ($5.900) y Ecco ($3.800).

## Que pasa si un producto llega en mal estado o vencido?

Indica tu numero de pedido y que paso; un humano del equipo lo resuelve. El asistente no gestiona cambios ni reembolsos por su cuenta.
"""
(DST / "emporio-sura-faq.md").write_text(faq, encoding="utf-8")

# --- 5) pendientes para el dueno (NO se indexa) -----------------------------------------------
pend = """# Pendientes para el dueno de Emporio Sura (no indexar)

Datos que no estan en el sistema. Mientras falten, el agente deriva a un humano.

## Despacho
- Despacho a otras comunas bajo pedido?
- Monto minimo de compra para despachar?
- Hora limite para pedir y recibir el mismo dia?

## Retiro en tienda
- Direccion exacta de la tienda.
- Horario de retiro.
- Tiempo de preparacion del pedido.

## Pagos
- Datos de la cuenta para transferencia (banco, numero, RUT, titular).
- Cuotas con Mercado Pago (cuantas, que tarjetas).
- Se acepta efectivo o pago contra entrega?

## Cambios, devoluciones y garantia
- Plazo y condiciones (sin abrir, con boleta).
- Productos sin cambio (perecibles, higiene personal, liquidaciones).
- Donde se hace el cambio y como se devuelve el dinero.
- Plazo y requisitos para reclamar producto vencido o en mal estado.

## Horarios
- Tienda fisica, WhatsApp, telefono y pedidos web.

## Catalogo
""" + "\n".join(f"- {w}" for w in warnings) + "\n"
(DST / "PENDIENTES-DUENO.md").write_text(pend, encoding="utf-8")

print(f"productos: {len(products)} | secciones: {len(by_section)} | avisos catalogo: {len(warnings)}")
for f in sorted(DST.iterdir()):
    print(f"  {f.name:<32} {f.stat().st_size:>6} B")
