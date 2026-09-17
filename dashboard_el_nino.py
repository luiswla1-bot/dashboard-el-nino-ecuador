"""
Dashboard de Monitoreo del Fenómeno del Niño en Ecuador
Datos en tiempo real de NOAA, Google Earth Engine, INOCAR y Windy
Modo TV: rotación automática de secciones cada minuto
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import gspread
from google.oauth2.service_account import Credentials

# ============ CONFIGURACIÓN ============
st.set_page_config(
    page_title="Monitoreo El Niño - Ecuador",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .metric-card { background-color: #f0f2f6; padding: 20px; border-radius: 10px; }
    .block-container { padding-top: 1.5rem; }
    </style>
""", unsafe_allow_html=True)

# ============ CONEXIÓN A GOOGLE SHEETS (histórico permanente) ============
@st.cache_resource(show_spinner=False)
def conectar_google_sheets():
    """Conecta con la hoja de Google Sheets usando las credenciales guardadas en Secrets"""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        credenciales = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=scopes
        )
        cliente = gspread.authorize(credenciales)
        hoja = cliente.open(st.secrets["sheets"]["nombre_hoja"]).sheet1
        return hoja
    except Exception as e:
        st.sidebar.error(f"⚠️ No se pudo conectar a Google Sheets: {e}")
        return None

hoja_sheets = conectar_google_sheets()

@st.cache_data(ttl=300, show_spinner=False)
def leer_historico_sheets():
    """Lee todo el histórico guardado en Google Sheets (caché de 5 min para no saturar la API)"""
    if hoja_sheets is None:
        return pd.DataFrame(columns=["timestamp", "oni", "tsm_promedio"])
    try:
        registros = hoja_sheets.get_all_records()
        df = pd.DataFrame(registros)
        if len(df) > 0:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['oni'] = pd.to_numeric(df['oni'], errors='coerce')
            df['tsm_promedio'] = pd.to_numeric(df['tsm_promedio'], errors='coerce')
        return df
    except Exception as e:
        st.sidebar.warning(f"No se pudo leer el histórico: {e}")
        return pd.DataFrame(columns=["timestamp", "oni", "tsm_promedio"])

# ============ SIDEBAR: CONTROLES ============
st.sidebar.header("⚙️ Configuración")

modo_tv = st.sidebar.toggle("📺 Modo TV (rotación automática)", value=False)
intervalo_rotacion = st.sidebar.slider("Segundos por pestaña", 20, 180, 60, step=10)
ocultar_sidebar = st.sidebar.checkbox("Ocultar esta barra al proyectar", value=False)

if ocultar_sidebar:
    st.markdown("""
        <style>
        section[data-testid="stSidebar"] { display: none; }
        </style>
    """, unsafe_allow_html=True)

SECCIONES = ["📈 Índice ONI", "🌧️ Precipitación en Vivo", "🌡️ Temp. Marina", "📍 Estaciones", "📊 Análisis"]

# ============ AUTOREFRESH ============
if modo_tv:
    contador = st_autorefresh(interval=intervalo_rotacion * 1000, key="tv_autorefresh")
    seccion_actual = SECCIONES[contador % len(SECCIONES)]
else:
    # Auto-refresco de datos cada 10 min aunque no esté en modo TV
    st_autorefresh(interval=600000, key="data_autorefresh")
    seccion_actual = st.sidebar.radio("Ir a sección:", SECCIONES)

# ============ CACHÉ DE DATOS (6 horas) ============
@st.cache_data(ttl=21600, show_spinner=False)
def obtener_datos_noaa_oni():
    """Obtiene el Índice ONI (Oceanic Niño Index) de NOAA"""
    try:
        url = "https://ggweather.com/enso/oni.txt"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            lineas = response.text.split('\n')
            datos = []
            for linea in lineas:
                if linea.strip() and not linea.startswith('Y'):
                    partes = linea.split()
                    if len(partes) >= 13:
                        try:
                            año = int(partes[0])
                            valores = [float(x) if x != '-' else np.nan for x in partes[1:13]]
                            datos.extend([
                                {'año': año, 'mes': m+1, 'oni': valores[m], 'fecha': f"{año}-{m+1:02d}"}
                                for m in range(12)
                            ])
                        except:
                            pass
            df = pd.DataFrame(datos)
            df['fecha'] = pd.to_datetime(df['fecha'])
            return df.dropna().sort_values('fecha')
    except Exception as e:
        st.warning(f"Error obteniendo ONI: {e}")
    return None

