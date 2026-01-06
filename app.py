from flask import Flask, render_template, request, url_for, redirect, jsonify
import requests
import pandas as pd
import os
import urllib.parse
from pathlib import Path
import urllib3

# Desactivar advertencias de SSL para limpiar la consola
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# --- CONFIGURACIÓN ---
FASTAPI_URL = "http://127.0.0.1:8000" 
BASE_DIR = Path(__file__).resolve().parent

# --- CONFIGURACIÓN GREEN API (Tus credenciales actuales) ---
GREEN_ID = 7105454700
GREEN_TOKEN = "ff0981990eb442a49c1f0d39b95a8217e0aa372f3f6f434caf"
HOST = "7105.api.greenapi.com"

def format_drive_url(url):
    if "drive.google.com" in url and "/d/" in url:
        try:
            file_id = url.split("/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=view&id={file_id}"
        except: return url
    return url

# ============================================================
# LÓGICA DE GREEN API
# ============================================================

def enviar_whatsapp_green_api(telefono, mensaje):
    numero_limpio = "".join(filter(str.isdigit, telefono))
    chat_id = f"{numero_limpio}@c.us"
    
    url = f"https://{HOST}/waInstance{GREEN_ID}/sendMessage/{GREEN_TOKEN}"
    payload = {
        "chatId": chat_id,
        "message": mensaje
    }
    
    try:
        # verify=False para evitar errores de certificados locales
        response = requests.post(url, json=payload, timeout=10, verify=False)
        print(f"🚀 Status Green API: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error Green API: {e}")
        return False

# ============================================================
# RUTAS
# ============================================================

@app.route("/")
def index():
    consultora_id = request.args.get("consultora_id")
    if consultora_id:
        return redirect(url_for('tienda', marca='natura', consultora_id=consultora_id))
    return "<h1>Error: Falta el ID de la consultora</h1>"

@app.route("/tienda/<marca>/<consultora_id>")
def tienda(marca, consultora_id):
    marca_limpia = marca.lower().strip()
    productos = [] 
    try:
        response = requests.get(f"{FASTAPI_URL}/productos", params={"consultora_id": consultora_id, "marca": marca_limpia}, timeout=5)
        if response.status_code == 200:
            productos = response.json()
            for prod in productos:
                if isinstance(prod.get("precio"), str):
                    prod["precio"] = float(prod["precio"].replace(",", "."))
                
                raw_url = str(prod.get("imagen_url", "")).strip()
                if not raw_url or raw_url.lower() in ["nan", "none", ""]:
                    prod["imagen_url"] = "https://via.placeholder.com/300?text=Sin+Imagen"
                elif raw_url.startswith("http"):
                    prod["imagen_url"] = format_drive_url(raw_url)
                else:
                    prod["imagen_url"] = url_for('static', filename=raw_url)
        else:
            return f"<h1>Error Backend: {response.status_code}</h1>"
    except Exception as e:
        return f"<h1>Error de conexión: {e}</h1>"

    return render_template("index.html", products=productos, consultora_id=consultora_id, marca_actual=marca_limpia)

@app.route("/orders", methods=["POST"])
def crear_pedido():
    data = request.json

    # 1. Obtener info de consultora para el WhatsApp
    try:
        # El Backend se encargará de mandar el WhatsApp y el Email al mismo tiempo
        res_back = requests.post(f"{FASTAPI_URL}/orders", json=data, timeout=10, verify=False)
        return jsonify(res_back.json()), res_back.status_code
    except Exception as e:
        print(f"❌ Error al conectar con el Backend: {e}")
        return jsonify({"detail": "Error de comunicación con el servidor central"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)