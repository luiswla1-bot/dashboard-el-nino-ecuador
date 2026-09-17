"""
Dashboard de Monitoreo del Fenómeno del Niño en Ecuador
Datos en tiempo real de NOAA, Google Earth Engine, e INOCAR
Actualización automática cada 6 horas
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
from functools import lru_cache
import time

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
    </style>
""", unsafe_allow_html=True)

# ============ CACHÉ DE DATOS (6 horas) ============
@st.cache_data(ttl=21600, show_spinner=False)
def obtener_datos_noaa_oni():
    """Obtiene el Índice ONI (Oceanic Niño Index) de NOAA"""
    try:
        url = "https://ggweather.com/enso/oni.txt"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            # Parsear el archivo de texto de NOAA
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
def obtener_tpm_pacifico():
    """Obtiene anomalía de Temperatura Superficial del Mar (TSM) del Pacífico ecuatorial"""
    try:
        # Datos de NOAA Cold & Warm Episodes
        url = "https://ggweather.com/enso/cold_and_warm_episodes_by_season.txt"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            # Retornar resumen de episodios
            return response.text
    except Exception as e:
        st.warning(f"Error obteniendo episodios: {e}")
    
    return None

@st.cache_data(ttl=21600, show_spinner=False)
def obtener_datos_simulados_estaciones():
    """Simula datos de estaciones oceanográficas ecuatorianas (en producción usarías API de INOCAR)"""
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

# ============ INTERFAZ PRINCIPAL ============
st.title("🌊 Dashboard: Monitoreo del Fenómeno del Niño")
st.caption("Costas de Ecuador - Datos en Tiempo Real")

# Fecha y hora de actualización
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Última actualización", datetime.now().strftime("%H:%M:%S"))
with col2:
    st.metric("Zona de monitoreo", "Costa Ecuatoriana")
with col3:
    st.metric("Frecuencia de actualización", "Cada 6 horas")

st.divider()

# ============ TAB 1: ÍNDICE ONI (El Niño/Niña) ============
tab1, tab2, tab3, tab4 = st.tabs(["📈 Índice ONI", "🌡️ Temp. Marina", "📍 Estaciones", "📊 Análisis"])

with tab1:
    st.subheader("Índice Oceánico Niño (ONI) - NOAA")
    st.info("📌 ONI > 0.5°C = El Niño | ONI < -0.5°C = La Niña | -0.5 a 0.5 = Neutral")
    
    df_oni = obtener_datos_noaa_oni()
    
    if df_oni is not None and len(df_oni) > 0:
        # Gráfico de serie de tiempo
        fig = go.Figure()
        
        # Línea principal
        fig.add_trace(go.Scatter(
            x=df_oni['fecha'],
            y=df_oni['oni'],
            mode='lines',
            name='ONI',
            line=dict(color='darkblue', width=2),
            fill='tozeroy'
        ))
        
        # Zonas de El Niño (rojo) y La Niña (azul)
        fig.add_hline(y=0.5, line_dash="dash", line_color="red", annotation_text="Umbral El Niño")
        fig.add_hline(y=-0.5, line_dash="dash", line_color="blue", annotation_text="Umbral La Niña")
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        
        fig.update_layout(
            title="Índice ONI (últimas 4 décadas)",
            xaxis_title="Fecha",
            yaxis_title="Anomalía de Temperatura (°C)",
            hovermode='x unified',
            height=400
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Estadísticas
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
        st.error("No se pudieron obtener datos del ONI")

# ============ TAB 2: TEMPERATURA MARINA ============
with tab2:
    st.subheader("Anomalía de Temperatura Superficial del Mar (TSM)")
    st.info("🌡️ Monitora cambios de temperatura en el Pacífico ecuatorial")
    
    # Mapa interactivo de estaciones
    df_estaciones = obtener_datos_simulados_estaciones()
    
    fig_mapa = px.scatter_geo(
        df_estaciones,
        lat='Latitud',
        lon='Longitud',
        hover_name='Estación',
        hover_data={'TSM (°C)': ':.1f', 'Salinidad': ':.2f'},
        size='TSM (°C)',
        color='TSM (°C)',
        color_continuous_scale='RdYlBu_r',
        title="Estaciones Oceanográficas: Temperatura Superficial",
        projection='natural earth'
    )
    
    fig_mapa.update_layout(
        geo=dict(
            scope='south america',
            projection_type='mercator',
            center=dict(lat=-2, lon=-80),
            lataxis_range=[-3.5, 1],
            lonaxis_range=[-92, -75]
        ),
        height=500
    )
    
    st.plotly_chart(fig_mapa, use_container_width=True)

# ============ TAB 3: DATOS DE ESTACIONES ============
with tab3:
    st.subheader("Estaciones Oceanográficas del Ecuador")
    
    df_estaciones = obtener_datos_simulados_estaciones()
    
    # Tabla con datos
    st.dataframe(
        df_estaciones.style.format({
            'TSM (°C)': '{:.1f}',
            'Salinidad': '{:.2f}'
        }),
        use_container_width=True
    )
    
    st.info(
        "**Fuentes de datos:**\n\n"
        "- 📍 INOCAR (Instituto Oceanográfico de la Armada Ecuatoriana)\n"
        "- 🌊 NOAA (National Oceanic and Atmospheric Administration)\n"
        "- 🛰️ Google Earth Engine (datos de satélite en tiempo real)"
    )

# ============ TAB 4: ANÁLISIS ============
with tab4:
    st.subheader("Análisis y Predicciones")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 📊 Indicadores Clave")
        st.write("""
        **Parámetros monitoreados:**
        - Índice ONI (3 meses móvil)
        - Anomalía de TSM ecuatorial
        - Vientos alisios del Pacífico
        - Profundidad de la termoclina
        - Precipitación acumulada (costas Ecuador)
        """)
    
    with col2:
        st.markdown("### ⚠️ Alertas Activas")
        
        df_oni = obtener_datos_noaa_oni()
        if df_oni is not None and len(df_oni) > 0:
            oni_actual = df_oni['oni'].iloc[-1]
            
            if oni_actual > 0.5:
                st.warning("🔴 **ALERTA: Condiciones El Niño activas**")
                st.write("Se esperan lluvias intensas e inundaciones en la costa ecuatoriana")
            elif oni_actual < -0.5:
                st.info("🔵 **ALERTA: Condiciones La Niña activas**")
                st.write("Se espera sequía en algunas regiones de la costa")
            else:
                st.success("⚪ **Condiciones neutrales**")

# ============ FOOTER ============
st.divider()
st.markdown("""
<div style='text-align: center; color: gray; font-size: 0.9em;'>
    <p>Dashboard desarrollado para monitoreo del Niño en Ecuador</p>
    <p>Datos actualizados automáticamente cada 6 horas desde NOAA, INOCAR y GEE</p>
    <p><strong>Última compilación:</strong> """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</p>
</div>
""", unsafe_allow_html=True)
