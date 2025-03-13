import streamlit as st
import requests
import pandas as pd
import yfinance as yf
import numpy as np
import json
import os
import matplotlib.pyplot as plt

# ==============================
# 📌 Cargar el archivo de tickers y CIKs
# ==============================
ruta_json = "company_tickers.json"

def obtener_cik(ticker):
    """Busca el CIK de un ticker en el archivo JSON de la SEC."""
    if not os.path.exists(ruta_json):
        return None
    with open(ruta_json, "r") as file:
        data = json.load(file)
    for item in data.values():
        if item["ticker"].lower() == ticker.lower():
            return str(item["cik_str"]).zfill(10)
    return None

# ==============================
# 📌 INTERFAZ PRINCIPAL EN STREAMLIT
# ==============================
st.title("📊 Análisis de EPS, Precio, PER y Valor Intrínseco")

ticker = st.text_input("Introduce el ticker de la empresa (Ej: AAPL, MSFT, TSLA):").strip().upper()

if ticker:
    # Obtener CIK
    CIK = obtener_cik(ticker)
    if not CIK:
        st.error("No se encontró el CIK. Verifica el ticker ingresado.")
    else:
        url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{CIK}/us-gaap/EarningsPerShareBasic.json"
        headers = {"User-Agent": "Academia-Inversion-GPT"}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            # ==============================
            # 1. Obtención y procesamiento de datos EPS
            # ==============================
            json_data = response.json()
            eps_data = pd.DataFrame(json_data["units"]["USD/shares"])
            eps_data = eps_data.rename(columns={"end": "Fecha", "val": "EPS Reportado"})

            # Convertir fechas
            eps_data["Fecha"] = pd.to_datetime(eps_data["Fecha"], errors="coerce")
            eps_data["filed"] = pd.to_datetime(eps_data["filed"], errors="coerce")

            # Filtrar informes 10-K (o 10-K/A) con fp=="FY"
            mask_10k = eps_data["form"].isin(["10-K", "10-K/A"])
            mask_fy = eps_data["fp"] == "FY"
            eps_10k_fy = eps_data[mask_10k & mask_fy].copy()

            # Ordenar por fy, Fecha (descendente) y filed (descendente)
            eps_10k_fy.sort_values(["fy", "Fecha", "filed"], ascending=[True, False, False], inplace=True)

            # Agrupar por año fiscal y tomar la primera fila (dato definitivo)
            eps_10k_anual = eps_10k_fy.groupby("fy", as_index=False).first()
            eps_10k_anual = eps_10k_anual.rename(columns={"EPS Reportado": "EPS Año Fiscal"})

            # ==============================
            # 2. Obtención de precios históricos y cálculo del PER
            # ==============================
            stock = yf.Ticker(ticker)
            hist = stock.history(period="max")
            prices_df = hist["Close"].reset_index()
            prices_df.columns = ["Fecha", "Precio"]
            prices_df["Fecha"] = pd.to_datetime(prices_df["Fecha"]).dt.tz_localize(None)

            # Merge asof entre EPS anual y precios históricos
            eps_10k_anual = eps_10k_anual.sort_values("Fecha")
            prices_df = prices_df.sort_values("Fecha")
            eps_price_df = pd.merge_asof(eps_10k_anual, prices_df, on="Fecha", direction="backward")

            # Calcular PER
            eps_price_df["PER"] = eps_price_df["Precio"] / eps_price_df["EPS Año Fiscal"]
            eps_price_df.replace([float("inf"), -float("inf")], None, inplace=True)

            st.subheader("📈 EPS y PER por Año Fiscal")
            st.dataframe(eps_price_df[["fy", "Fecha", "EPS Año Fiscal", "Precio", "PER"]])

            #csv = eps_price_df.to_csv(index=False).encode("utf-8")
            #st.download_button("📥 Descargar EPS y PER en CSV", csv, "eps_per_data.csv", "text/csv")

            # ==============================
            # 3. Gráficos: Evolución del EPS y PER
            # ==============================
            st.subheader("📊 Evolución del EPS y PER")
            fig, ax1 = plt.subplots(figsize=(10, 5))
            ax1.set_xlabel("Año Fiscal")
            ax1.set_ylabel("EPS", color="tab:blue")
            ax1.plot(eps_price_df["fy"], eps_price_df["EPS Año Fiscal"], marker="o", color="tab:blue", label="EPS")
            ax1.tick_params(axis="y", labelcolor="tab:blue")

            ax2 = ax1.twinx()
            ax2.set_ylabel("PER", color="tab:red")
            ax2.plot(eps_price_df["fy"], eps_price_df["PER"], marker="s", linestyle="dashed", color="tab:red", label="PER")
            ax2.tick_params(axis="y", labelcolor="tab:red")

            fig.tight_layout()
            st.pyplot(fig)

            # ==============================
            # 4. Cálculo de Crecimientos y PER Promedio
            # ==============================
            def calcular_crecimiento(data, años):
                if len(data) < años:
                    return None
                return ((data.iloc[-1] / data.iloc[-años]) ** (1 / años) - 1) * 100

            eps_crecimiento_10 = calcular_crecimiento(eps_price_df["EPS Año Fiscal"], 10)
            eps_crecimiento_5 = calcular_crecimiento(eps_price_df["EPS Año Fiscal"], 5)
            per_promedio_10 = eps_price_df["PER"].tail(10).mean()
            per_promedio_5 = eps_price_df["PER"].tail(5).mean()

            st.subheader("📊 Crecimiento y PER Promedio")
            crecimiento_df = pd.DataFrame({
                "Métrica": ["Crecimiento EPS (10 años, CAGR)", "Crecimiento EPS (5 años, CAGR)",
                            "PER Promedio (10 años)", "PER Promedio (5 años)"],
                "Valor": [f"{eps_crecimiento_10:.2f} %" if eps_crecimiento_10 is not None else "N/A",
                          f"{eps_crecimiento_5:.2f} %" if eps_crecimiento_5 is not None else "N/A",
                          f"{per_promedio_10:.2f}" if per_promedio_10 is not None else "N/A",
                          f"{per_promedio_5:.2f}" if per_promedio_5 is not None else "N/A"]
            })
            st.table(crecimiento_df)

            st.subheader("📊 Escenarios de PER")
            escenarios_df = pd.DataFrame({
                "Periodo": ["10 años", "5 años"],
                "Pesimista": [per_promedio_10 * 0.8 if per_promedio_10 else None,
                              per_promedio_5 * 0.8 if per_promedio_5 else None],
                "Base": [per_promedio_10, per_promedio_5],
                "Optimista": [per_promedio_10 * 1.2 if per_promedio_10 else None,
                              per_promedio_5 * 1.2 if per_promedio_5 else None]
            })
            st.table(escenarios_df)

            # ==============================
            # 5. Proyección del Valor Intrínseco
            # ==============================
            st.subheader("💡 Proyección de Precio Intrínseco")
            opcion_proyeccion = st.radio("¿Desea hacer una previsión del precio basada en el crecimiento del EPS y el PER?",
                                         ("No", "Sí"))
            if opcion_proyeccion == "Sí":
                st.write("Seleccione las opciones para la proyección:")

                # Selección del PER base
                per_opciones = {
                    "PER medio 10 años": per_promedio_10,
                    "PER medio 5 años": per_promedio_5,
                    "Ingresar PER manualmente": None
                }
                per_seleccion = st.radio("Seleccione el PER base:", list(per_opciones.keys()))
                if per_seleccion == "Ingresar PER manualmente":
                    per_base = st.number_input("Ingrese el PER base:", min_value=0.1, step=0.1, format="%.2f")
                else:
                    per_base = per_opciones[per_seleccion]

                # Selección del CAGR del EPS
                cagr_opciones = {
                    "CAGR últimos 10 años": eps_crecimiento_10,
                    "CAGR últimos 5 años": eps_crecimiento_5,
                    "Ingresar CAGR manualmente": None
                }
                cagr_seleccion = st.radio("Seleccione el CAGR del EPS:", list(cagr_opciones.keys()))
                if cagr_seleccion == "Ingresar CAGR manualmente":
                    cagr_eps = st.number_input("Ingrese el CAGR del EPS (%):", min_value=-50.0, max_value=100.0, step=0.1, format="%.2f")
                else:
                    cagr_eps = cagr_opciones[cagr_seleccion]

                # Proyección de EPS para los próximos 5 años
                current_eps = eps_price_df["EPS Año Fiscal"].iloc[-1]
                current_fy = int(eps_price_df["fy"].iloc[-1])
                años_futuros = np.arange(1, 6)
                future_fys = [current_fy + i for i in años_futuros]
                projected_eps = current_eps * ((1 + cagr_eps / 100) ** años_futuros)

                # Calcular escenarios de PER
                per_pesimista = per_base * 0.8
                per_base_val = per_base
                per_optimista = per_base * 1.2

                # Calcular precio proyectado para cada escenario
                precio_pesimista = projected_eps * per_pesimista
                precio_base = projected_eps * per_base_val
                precio_optimista = projected_eps * per_optimista

                proyeccion_df = pd.DataFrame({
                    "Año Fiscal": future_fys,
                    "EPS Proyectado": projected_eps,
                    "Precio (Pesimista)": precio_pesimista,
                    "Precio (Base)": precio_base,
                    "Precio (Optimista)": precio_optimista
                })
                st.subheader("📊 Proyección de Precio en los Próximos 5 Años")
                st.table(proyeccion_df)

                # ==============================
                # Gráfico: Precio Histórico vs Proyección en 3 escenarios
                # ==============================
                # Extraer precios históricos de los últimos 10 años (si existen)
                if len(eps_price_df) >= 10:
                    historical_df = eps_price_df.tail(10)[["fy", "Precio"]].copy()
                    historical_df.rename(columns={"fy": "Año Fiscal", "Precio": "Precio Histórico"}, inplace=True)
                else:
                    historical_df = pd.DataFrame(columns=["Año Fiscal", "Precio Histórico"])

                fig2, ax = plt.subplots(figsize=(10, 5))
                if not historical_df.empty:
                    ax.plot(historical_df["Año Fiscal"], historical_df["Precio Histórico"], marker="o", color="blue",
                            label="Precio Histórico (últimos 10 años)")
                ax.plot(future_fys, precio_pesimista, marker="o", linestyle="dashed", color="red", label="Proyección (Pesimista)")
                ax.plot(future_fys, precio_base, marker="o", linestyle="dashed", color="green", label="Proyección (Base)")
                ax.plot(future_fys, precio_optimista, marker="o", linestyle="dashed", color="orange", label="Proyección (Optimista)")
                ax.set_xlabel("Año Fiscal")
                ax.set_ylabel("Precio")
                ax.legend()
                st.subheader("📈 Evolución: Precio Histórico vs Proyección")
                st.pyplot(fig2)
            else:
                st.info("✅ No se realizará la proyección de precio.")

        else:
            st.error("❌ Error al obtener datos de la SEC. Inténtalo más tarde.")
else:
    st.info("💡 Introduce un ticker para comenzar el análisis.")
