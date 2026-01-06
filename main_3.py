from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Dict
from datetime import datetime
import csv
import io
import requests
import pandas as pd
from pathlib import Path
import base64
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import json

# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Archivos CSV / Excel
PRODUCTS_FILE = DATA_DIR / "productos.csv"
CONSULTORAS_FILE = DATA_DIR / "consultoras.csv"

# URL base del frontend
FRONT_BASE_URL = "http://127.0.0.1:8000/front/front.html"

# ---------- SendGrid (correo) ----------
SENDGRID_API_KEY = "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"
SENDGRID_FROM_EMAIL = "leslycordero55@gmail.com"
EMAIL_PEDIDOS_GENERAL = "leslylucas@natura.net"
SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

# ---------- Green API (WhatsApp Automático) ----------
# Reemplaza estos valores con los de tu consola de Green API
GREEN_ID = 7105454700
GREEN_TOKEN = "ff0981990eb442a49c1f0d39b95a8217e0aa372f3f6f434caf"
HOST = "7105.api.greenapi.com"

# ============================================================
# CREACIÓN DE LA APP FASTAPI
# ============================================================

app = FastAPI(title="Ecommerce-lite")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"❌ ERROR DE VALIDACIÓN: {json.dumps(exc.errors(), indent=2)}")
    return JSONResponse(status_code=400, content={"detail": exc.errors()})

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    print(f"⚠️ ERROR DE LÓGICA: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# Servir archivos estáticos
app.mount("/front", StaticFiles(directory=BASE_DIR, html=True), name="front")

# ============================================================
# MODELOS Pydantic
# ============================================================

class Cliente(BaseModel):
    nombre: str = Field(..., min_length=2)
    telefono: str = Field(..., min_length=8)
    correo: Optional[EmailStr] = None

class ItemCarrito(BaseModel):
    sku: str
    descripcion: str
    cantidad: int = Field(..., gt=0)

class PedidoCreate(BaseModel):
    consultora_id: str
    carrito: List[ItemCarrito]
    cliente: Cliente

class ProductOut(BaseModel):
    sku: str
    descripcion: str
    precio: Optional[float] = None
    imagen_url: Optional[str] = None
    marca: Optional[str] = None

class ConsultoraOut(BaseModel):
    id: str
    nombre: str
    telefono: str
    email: EmailStr

class LinkOut(BaseModel):
    consultora_id: str
    url: str

# ESTRUCTURAS EN MEMORIA
PRODUCTS: List[ProductOut] = []
CONSULTORAS: Dict[str, ConsultoraOut] = {}

# ============================================================
# CARGA DE DATOS (CSV / Excel)
# ============================================================

def load_products():
    global PRODUCTS
    if not PRODUCTS_FILE.exists(): return
    
    if PRODUCTS_FILE.suffix == ".xlsx":
        df = pd.read_excel(PRODUCTS_FILE)
    else:
        df = pd.read_csv(PRODUCTS_FILE, decimal=",")

    df.columns = [str(c).strip().upper() for c in df.columns]
    
    PRODUCTS = []
    for record in df.to_dict(orient="records"):
        raw_precio = record.get("PRECIO")
        try:
            precio_val = float(raw_precio) if pd.notna(raw_precio) else None
        except:
            precio_val = float(str(raw_precio).replace(",", ".")) if pd.notna(raw_precio) else None
        
        PRODUCTS.append(ProductOut(
            sku=str(record["CV"]),
            descripcion=str(record["DESCRIPCION"]),
            precio=precio_val,
            imagen_url=str(record.get("IMAGEN")).strip() if pd.notna(record.get("IMAGEN")) else None,
            marca=str(record.get("MARCA")).strip().lower() if pd.notna(record.get("MARCA")) else "natura"
        ))

def load_consultoras():
    global CONSULTORAS
    if not CONSULTORAS_FILE.exists(): return
    
    df = pd.read_excel(CONSULTORAS_FILE) if CONSULTORAS_FILE.suffix == ".xlsx" else pd.read_csv(CONSULTORAS_FILE)
    df.columns = [str(c).strip().upper() for c in df.columns]
    
    CONSULTORAS = {}
    for record in df.to_dict(orient="records"):
        cid = str(record["ID"])
        CONSULTORAS[cid] = ConsultoraOut(
            id=cid, 
            nombre=str(record["NOMBRE"]), 
            telefono=str(record["TELEFONO"]), 
            email=str(record["EMAIL"]).strip()
        )

# ============================================================
# FUNCIONES AUXILIARES (Email y WhatsApp)
# ============================================================

def generar_csv_pedido(pedido: PedidoCreate, consultora: ConsultoraOut) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sku", "descripcion", "cantidad", "cliente", "tel_cliente", "consultora_id"])
    for item in pedido.carrito:
        writer.writerow([item.sku, item.descripcion, item.cantidad, pedido.cliente.nombre, pedido.cliente.telefono, consultora.id])
    return output.getvalue().encode("utf-8")

def enviar_correo_sendgrid(pedido: PedidoCreate, consultora: ConsultoraOut, csv_bytes: bytes):
    if not SENDGRID_API_KEY: return
    resumen = "\n".join([f"- {i.cantidad} x {i.descripcion}" for i in pedido.carrito])
    cuerpo = f"Nuevo pedido recibido\n\nConsultora: {consultora.nombre}\nCliente: {pedido.cliente.nombre}\n\nResumen:\n{resumen}"
    archivo_b64 = base64.b64encode(csv_bytes).decode("utf-8")
    
    data = {
        "personalizations": [{"to": [{"email": EMAIL_PEDIDOS_GENERAL}, {"email": consultora.email}], "subject": f"Pedido {consultora.nombre}"}],
        "from": {"email": SENDGRID_FROM_EMAIL},
        "content": [{"type": "text/plain", "value": cuerpo}],
        "attachments": [{"content": archivo_b64, "type": "text/csv", "filename": "pedido.csv"}]
    }
    requests.post(SENDGRID_API_URL, json=data, headers={"Authorization": f"Bearer {SENDGRID_API_KEY}"}, verify=False)

def enviar_whatsapp_automatico(numero_destino: str, texto: str):
    """
    Envía el mensaje directamente desde el servidor sin intervención del usuario.
    """
    # Limpiar número de teléfono
    numero_limpio = "".join(filter(str.isdigit, numero_destino))
    chat_id = f"{numero_limpio}@c.us"
    
    
    url = f"https://{HOST}/waInstance{GREEN_ID}/sendMessage/{GREEN_TOKEN}"
    payload = {"chatId": chat_id, "message": texto}
    
    try:
        resp = requests.post(url, json=payload, timeout=10, verify=False)
        return resp.status_code == 200
    except Exception as e:
        print(f"Error en envío automático de WhatsApp: {e}")
        return False

# ============================================================
# ENDPOINTS
# ============================================================

@app.on_event("startup")
def startup_event():
    load_products()
    load_consultoras()

@app.post("/links", response_model=LinkOut)
def generar_link_tienda(consultora_id: str):
    if consultora_id not in CONSULTORAS: 
        raise HTTPException(status_code=404, detail="Consultora no encontrada")
    return LinkOut(consultora_id=consultora_id, url=f"{FRONT_BASE_URL}?consultora_id={consultora_id}")

@app.get("/productos", response_model=List[ProductOut])
def get_productos(consultora_id: str, marca: Optional[str] = None):
    if consultora_id not in CONSULTORAS: 
        raise HTTPException(status_code=404, detail="Consultora no encontrada")
    if not marca: 
        return PRODUCTS
    return [p for p in PRODUCTS if p.marca == marca.lower().strip()]

@app.get("/consultoras", response_model=List[ConsultoraOut])
def get_consultoras():
    return list(CONSULTORAS.values())

@app.post("/orders")
def crear_pedido(pedido: PedidoCreate):
    if not pedido.carrito: 
        raise HTTPException(status_code=400, detail="El carrito está vacío")
    
    consultora = CONSULTORAS.get(pedido.consultora_id)
    if not consultora: 
        raise HTTPException(status_code=404, detail="Consultora no encontrada")

    # 1. Generar y enviar Email (Segundo plano)
    csv_bytes = generar_csv_pedido(pedido, consultora)
    try:
        enviar_correo_sendgrid(pedido, consultora, csv_bytes)
    except Exception as e:
        print(f"Error enviando correo: {e}")

    # 2. Construir mensaje de WhatsApp
    resumen_txt = "\n".join([f"• {i.cantidad} x {i.descripcion}" for i in pedido.carrito])
    mensaje_final = (
        f"🌟 Buenas noticias!🌟\n\n"
        f"🛍️ *NUEVO PEDIDO RECIBIDO*\n\n"
        f"*Para la Consultora:* {consultora.nombre}\n"
        f"*Del Cliente:* {pedido.cliente.nombre}\n"
        f"*Teléfono:* {pedido.cliente.telefono}\n\n"
        f"*Productos:*\n{resumen_txt}\n\n"
        f"¡Tu pedido te espera! 📦 Ingresa a MI NEGOCIO para ver el pedido precargado y finaliza tu compra 🛒"
    )

    # 3. EJECUTAR ENVÍO AUTOMÁTICO (Sin clics en el móvil)
    whatsapp_enviado = enviar_whatsapp_automatico(consultora.telefono, mensaje_final)

    return {
        "status": "ok",
        "message": "Pedido procesado y notificado",
        "whatsapp_automatico": whatsapp_enviado
    }