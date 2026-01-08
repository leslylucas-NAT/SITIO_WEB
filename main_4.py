import os
import io
import csv
import json
import base64
import pandas as pd
import urllib3
import requests
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, EmailStr, Field

# Desactivar advertencias de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# CONFIGURACIÓN Y DIRECTORIOS
# ============================================================
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates" # Asegúrate de mover tu index.html aquí

# Archivos CSV / Excel
PRODUCTS_FILE = DATA_DIR / "productos.csv"
CONSULTORAS_FILE = DATA_DIR / "consultoras.csv"

# Variables de Ambiente
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")
GREEN_TOKEN = os.getenv("GREEN_TOKEN") or "ff0981990eb442a49c1f0d39b95a8217e0aa372f3f6f434caf"
GREEN_ID = os.getenv("GREEN_ID") or 7105454700
HOST = os.getenv("GREEN_HOST") or "7105.api.greenapi.com"
EMAIL_PEDIDOS_GENERAL = "leslylucas@natura.net"
SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

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

# ============================================================
# ESTADO GLOBAL Y CARGA DE DATOS
# ============================================================

app = FastAPI(title="Ecommerce-lite Unificado")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

PRODUCTS: List[ProductOut] = []
CONSULTORAS: Dict[str, ConsultoraOut] = {}

def format_drive_url(url: str):
    if "drive.google.com" in url and "/d/" in url:
        try:
            file_id = url.split("/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=view&id={file_id}"
        except: return url
    return url

def load_data():
    global PRODUCTS, CONSULTORAS
    # Cargar Productos
    if PRODUCTS_FILE.exists():
        df = pd.read_excel(PRODUCTS_FILE) if PRODUCTS_FILE.suffix == ".xlsx" else pd.read_csv(PRODUCTS_FILE, decimal=",")
        df.columns = [str(c).strip().upper() for c in df.columns]
        PRODUCTS = []
        for record in df.to_dict(orient="records"):
            raw_precio = record.get("PRECIO")
            try:
                precio_val = float(raw_precio) if pd.notna(raw_precio) else None
            except:
                precio_val = float(str(raw_precio).replace(",", ".")) if pd.notna(raw_precio) else None
            
            # Limpiar y formatear imagen
            raw_url = str(record.get("IMAGEN")).strip() if pd.notna(record.get("IMAGEN")) else ""
            if not raw_url or raw_url.lower() in ["nan", "none"]:
                img = "https://via.placeholder.com/300?text=Sin+Imagen"
            elif raw_url.startswith("http"):
                img = format_drive_url(raw_url)
            else:
                img = f"/static/{raw_url}"

            PRODUCTS.append(ProductOut(
                sku=str(record["CV"]),
                descripcion=str(record["DESCRIPCION"]),
                precio=precio_val,
                imagen_url=img,
                marca=str(record.get("MARCA")).strip().lower() if pd.notna(record.get("MARCA")) else "natura"
            ))

    # Cargar Consultoras
    if CONSULTORAS_FILE.exists():
        dfc = pd.read_excel(CONSULTORAS_FILE) if CONSULTORAS_FILE.suffix == ".xlsx" else pd.read_csv(CONSULTORAS_FILE)
        dfc.columns = [str(c).strip().upper() for c in dfc.columns]
        CONSULTORAS = {str(r["ID"]): ConsultoraOut(id=str(r["ID"]), nombre=str(r["NOMBRE"]), telefono=str(r["TELEFONO"]), email=str(r["EMAIL"]).strip()) for r in dfc.to_dict(orient="records")}

@app.on_event("startup")
def startup_event():
    load_data()

# ============================================================
# LÓGICA DE NOTIFICACIONES
# ============================================================

def enviar_notificaciones_background(pedido: PedidoCreate, consultora: ConsultoraOut):
    # 1. CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sku", "descripcion", "cantidad", "cliente", "tel_cliente", "consultora_id"])
    for item in pedido.carrito:
        writer.writerow([item.sku, item.descripcion, item.cantidad, pedido.cliente.nombre, pedido.cliente.telefono, consultora.id])
    csv_bytes = output.getvalue().encode("utf-8")

    # 2. Email (SendGrid)
    if SENDGRID_API_KEY:
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

    # 3. WhatsApp (Green API)
    resumen_txt = "\n".join([f"• {i.cantidad} x {i.descripcion}" for i in pedido.carrito])
    mensaje = (f"🌟 *NUEVO PEDIDO RECIBIDO*\n\n*Consultora:* {consultora.nombre}\n*Cliente:* {pedido.cliente.nombre}\n"
               f"*Tel:* {pedido.cliente.telefono}\n\n*Productos:*\n{resumen_txt}\n\n¡Ingresa a MI NEGOCIO para finalizar!")
    
    numero_limpio = "".join(filter(str.isdigit, consultora.telefono))
    url_wa = f"https://{HOST}/waInstance{GREEN_ID}/sendMessage/{GREEN_TOKEN}"
    requests.post(url_wa, json={"chatId": f"{numero_limpio}@c.us", "message": mensaje}, verify=False)

# ============================================================
# RUTAS DE UI (ANTIGUO FLASK)
# ============================================================

app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

@app.get("/")
async def index(consultora_id: Optional[str] = None):
    if not consultora_id:
        return JSONResponse(status_code=400, content={"detail": "Falta ID de consultora"})
    return RedirectResponse(url=f"/tienda/natura/{consultora_id}")

@app.get("/tienda/{marca}/{consultora_id}")
async def tienda(request: Request, marca: str, consultora_id: str):
    if consultora_id not in CONSULTORAS:
        raise HTTPException(status_code=404, detail="Consultora no encontrada")
    
    productos_filtrados = [p for p in PRODUCTS if p.marca == marca.lower().strip()]
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "products": productos_filtrados, 
        "consultora_id": consultora_id, 
        "marca_actual": marca
    })

# ============================================================
# ENDPOINTS API
# ============================================================

@app.post("/api/orders")
async def crear_pedido(pedido: PedidoCreate, background_tasks: BackgroundTasks):
    if not pedido.carrito:
        raise HTTPException(status_code=400, detail="Carrito vacío")
    
    consultora = CONSULTORAS.get(pedido.consultora_id)
    if not consultora:
        raise HTTPException(status_code=404, detail="Consultora no existe")

    # Ejecutar envíos pesados en segundo plano para no bloquear al cliente
    background_tasks.add_task(enviar_notificaciones_background, pedido, consultora)

    return {"status": "ok", "message": "Pedido recibido"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)