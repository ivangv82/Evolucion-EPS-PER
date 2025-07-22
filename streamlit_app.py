import streamlit as st
import requests
import pandas as pd
import yfinance as yf
import numpy as np
import json
import os
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# ==============================
# 📌 1. FUNCIONES
# (Sin cambios en esta sección)
# ==============================
@st.cache_data
def cargar_mapeo_tickers_ciks(ruta_json):
    if not os.path.exists(ruta_json):
        st.error(f"Error: No se encontró el archivo '{ruta_json}'.")
        return None
    with open(ruta_json, "r") as file:
        data = json.load(file)
    ticker_to_cik = {item["ticker"].upper(): str(item["cik_str"]).zfill(10) for item in data.values()}
    return ticker_to_cik

@st.cache_data
def obtener_datos_sec(cik):
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
    mask = eps_data["form"].isin(["10-K", "10-K/A"]) & (eps_data["fp"] == "FY")
    eps_anual_data = eps_data[mask].copy()
    if eps_anual_data.empty:
        return pd.DataFrame()
    eps_anual_data.sort_values(by=["fy", "filed"], ascending=[False, False], inplace=True)
    final_eps = eps_anual_data.drop_duplicates(subset="fy", keep="first")
    final_eps.sort_values(by="fy", ascending=True, inplace=True)
    final_eps = final_eps.rename(columns={"EPS Reportado": "EPS Año Fiscal"})
    return final_eps

@st.cache_data
def obtener_datos_yfinance(ticker):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="max")
    if hist.empty:
        return None, None
    info = stock.info
    current_price = info.get("currentPrice") or hist['Close'].iloc[-1]
    trailing_eps = info.get("trailingEps")
    prices_df = hist["Close"].reset_index()
    prices_df.columns = ["Fecha", "Precio"]
    prices_df["Fecha"] = pd.to_datetime(prices_df["Fecha"]).dt.tz_localize(None)
    return prices_df, {"price": current_price, "eps": trailing_eps}

def calcular_per_y_fusionar(eps_df, prices_df):
    eps_df_sorted = eps_df.sort_values("Fecha")
    prices_df_sorted = prices_df.sort_values("Fecha")
    eps_price_df = pd.merge_asof(eps_df_sorted, prices_df_sorted, on="Fecha", direction="backward")
    eps_price_df["PER"] = np.where(eps_price_df["EPS Año Fiscal"] > 0,
                                   eps_price_df["Precio"] / eps_price_df["EPS Año Fiscal"],
                                   None)
    eps_price_df.replace([float("inf"), -float("inf")], None, inplace=True)
    return eps_price_df

# ==============================
# 📌 2. INTERFAZ PRINCIPAL
# ==============================
st.title("📊 Analizador de Valor Intrínseco")

ruta_json = "company_tickers.json"
ticker_cik_map = cargar_mapeo_tickers_ciks(ruta_json)

