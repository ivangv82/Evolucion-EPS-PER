import streamlit as st
import requests
import pandas as pd
import yfinance as yf
import numpy as np
import json
import os
import matplotlib.pyplot as plt

# ==============================
# 📌 1. FUNCIONES OPTIMIZADAS Y CACHEADAS
# ==============================

@st.cache_data
def cargar_mapeo_tickers_ciks(ruta_json):
    """
    Carga el archivo JSON de la SEC y crea un diccionario para un mapeo
    rápido de Ticker -> CIK. La función se cachea para no leer el archivo
    en cada ejecución.
    """
    if not os.path.exists(ruta_json):
        st.error(f"Error: No se encontró el archivo '{ruta_json}'. Asegúrate de que está en el directorio correcto.")
        return None
    with open(ruta_json, "r") as file:
        data = json.load(file)
    ticker_to_cik = {item["ticker"].upper(): str(item["cik_str"]).zfill(10) for item in data.values()}
    return ticker_to_cik

@st.cache_data
def obtener_datos_eps_sec(cik):
    """
    Obtiene y procesa los datos de EPS de una empresa desde la API de la SEC
    usando su CIK. Cachea el resultado para evitar múltiples llamadas a la API
    para el mismo CIK.
    """
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/EarningsPerShareBasic.json"
    headers = {"User-Agent": "ivan@formacionenbolsa.com"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    json_data = response.json()
    
    if "USD/shares" not in json_data["units"]:
        return None

    eps_data = pd.DataFrame(json_data["units"]["USD/shares"])
    eps_data = eps_data.rename(columns={"end": "Fecha", "val": "EPS Reportado"})
    eps_data["Fecha"] = pd.to_datetime(eps_data["Fecha"], errors="coerce")
    eps_data["filed"] = pd.to_datetime(eps_data["filed"], errors="coerce")

    mask_10k = eps_data["form"].isin(["10-K", "10-K/A"])
    mask_fy = eps_data["fp"] == "FY"
    eps_10k_fy = eps_data[mask_10k & mask_fy].copy()

    if eps_10k_fy.empty:
        return pd.DataFrame()

    eps_10k_fy.sort_values(["fy", "Fecha", "filed"], ascending=[True, False, False], inplace=True)
    eps_10k_anual = eps_10k_fy.groupby("fy", as_index=False).first()
    eps_10k_anual = eps_10k_anual.rename(columns={"EPS Reportado": "EPS Año Fiscal"})
    
    return eps_10k_anual

@st.cache_data
def obtener_precios_historicos(ticker):
    """
    Obtiene los precios de cierre históricos desde yfinance.
    Cachea el resultado para el ticker solicitado.
    """
    stock = yf.Ticker(ticker)
    hist = stock.history(period="max")
    if hist.empty:
        return None
    prices_df = hist["Close"].reset_index()
    prices_df.columns = ["Fecha", "Precio"]
    prices_df["Fecha"] = pd.to_datetime(prices_df["Fecha"]).dt.tz_localize(None)
    return prices_df

def calcular_per_y_fusionar(eps_df, prices_df):
    """
    Fusiona los dataframes de EPS y precios, y calcula el PER.
    """
    eps_df = eps_df.sort_values("Fecha")
    prices_df = prices_df.sort_values("Fecha")
    eps_price_df = pd.merge_asof(eps_df, prices_df, on="Fecha", direction="backward")
    
    eps_price_df["PER"] = np.where(eps_price_df["EPS Año Fiscal"] > 0,
                                   eps_price_df["Precio"] / eps_price_df["EPS Año Fiscal"],
                                   None)
    
    eps_price_df.replace([float("inf"), -float("inf")], None, inplace=True)
    return eps_price_df


# ==============================
# 📌 2. INTERFAZ PRINCIPAL EN STREAMLIT
# ==============================
st.title("📊 Analizador de Valor Intrínseco")
st.write("Herramienta para analizar el EPS, PER y proyectar el valor futuro de una empresa.")

ruta_json = "company_tickers.json"
ticker_cik_map = cargar_mapeo_tickers_ciks(ruta_json)

if ticker_cik_map:
    ticker = st.text_input("Introduce el ticker de la empresa (Ej: AAPL, MSFT, GOOGL):", key="ticker_input").strip().upper()

    if ticker:
        CIK = ticker_cik_map.get(ticker)
        
        if not CIK:
            st.error(f"No se encontró un CIK para el ticker '{ticker}'. Verifica que el ticker sea correcto y esté en el archivo `company_tickers.json`.")
        else:
            try:
                with st.spinner(f"🔍 Obteniendo datos para {ticker}... Por favor, espera."):
                    eps_anual_df = obtener_datos_eps_sec(CIK)
                    precios_df = obtener_precios_historicos(ticker)

                if eps_anual_df is None or eps_anual_df.empty:
                    st.warning(f"No se encontraron datos de 'EarningsPerShareBasic' en formato 10-K para '{ticker}' en la base de datos de la SEC.")
                elif precios_df is None:
                    st.warning(f"No se pudieron obtener los datos de precios para '{ticker}' desde yfinance.")
                else:
                    eps_price_df = calcular_per_y_fusionar(eps_anual_df, precios_df)
                    st.success(f"¡Análisis para {ticker} completado!")

                    tab1, tab2, tab3 = st.tabs(["📊 Resumen y Gráficos", "💡 Proyección de Valor", "🗃️ Datos Completos"])

                    with tab1:
                        st.subheader("📈 EPS y PER por Año Fiscal")
                        st.dataframe(eps_price_df[["fy", "Fecha", "EPS Año Fiscal", "Precio", "PER"]].round(2))
                        st.info("Nota: El PER se muestra como 'N/A' si el EPS es negativo o cero.")

                        st.subheader("📊 Evolución del EPS y PER")
                        fig, ax1 = plt.subplots(figsize=(10, 5))
                        ax1.set_xlabel("Año Fiscal")
                        ax1.set_ylabel("EPS (USD)", color="tab:blue")
                        ax1.plot(eps_price_df["fy"], eps_price_df["EPS Año Fiscal"], marker="o", color="tab:blue", label="EPS")
                        ax1.tick_params(axis="y", labelcolor="tab:blue")
                        
                        ax2 = ax1.twinx()
                        ax2.set_ylabel("PER", color="tab:red")
                        ax2.plot(eps_price_df["fy"], eps_price_df["PER"], marker="s", linestyle="--", color="tab:red", label="PER")
                        ax2.tick_params(axis="y", labelcolor="tab:red")
                        
                        fig.tight_layout()
                        st.pyplot(fig)
                        
                        st.subheader("📊 Crecimiento y PER Promedio")
                        def calcular_crecimiento(data, años):
                            data = data.dropna()
                            if len(data) < años: return None
                            valor_inicial = data.iloc[-años]
                            if valor_inicial <= 0: return None
                            return ((data.iloc[-1] / valor_inicial) ** (1 / años) - 1) * 100

                        eps_crecimiento_10 = calcular_crecimiento(eps_price_df["EPS Año Fiscal"], 10)
                        eps_crecimiento_5 = calcular_crecimiento(eps_price_df["EPS Año Fiscal"], 5)
                        per_promedio_10 = eps_price_df["PER"].dropna().tail(10).mean()
                        per_promedio_5 = eps_price_df["PER"].dropna().tail(5).mean()

                        crecimiento_df = pd.DataFrame({
                            "Métrica": ["Crecimiento EPS (10 años, CAGR)", "Crecimiento EPS (5 años, CAGR)", "PER Promedio (10 años)", "PER Promedio (5 años)"],
                            "Valor": [f"{eps_crecimiento_10:.2f} %" if eps_crecimiento_10 is not None else "N/A",
                                      f"{eps_crecimiento_5:.2f} %" if eps_crecimiento_5 is not None else "N/A",
                                      f"{per_promedio_10:.2f}" if pd.notna(per_promedio_10) else "N/A",
                                      f"{per_promedio_5:.2f}" if pd.notna(per_promedio_5) else "N/A"]
                        })
                        st.table(crecimiento_df)

                    with tab2:
                        st.subheader("💡 Proyección de Precio Intrínseco")
                        
                        # Para evitar el "salto", usamos un contenedor que siempre está presente
                        # y mostramos su contenido de forma condicional.
                        projection_container = st.container()

                        with projection_container:
                            opcion_proyeccion = st.radio("¿Desea hacer una previsión del precio?", ("No", "Sí"), key="proy_radio", horizontal=True)
                            
                            if opcion_proyeccion == "Sí":
                                st.markdown("---") # Separador visual
                                st.write("##### **Parámetros de la Proyección**")

                                col1, col2 = st.columns(2)
                                with col1:
                                    per_opciones = {
                                        "PER medio 10 años": per_promedio_10, "PER medio 5 años": per_promedio_5,
                                        "Ingresar PER manualmente": None
                                    }
                                    per_seleccion = st.radio("Seleccione el **PER base**:", [k for k,v in per_opciones.items() if v is not None] + ["Ingresar PER manualmente"], key="per_radio")
                                    if per_seleccion == "Ingresar PER manualmente":
                                        per_base = st.number_input("PER base:", min_value=0.1, step=0.1, format="%.2f", key="per_manual")
                                    else:
                                        per_base = per_opciones[per_seleccion]
                                
                                with col2:
                                    cagr_opciones = {
                                        "CAGR últimos 10 años": eps_crecimiento_10, "CAGR últimos 5 años": eps_crecimiento_5,
                                        "Ingresar CAGR manualmente": None
                                    }
                                    cagr_seleccion = st.radio("Seleccione el **CAGR del EPS**:", [k for k,v in cagr_opciones.items() if v is not None] + ["Ingresar CAGR manualmente"], key="cagr_radio")
                                    if cagr_seleccion == "Ingresar CAGR manualmente":
                                        cagr_eps = st.number_input("CAGR del EPS (%):", min_value=-50.0, max_value=100.0, step=0.1, format="%.2f", key="cagr_manual")
                                    else:
                                        cagr_eps = cagr_opciones[cagr_seleccion]

                                if per_base and cagr_eps is not None:
                                    st.markdown("---")
                                    current_eps = eps_price_df["EPS Año Fiscal"].iloc[-1]
                                    current_fy = int(eps_price_df["fy"].iloc[-1])
                                    años_futuros = np.arange(1, 6)
                                    future_fys = [current_fy + i for i in años_futuros]
                                    projected_eps = current_eps * ((1 + cagr_eps / 100) ** años_futuros)
                                    
                                    precio_pesimista = projected_eps * (per_base * 0.8)
                                    precio_base_val = projected_eps * per_base
                                    precio_optimista = projected_eps * (per_base * 1.2)

                                    proyeccion_df = pd.DataFrame({
                                        "Año Fiscal": future_fys, "EPS Proyectado": projected_eps,
                                        "Precio (Pesimista)": precio_pesimista, "Precio (Base)": precio_base_val,
                                        "Precio (Optimista)": precio_optimista
                                    })
                                    st.subheader("📊 Proyección de Precio en los Próximos 5 Años")
                                    st.table(proyeccion_df.round(2))

                                    # =========================================================
                                    # ✅ GRÁFICO DE PROYECCIÓN AÑADIDO DE VUELTA
                                    # =========================================================
                                    st.subheader("📈 Evolución: Precio Histórico vs. Proyección")
                                    fig2, ax = plt.subplots(figsize=(10, 5))
                                    
                                    # Datos históricos (últimos 10 años si es posible)
                                    historical_df = eps_price_df.tail(10)
                                    ax.plot(historical_df["fy"], historical_df["Precio"], marker="o", linestyle="-", color="blue", label="Precio Histórico Anual")
                                    
                                    # Conectar el último precio histórico con la primera proyección
                                    all_fys = list(historical_df["fy"]) + future_fys
                                    pesimista_plot = list(np.full(len(historical_df)-1, np.nan)) + [historical_df["Precio"].iloc[-1]] + list(precio_pesimista)
                                    base_plot = list(np.full(len(historical_df)-1, np.nan)) + [historical_df["Precio"].iloc[-1]] + list(precio_base_val)
                                    optimista_plot = list(np.full(len(historical_df)-1, np.nan)) + [historical_df["Precio"].iloc[-1]] + list(precio_optimista)
                                    
                                    # Datos proyectados
                                    ax.plot(all_fys, pesimista_plot, marker="o", linestyle="--", color="red", label="Proyección Pesimista")
                                    ax.plot(all_fys, base_plot, marker="o", linestyle="--", color="green", label="Proyección Base")
                                    ax.plot(all_fys, optimista_plot, marker="o", linestyle="--", color="orange", label="Proyección Optimista")

                                    ax.set_xlabel("Año Fiscal")
                                    ax.set_ylabel("Precio (USD)")
                                    ax.legend()
                                    ax.grid(True, linestyle='--', alpha=0.6)
                                    st.pyplot(fig2)

                                else:
                                    st.warning("Por favor, seleccione o ingrese valores válidos para PER y CAGR para continuar.")

                    with tab3:
                        st.subheader("🗃️ Datos Históricos Completos")
                        st.write("A continuación se muestran los datos completos utilizados para el análisis.")
                        st.dataframe(eps_price_df.round(2))
                        
                        csv = eps_price_df.to_csv(index=False).encode("utf-8")
                        st.download_button("📥 Descargar Datos en CSV", csv, f"datos_analisis_{ticker}.csv", "text/csv")

            except requests.exceptions.HTTPError as e:
                st.error(f"❌ Error de conexión al obtener datos de la SEC: {e}")
            except Exception as e:
                st.error(f"Ocurrió un error inesperado: {e}")

    else:
        st.info("💡 Introduce un ticker para comenzar el análisis.")
