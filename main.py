import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime
import requests

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Bodega PRO", layout="wide")

# 🔐 SECRETS
TOKEN = st.secrets["telegram"]["token"]
CHAT_ID = st.secrets["telegram"]["chat_id"]

# ---------------- TELEGRAM ----------------
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        st.error(f"Error Telegram: {e}")

# ---------------- GOOGLE SHEETS ----------------
@st.cache_resource
def conectar():
    creds = dict(st.secrets["gcp_service_account"])
    creds["private_key"] = creds["private_key"].replace("\\n", "\n")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds, scope)
    client = gspread.authorize(creds)

    return client.open("Inventario_Bodega")

sh = conectar()
inv = sh.worksheet("Inventario")
mov = sh.worksheet("Movimientos")

# ---------------- CACHE DATA ----------------
@st.cache_data(ttl=60)
def df_inv():
    return pd.DataFrame(inv.get_all_records())

@st.cache_data(ttl=60)
def df_mov():
    return pd.DataFrame(mov.get_all_records())

# 🔥 MAPA PARA EVITAR .find()
@st.cache_data(ttl=60)
def mapa_items():
    df = df_inv()
    return {row["Nombre"]: idx + 2 for idx, row in df.iterrows()}

# ---------------- FUNCIONES ----------------
def update_stock(item, cant, op):
    try:
        mapa = mapa_items()

        if item not in mapa:
            st.error(f"No existe el item: {item}")
            return

        fila = mapa[item]

        valor = inv.cell(fila, 4).value
        stock = int(valor) if valor else 0

        nuevo = stock - cant if op == "restar" else stock + cant
        inv.update_cell(fila, 4, max(0, nuevo))

    except Exception as e:
        st.error(f"Error stock: {e}")

def registrar(data):
    try:
        mov.append_row(data)
    except Exception as e:
        st.error(f"Error registrando: {e}")

# ---------------- UI ----------------
menu = st.sidebar.radio("Menú", [
    "Dashboard",
    "Salida",
    "Devoluciones",
    "Historial"
])

# ---------------- DASHBOARD ----------------
if menu == "Dashboard":
    st.title("📊 Inventario")

    df = df_inv()

    col1, col2, col3 = st.columns(3)
    col1.metric("Items", len(df))
    col2.metric("Stock Total", df["Stock"].sum())

    bajos = df[df["Stock"] < 5]
    col3.metric("Bajo Stock", len(bajos))

    if not bajos.empty:
        st.warning("⚠️ Bajo stock detectado")
        st.dataframe(bajos)

        if "alerta_enviada" not in st.session_state:
            mensaje = "⚠️ STOCK BAJO\n\n"
            for _, row in bajos.iterrows():
                mensaje += f"{row['Nombre']} ({row['Stock']})\n"

            enviar_telegram(mensaje)
            st.session_state.alerta_enviada = True

    st.dataframe(df)

# ---------------- SALIDA ----------------
elif menu == "Salida":
    st.title("📤 Salida")

    df = df_inv()
    items = df["Nombre"].tolist()

    usuario = st.text_input("Responsable")
    destino = st.text_input("Destino")
    seleccion = st.multiselect("Items", items)

    cantidades = {}
    for i in seleccion:
        cantidades[i] = st.number_input(f"{i}", min_value=1, key=i)

    if st.button("Registrar salida"):

        if not usuario:
            st.warning("Falta el responsable")
            st.stop()

        if not destino:
            st.warning("Falta destino")
            st.stop()

        fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

        resumen = []
        for i, c in cantidades.items():
            update_stock(i, c, "restar")
            resumen.append(f"{i}({c})")

        registrar([
            fecha,
            usuario,
            destino,
            ", ".join(resumen),
            "Salida",
            "PENDIENTE"
        ])

        enviar_telegram(f"📤 SALIDA\nUsuario: {usuario}\nDestino: {destino}\nItems: {', '.join(resumen)}")

        st.success("Salida registrada")
        st.rerun()

# ---------------- DEVOLUCIONES ----------------
elif menu == "Devoluciones":
    st.title("📥 Devoluciones")

    df = df_mov()
    pendientes = df[df["Estado_Retorno"] == "PENDIENTE"]

    for idx, row in pendientes.iterrows():
        with st.expander(f"{row['Items_Llevados']}"):

            items = row["Items_Llevados"].split(", ")
            dev = {}

            for i in items:
                if "(" not in i:
                    continue

                nombre = i.split("(")[0].strip()
                dev[nombre] = st.number_input(nombre, min_value=1, key=f"{idx}_{nombre}")

            if st.button("Devolver", key=idx):

                for i, c in dev.items():
                    update_stock(i, c, "sumar")

                mov.update_cell(idx + 2, 6, "DEVUELTO")

                enviar_telegram("📥 Devolución registrada")

                st.success("Devuelto correctamente")
                st.rerun()

# ---------------- HISTORIAL ----------------
elif menu == "Historial":
    st.title("📜 Historial")

    df = df_mov()
    st.dataframe(df)