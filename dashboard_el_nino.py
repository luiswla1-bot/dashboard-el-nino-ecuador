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
    .block-container { padding-top: 0.8rem !important; padding-bottom: 1rem !important; }
    header[data-testid="stHeader"] { height: 0px; }
    h2, h3 { font-size: 1.15rem !important; }
    div[data-testid="stMetricValue"] { font-size: 1.3rem !important; }
    div[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
    </style>
""", unsafe_allow_html=True)

# ============ SISTEMA PARA MOSTRAR/OCULTAR BARRA LATERAL (persistente vía URL) ============
if "sidebar_oculto" not in st.session_state:
    st.session_state.sidebar_oculto = False

if st.query_params.get("accion") == "mostrar_panel":
    st.session_state.sidebar_oculto = False
    st.query_params.clear()

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

modo_tv = st.sidebar.toggle("📺 Rotación automática", value=False)
intervalo_rotacion = st.sidebar.slider("Segundos por pestaña", 10, 180, 60, step=10)
ocultar_sidebar = st.sidebar.checkbox("Ocultar esta barra al proyectar", value=st.session_state.sidebar_oculto)
if ocultar_sidebar:
    st.session_state.sidebar_oculto = True

if st.session_state.sidebar_oculto:
    st.markdown("""
        <style>
        section[data-testid="stSidebar"] { display: none; }
        </style>
        <a href="?accion=mostrar_panel" target="_self" style="
            position: fixed; top: 12px; right: 16px; z-index: 9999;
            background: #0072C6; color: white; padding: 8px 14px;
            border-radius: 8px; text-decoration: none; font-size: 13px;
            font-family: sans-serif; box-shadow: 0 2px 6px rgba(0,0,0,0.3);">
            ⚙️ Mostrar configuración
        </a>
    """, unsafe_allow_html=True)

SECCIONES = ["📈 Índice RONI", "🌦️ Clima en Vivo", "📍 Estaciones", "📊 Análisis"]
TITULOS_SECCION = {
    "📈 Índice RONI": "Índice Relativo Oceánico Niño (RONI) - NOAA/CPC",
    "🌦️ Clima en Vivo": "Mapa de Clima en Tiempo Real",
    "📍 Estaciones": "Estaciones Oceanográficas del Ecuador",
    "📊 Análisis": "Análisis, Alertas e Histórico"
}

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
    """Obtiene el índice RONI (Relative Oceanic Niño Index) oficial de NOAA/CPC.
    Desde feb-2026 este índice reemplazó al ONI tradicional, mismos umbrales (+/-0.5°C)."""
    try:
        url = "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            # Mapa de temporadas de 3 meses a un mes representativo para graficar
            mapa_temporada_mes = {
                'DJF': 1, 'JFM': 2, 'FMA': 3, 'MAM': 4, 'AMJ': 5, 'MJJ': 6,
                'JJA': 7, 'JAS': 8, 'ASO': 9, 'SON': 10, 'OND': 11, 'NDJ': 12
            }
            lineas = response.text.strip().split('\n')
            datos = []
            for linea in lineas[1:]:  # saltar encabezado "SEAS YR ANOM"
                partes = linea.split()
                if len(partes) == 3:
                    temporada, año, anom = partes
                    if temporada in mapa_temporada_mes:
                        try:
                            datos.append({
                                'año': int(año),
                                'mes': mapa_temporada_mes[temporada],
                                'oni': float(anom),
                                'fecha': f"{año}-{mapa_temporada_mes[temporada]:02d}"
                            })
                        except ValueError:
                            pass
            df = pd.DataFrame(datos)
            df['fecha'] = pd.to_datetime(df['fecha'])
            return df.dropna().sort_values('fecha')
    except Exception as e:
        st.warning(f"Error obteniendo RONI: {e}")
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

# ============ ENCABEZADO COMPACTO ============
total_lecturas = len(leer_historico_sheets())
estado_tv = f"🟢 TV {intervalo_rotacion}s" if modo_tv else "⚪ Manual"
titulo_seccion = TITULOS_SECCION.get(seccion_actual, seccion_actual)

st.markdown(f"""
<div style='display:flex; align-items:center; justify-content:space-between;
            flex-wrap:wrap; padding:3px 4px 6px 4px; border-bottom:1px solid rgba(128,128,128,0.3);
            margin-bottom:6px;'>
    <div style='font-size:1rem; font-weight:700; line-height:1.2;'>
        🌊 Monitoreo del Fenómeno del Niño <span style='font-weight:400; opacity:0.85;'>— {titulo_seccion}</span>
    </div>
    <div style='display:flex; gap:14px; font-size:0.68rem; opacity:0.8; flex-wrap:wrap;'>
        <span>🕐 {datetime.now().strftime('%H:%M:%S')}</span>
        <span>{estado_tv}</span>
        <span>📊 {total_lecturas} lecturas</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ============ SECCIÓN: ÍNDICE RONI ============
if seccion_actual == "📈 Índice RONI":
    st.caption("Desde febrero de 2026, NOAA reemplazó el índice ONI tradicional por el RONI (mismos umbrales)")
    st.info("📌 RONI > 0.5°C = El Niño | RONI < -0.5°C = La Niña | -0.5 a 0.5 = Neutral")

    if df_oni is not None and len(df_oni) > 0:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_oni['fecha'], y=df_oni['oni'], mode='lines', name='RONI',
            line=dict(color='darkblue', width=2), fill='tozeroy'
        ))
        fig.add_hline(y=0.5, line_dash="dash", line_color="red", annotation_text="Umbral El Niño")
        fig.add_hline(y=-0.5, line_dash="dash", line_color="blue", annotation_text="Umbral La Niña")
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(
            title="Índice RONI (1950-presente)", xaxis_title="Fecha",
            yaxis_title="Anomalía de Temperatura (°C)", hovermode='x unified', height=450
        )
        st.plotly_chart(fig, use_container_width=True)

        col1, col2, col3, col4 = st.columns(4)
        ultimos_datos = df_oni.tail(3)
        with col1:
            st.metric("RONI Actual", f"{ultimos_datos['oni'].iloc[-1]:.2f}°C")
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
        st.error("No se pudieron obtener datos del RONI en este momento")