if ticker_cik_map:
    ticker = st.text_input("Introduce el ticker de la empresa (Ej: AAPL, MSFT, GOOGL):", key="ticker_input").strip().upper()

    if ticker:
        if 'current_ticker' not in st.session_state or st.session_state.current_ticker != ticker:
            st.session_state.current_ticker = ticker
            st.session_state.projection_results = None

        CIK = ticker_cik_map.get(ticker)
        
        if not CIK:
            st.error(f"No se encontró un CIK para el ticker '{ticker}'.")
        else:
            try:
                with st.spinner(f"🔍 Obteniendo datos para {ticker}..."):
                    eps_anual_df = obtener_datos_sec(CIK)
                    precios_df, ttm_data = obtener_datos_yfinance(ticker)

                if eps_anual_df is None or eps_anual_df.empty:
                    st.warning(f"No se encontraron datos de EPS anuales (10-K) para '{ticker}' en la SEC.")
                elif precios_df is None:
                    st.warning(f"No se pudieron obtener los datos de precios para '{ticker}' desde yfinance.")
                else:
                    eps_price_df = calcular_per_y_fusionar(eps_anual_df, precios_df)
                    st.success(f"¡Análisis para {ticker} completado!")

                    tab1, tab2, tab3 = st.tabs(["📊 Resumen y Gráficos", "💡 Proyección de Valor", "🗃️ Datos Completos"])

                    with tab1:
                        # (Sin cambios en esta pestaña)
                        st.subheader(f"Situación Actual (TTM) a {datetime.now().strftime('%d/%m/%Y')}")
                        per_ttm = (ttm_data['price'] / ttm_data['eps']) if ttm_data.get('price') and ttm_data.get('eps') and ttm_data['eps'] > 0 else "N/A"
                        
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Precio Actual", f"${ttm_data['price']:.2f}" if ttm_data.get('price') else "N/A")
                        col2.metric("EPS (TTM)", f"${ttm_data['eps']:.2f}" if ttm_data.get('eps') else "N/A")
                        col3.metric("PER (TTM)", f"{per_ttm:.2f}" if isinstance(per_ttm, float) else per_ttm)
                        st.markdown("---")
                        
                        st.subheader("📈 Análisis Histórico Anual (basado en informes 10-K)")
                        st.dataframe(eps_price_df[["fy", "Fecha", "EPS Año Fiscal", "Precio", "PER"]].round(2))
                        
                        st.subheader("📊 Evolución del EPS y PER Históricos")
                        fig, ax1 = plt.subplots(figsize=(10, 5))
                        ax1.set_xlabel("Año Fiscal")
                        ax1.set_ylabel("EPS (USD)", color="tab:blue")
                        ax1.plot(eps_price_df["fy"], eps_price_df["EPS Año Fiscal"], marker="o", color="tab:blue", label="EPS")
                        
                        ax2 = ax1.twinx()
                        ax2.set_ylabel("PER", color="tab:red")
                        ax2.plot(eps_price_df["fy"], eps_price_df["PER"], marker="s", linestyle="--", color="tab:red", label="PER")
                        st.pyplot(fig)
                        
                        st.subheader("📊 Crecimiento y PER Promedio Históricos")
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
                        st.write("Selecciona los parámetros y pulsa 'Calcular Proyección' para ver los resultados.")
                        st.markdown("---")

                        col1, col2 = st.columns(2)
                        with col1:
                            per_opciones = { "PER (TTM)": per_ttm if isinstance(per_ttm, float) else None, "PER medio 10 años": per_promedio_10, "PER medio 5 años": per_promedio_5, "Ingresar PER manualmente": None }
                            per_seleccion = st.radio("Seleccione el **PER base**:", [k for k,v in per_opciones.items() if v is not None] + ["Ingresar PER manualmente"], key="per_radio")
                            if per_seleccion == "Ingresar PER manualmente":
                                per_base = st.number_input("PER base:", min_value=0.1, step=0.1, format="%.2f", key="per_manual")
                            else:
                                per_base = per_opciones[per_seleccion]
                        
                        with col2:
                            cagr_opciones = { "CAGR últimos 10 años": eps_crecimiento_10, "CAGR últimos 5 años": eps_crecimiento_5, "Ingresar CAGR manualmente": None }
                            cagr_seleccion = st.radio("Seleccione el **CAGR del EPS**:", [k for k,v in cagr_opciones.items() if v is not None] + ["Ingresar CAGR manualmente"], key="cagr_radio")
                            if cagr_seleccion == "Ingresar CAGR manualmente":
                                cagr_eps = st.number_input("CAGR del EPS (%):", min_value=-50.0, max_value=100.0, step=0.1, format="%.2f", key="cagr_manual")
                            else:
                                cagr_eps = cagr_opciones[cagr_seleccion]

                        if st.button("📊 Calcular Proyección"):
                            if per_base is not None and cagr_eps is not None:
                                current_eps = eps_price_df["EPS Año Fiscal"].iloc[-1]
                                
                                # --- ✅ CAMBIO CLAVE: LÓGICA DEL GRÁFICO DE PROYECCIÓN ---
                                
                                # 1. Calcular los valores proyectados
                                años_futuros = np.arange(1, 6)
                                projected_eps = current_eps * ((1 + cagr_eps / 100) ** años_futuros)
                                
                                proyeccion_df = pd.DataFrame({
                                    "Año": años_futuros,
                                    "EPS Proyectado": projected_eps,
                                    "Precio (Pesimista)": projected_eps * (per_base * 0.8),
                                    "Precio (Base)": projected_eps * per_base,
                                    "Precio (Optimista)": projected_eps * (per_base * 1.2)
                                })
                                
                                # 2. Preparar los datos para el gráfico
                                fig2, ax = plt.subplots(figsize=(12, 6))

                                # Histórico: Precio diario de los últimos 10 años
                                ten_years_ago = datetime.now() - timedelta(days=365*10)
                                historical_prices_daily = precios_df[precios_df['Fecha'] > ten_years_ago]
                                ax.plot(historical_prices_daily['Fecha'], historical_prices_daily['Precio'], color="royalblue", label="Precio Histórico Diario")

                                # Proyecciones: Parten desde el último precio conocido
                                last_date = historical_prices_daily['Fecha'].iloc[-1]
                                last_price = historical_prices_daily['Precio'].iloc[-1]
                                
                                # Creamos las fechas futuras partiendo del último día
                                future_dates = [last_date + timedelta(days=365 * i) for i in años_futuros]

                                # Creamos las series de datos para el gráfico, uniendo el último punto histórico con la proyección
                                plot_dates = [last_date] + future_dates
                                plot_pesimista = [last_price] + list(proyeccion_df["Precio (Pesimista)"])
                                plot_base = [last_price] + list(proyeccion_df["Precio (Base)"])
                                plot_optimista = [last_price] + list(proyeccion_df["Precio (Optimista)"])

                                ax.plot(plot_dates, plot_pesimista, marker=".", linestyle="--", color="red", label="Proyección Pesimista")
                                ax.plot(plot_dates, plot_base, marker=".", linestyle="--", color="green", label="Proyección Base")
                                ax.plot(plot_dates, plot_optimista, marker=".", linestyle="--", color="orange", label="Proyección Optimista")

                                # --- FIN DEL CAMBIO ---

                                ax.set_title(f"Evolución y Proyección de Precio para {ticker}", fontsize=16)
                                ax.set_xlabel("Fecha")
                                ax.set_ylabel("Precio (USD)")
                                ax.legend()
                                ax.grid(True, linestyle='--', alpha=0.6)
                                plt.tight_layout()
                                
                                # Renombramos la columna 'Año' en la tabla para mayor claridad
                                proyeccion_df.rename(columns={"Año": "Años Vista"}, inplace=True)

                                st.session_state.projection_results = { "table": proyeccion_df, "figure": fig2 }
                            else:
                                st.warning("Por favor, asegúrate de que los valores de PER y CAGR son válidos antes de calcular.")
                                st.session_state.projection_results = None

                        if st.session_state.get('projection_results'):
                            st.markdown("---")
                            st.subheader("📊 Proyección de Precio a 5 Años Vista")
                            st.table(st.session_state.projection_results["table"].round(2))
                            st.subheader("📈 Gráfico de Evolución y Proyección")
                            st.pyplot(st.session_state.projection_results["figure"])

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