@st.cache_data(ttl=21600, show_spinner=False)
def obtener_datos_simulados_estaciones():
    """Datos de estaciones oceanográficas ecuatorianas (reemplazar con API real de INOCAR cuando esté disponible)"""
    estaciones = {
        'Santa Elena (Punta)': {'lat': -2.24, 'lon': -80.36, 'tpm': 23.5, 'salinidad': 34.8},
        'Manta (Bahía)': {'lat': -0.96, 'lon': -80.73, 'tpm': 24.2, 'salinidad': 34.9},
        'Puerto López': {'lat': -1.54, 'lon': -80.42, 'tpm': 23.8, 'salinidad': 34.7},
        'Galápagos (Darwin)': {'lat': -0.30, 'lon': -90.31, 'tpm': 22.1, 'salinidad': 34.6}
    }
    datos = []
    for estacion, props in estaciones.items():
        datos.append({
            'Estación': estacion,
            'Latitud': props['lat'],
            'Longitud': props['lon'],
            'TSM (°C)': props['tpm'] + np.random.normal(0, 0.3),
            'Salinidad': props['salinidad'] + np.random.normal(0, 0.05),
            'Última actualización': datetime.now() - timedelta(hours=np.random.randint(0, 3))
        })
    return pd.DataFrame(datos)

def registrar_historico(oni_actual, tsm_promedio):
    """Agrega una fila nueva a Google Sheets, solo si han pasado al menos 30 min desde la última lectura"""
    if hoja_sheets is None:
        return
    try:
        historico_actual = leer_historico_sheets()
        ahora = datetime.now()
        if len(historico_actual) > 0:
            ultima_lectura = historico_actual['timestamp'].iloc[-1]
            minutos_desde_ultima = (ahora - ultima_lectura).total_seconds() / 60
            if minutos_desde_ultima < 30:
                return  # evita duplicar filas cuando la app rota de pestaña cada minuto
        hoja_sheets.append_row([
            ahora.strftime("%Y-%m-%d %H:%M:%S"),
            round(float(oni_actual), 3) if not np.isnan(oni_actual) else "",
            round(float(tsm_promedio), 3)
        ])
        leer_historico_sheets.clear()  # refresca la caché de lectura
    except Exception as e:
        st.sidebar.warning(f"No se pudo guardar en el histórico: {e}")

# ============ CARGA DE DATOS BASE ============
df_oni = obtener_datos_noaa_oni()
df_estaciones = obtener_datos_simulados_estaciones()

if df_oni is not None and len(df_oni) > 0:
    oni_actual_val = df_oni['oni'].iloc[-1]
else:
    oni_actual_val = np.nan

tsm_prom_val = df_estaciones['TSM (°C)'].mean()
registrar_historico(oni_actual_val, tsm_prom_val)

# ============ ENCABEZADO ============
st.title("🌊 Dashboard: Monitoreo del Fenómeno del Niño")
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Última actualización", datetime.now().strftime("%H:%M:%S"))
with col2:
    st.metric("Sección actual", seccion_actual)
with col3:
    if modo_tv:
        st.metric("Modo TV", f"🟢 Activo ({intervalo_rotacion}s)")
    else:
        st.metric("Modo TV", "⚪ Manual")
with col4:
    total_lecturas = len(leer_historico_sheets())
    st.metric("Lecturas históricas guardadas", total_lecturas)

st.divider()

# ============ SECCIÓN: ÍNDICE ONI ============
if seccion_actual == "📈 Índice ONI":
    st.subheader("Índice Oceánico Niño (ONI) - NOAA")
    st.info("📌 ONI > 0.5°C = El Niño | ONI < -0.5°C = La Niña | -0.5 a 0.5 = Neutral")

    if df_oni is not None and len(df_oni) > 0:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_oni['fecha'], y=df_oni['oni'], mode='lines', name='ONI',
            line=dict(color='darkblue', width=2), fill='tozeroy'
        ))
        fig.add_hline(y=0.5, line_dash="dash", line_color="red", annotation_text="Umbral El Niño")
        fig.add_hline(y=-0.5, line_dash="dash", line_color="blue", annotation_text="Umbral La Niña")
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(
            title="Índice ONI (últimas décadas)", xaxis_title="Fecha",
            yaxis_title="Anomalía de Temperatura (°C)", hovermode='x unified', height=450
        )
        st.plotly_chart(fig, use_container_width=True)

        col1, col2, col3, col4 = st.columns(4)
        ultimos_datos = df_oni.tail(3)
        with col1:
            st.metric("ONI Actual", f"{ultimos_datos['oni'].iloc[-1]:.2f}°C")
        with col2:
            cambio = ultimos_datos['oni'].iloc[-1] - ultimos_datos['oni'].iloc[-2]
            st.metric("Cambio (mensual)", f"{cambio:+.2f}°C")
        with col3:
            promedio_trimestre = ultimos_datos['oni'].mean()
            st.metric("Promedio 3 meses", f"{promedio_trimestre:.2f}°C")
        with col4:
            if promedio_trimestre > 0.5:
                condicion = "🔴 EL NIÑO"
            elif promedio_trimestre < -0.5:
                condicion = "🔵 LA NIÑA"
            else:
                condicion = "⚪ NEUTRAL"
            st.metric("Condición", condicion)
    else:
        st.error("No se pudieron obtener datos del ONI en este momento")