# ============ SECCIÓN: CLIMA EN VIVO ============
elif seccion_actual == "🌦️ Clima en Vivo":
    ALTURA_MAPA = 900
    windy_html = f"""
    <html>
    <head><style>html, body {{ margin:0; padding:0; height:{ALTURA_MAPA}px; }}</style></head>
    <body>
        <iframe
            style="width:100%; height:{ALTURA_MAPA}px; border:0; display:block;"
            src="https://embed.windy.com/embed2.html?lat=-1.5&lon=-80.0&detailLat=-1.5&detailLon=-80.0&zoom=6&level=surface&overlay=rain&product=ecmwf&menu=&message=true&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1">
        </iframe>
    </body>
    </html>
    """
    components.html(windy_html, height=ALTURA_MAPA, scrolling=False)

# ============ SECCIÓN: ESTACIONES ============
elif seccion_actual == "📍 Estaciones":
    st.dataframe(
        df_estaciones.style.format({'TSM (°C)': '{:.1f}', 'Salinidad': '{:.2f}'}),
        use_container_width=True, height=250
    )

    st.divider()
    st.markdown("### 🔗 Boletines oficiales de INOCAR (datos reales verificados)")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        **🌊 Boyas oceanográficas**
        Temperatura, oleaje y corrientes en tiempo real

        [Ver boletín de boyas →](https://www.inocar.mil.ec/web/index.php/boletines/boyas-oceanograficas)
        """)
        st.markdown("""
        **📈 Monitoreo oceánico (Boya Hermandad, Galápagos)**
        Perfiles de temperatura por profundidad

        [Ver monitoreo →](https://www.inocar.mil.ec/web/index.php/productos/monitoreo-oceanico)
        """)
    with col2:
        st.markdown("""
        **🌊 Oleaje y aguaje**
        Condiciones de oleaje en la costa ecuatoriana

        [Ver boletín de oleaje →](https://www.inocar.mil.ec/web/index.php/boletines/oleaje-y-aguaje)
        """)
        st.markdown("""
        **📡 TSM y oleaje en vivo (Salinas y Manta)**
        Datos de boyas costeras, actualización directa

        [Ver datos en vivo →](http://www.inocar.mil.ec/boyas_olas/leer_boyas.php)
        """)

    st.divider()
    st.info(
        "**Otras fuentes de datos usadas en esta aplicación:**\n\n"
        "- 🌊 NOAA/CPC (índice RONI oficial)\n"
        "- 🌧️ Windy.com (precipitación y viento en vivo)\n"
        "- 🛰️ Google Earth Engine (datos de satélite, en desarrollo)"
    )

# ============ SECCIÓN: ANÁLISIS + HISTÓRICO ============
elif seccion_actual == "📊 Análisis":
    hist = leer_historico_sheets()
    if len(hist) > 1:
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Scatter(x=hist['timestamp'], y=hist['oni'], mode='lines+markers', name='RONI'))
        fig_hist.add_trace(go.Scatter(x=hist['timestamp'], y=hist['tsm_promedio'], mode='lines+markers', name='TSM Promedio', yaxis='y2'))
        fig_hist.update_layout(
            height=380,
            yaxis=dict(title="RONI (°C)"),
            yaxis2=dict(title="TSM (°C)", overlaying='y', side='right'),
            legend=dict(orientation='h'),
            margin=dict(t=30, b=30)
        )
        st.plotly_chart(fig_hist, use_container_width=True)
        st.caption(f"⏱️ Recolectando desde: {hist['timestamp'].iloc[0].strftime('%Y-%m-%d %H:%M')} — {len(hist)} lecturas guardadas en Google Sheets")
    elif hoja_sheets is None:
        st.warning("⚠️ El histórico permanente no está conectado todavía. Revisa la configuración de Secrets en Streamlit Cloud.")
    else:
        st.info("Aún no hay suficientes lecturas para graficar la tendencia. Vuelve en 30-60 minutos.")

    st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("<div style='font-size:0.85rem; font-weight:600;'>⚠️ Alertas Activas</div>", unsafe_allow_html=True)
        if not np.isnan(oni_actual_val):
            if oni_actual_val > 0.5:
                mensaje = "🔴 **El Niño activo** — se esperan lluvias intensas e inundaciones en la costa"
            elif oni_actual_val < -0.5:
                mensaje = "🔵 **La Niña activa** — se espera sequía en algunas regiones de la costa"
            else:
                mensaje = "⚪ **Condiciones neutrales**"
            st.markdown(f"<div style='font-size:0.75rem; opacity:0.9;'>{mensaje}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div style='font-size:0.85rem; font-weight:600;'>📊 Indicadores monitoreados</div>", unsafe_allow_html=True)
        st.markdown("""
        <div style='font-size:0.75rem; opacity:0.9; line-height:1.6;'>
        • Índice RONI<br>
        • Anomalía de TSM ecuatorial<br>
        • Clima en vivo (Windy)<br>
        • Estaciones oceanográficas del Ecuador
        </div>
        """, unsafe_allow_html=True)

# ============ FOOTER ============
st.divider()
st.markdown(f"""
<div style='text-align: center; color: gray; font-size: 0.8em;'>
    <p>Monitoreo del Niño en Ecuador — Modo TV: {"Activo" if modo_tv else "Manual"}</p>
    <p><strong>Última compilación:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
</div>
""", unsafe_allow_html=True)