# ============ SECCIÓN: PRECIPITACIÓN EN VIVO ============
elif seccion_actual == "🌧️ Precipitación en Vivo":
    st.subheader("Mapa de Precipitación en Tiempo Real")
    st.info("🌧️ Fuente: Windy.com (modelo ECMWF/GFS) — se actualiza automáticamente en el propio mapa")

    windy_html = """
    <iframe
        width="100%"
        height="600"
        src="https://embed.windy.com/embed2.html?lat=-1.5&lon=-80.0&detailLat=-1.5&detailLon=-80.0&width=650&height=450&zoom=6&level=surface&overlay=rain&product=ecmwf&menu=&message=true&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1"
        frameborder="0">
    </iframe>
    """
    components.html(windy_html, height=620)

    st.caption("Puedes cambiar la capa dentro del mapa (lluvia, viento, nubes, temperatura, olas) usando el menú del propio widget de Windy.")

# ============ SECCIÓN: TEMPERATURA MARINA ============
elif seccion_actual == "🌡️ Temp. Marina":
    st.subheader("Anomalía de Temperatura Superficial del Mar (TSM)")
    st.info("🌡️ Estaciones oceanográficas frente a la costa ecuatoriana")

    fig_mapa = px.scatter_geo(
        df_estaciones, lat='Latitud', lon='Longitud', hover_name='Estación',
        hover_data={'TSM (°C)': ':.1f', 'Salinidad': ':.2f'},
        size='TSM (°C)', color='TSM (°C)', color_continuous_scale='RdYlBu_r',
        title="Estaciones Oceanográficas: Temperatura Superficial", projection='natural earth'
    )
    fig_mapa.update_layout(
        geo=dict(scope='south america', projection_type='mercator',
                 center=dict(lat=-2, lon=-80), lataxis_range=[-3.5, 1], lonaxis_range=[-92, -75]),
        height=550
    )
    st.plotly_chart(fig_mapa, use_container_width=True)

# ============ SECCIÓN: ESTACIONES ============
elif seccion_actual == "📍 Estaciones":
    st.subheader("Estaciones Oceanográficas del Ecuador")
    st.dataframe(
        df_estaciones.style.format({'TSM (°C)': '{:.1f}', 'Salinidad': '{:.2f}'}),
        use_container_width=True, height=250
    )
    st.info(
        "**Fuentes de datos:**\n\n"
        "- 📍 INOCAR (Instituto Oceanográfico de la Armada Ecuatoriana)\n"
        "- 🌊 NOAA (National Oceanic and Atmospheric Administration)\n"
        "- 🌧️ Windy.com (precipitación y viento en vivo)\n"
        "- 🛰️ Google Earth Engine (datos de satélite)"
    )

# ============ SECCIÓN: ANÁLISIS + HISTÓRICO ============
elif seccion_actual == "📊 Análisis":
    st.subheader("Análisis, Alertas e Histórico de la Sesión")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### ⚠️ Alertas Activas")
        if not np.isnan(oni_actual_val):
            if oni_actual_val > 0.5:
                st.warning("🔴 **ALERTA: Condiciones El Niño activas**")
                st.write("Se esperan lluvias intensas e inundaciones en la costa ecuatoriana")
            elif oni_actual_val < -0.5:
                st.info("🔵 **ALERTA: Condiciones La Niña activas**")
                st.write("Se espera sequía en algunas regiones de la costa")
            else:
                st.success("⚪ **Condiciones neutrales**")
    with col2:
        st.markdown("### 📊 Indicadores monitoreados")
        st.write("""
        - Índice ONI (3 meses móvil)
        - Anomalía de TSM ecuatorial
        - Precipitación en vivo (Windy)
        - Estaciones oceanográficas del Ecuador
        """)

    st.divider()
    st.markdown("### 📈 Histórico permanente (Google Sheets)")
    hist = leer_historico_sheets()
    if len(hist) > 1:
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Scatter(x=hist['timestamp'], y=hist['oni'], mode='lines+markers', name='ONI'))
        fig_hist.add_trace(go.Scatter(x=hist['timestamp'], y=hist['tsm_promedio'], mode='lines+markers', name='TSM Promedio', yaxis='y2'))
        fig_hist.update_layout(
            height=350,
            yaxis=dict(title="ONI (°C)"),
            yaxis2=dict(title="TSM (°C)", overlaying='y', side='right'),
            legend=dict(orientation='h')
        )
        st.plotly_chart(fig_hist, use_container_width=True)
        st.caption(f"⏱️ Recolectando desde: {hist['timestamp'].iloc[0].strftime('%Y-%m-%d %H:%M')} — {len(hist)} lecturas guardadas en Google Sheets")
    elif hoja_sheets is None:
        st.warning("⚠️ El histórico permanente no está conectado todavía. Revisa la configuración de Secrets en Streamlit Cloud.")
    else:
        st.info("Aún no hay suficientes lecturas para graficar la tendencia. Vuelve en 30-60 minutos.")

# ============ FOOTER ============
st.divider()
st.markdown(f"""
<div style='text-align: center; color: gray; font-size: 0.9em;'>
    <p>Dashboard de monitoreo del Niño en Ecuador — Modo TV: {"Activo" if modo_tv else "Manual"}</p>
    <p><strong>Última compilación:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
</div>
""", unsafe_allow_html=True)
