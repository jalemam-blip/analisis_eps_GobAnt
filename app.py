import streamlit as st
import requests
import pdfplumber
import re
import os
import pandas as pd
import logging
import pytesseract
from pdf2image import convert_from_path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import locale
from unidecode import unidecode

# ==================== CONFIGURACIÓN ====================
logging.getLogger("pdfminer").setLevel(logging.ERROR)
try:
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
except:
    locale.setlocale(locale.LC_TIME, 'C')

# Ruta de Tesseract en el entorno de hosting
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

st.set_page_config(page_title="Analizador de Alertas de Afiliación", layout="wide", page_icon="🚀")

st.title("🚀 Analizador de Alertas de Afiliación V6.5")
st.markdown("**Análisis automático de PDFs desde ArcGIS • Web y Móvil**")

base_url = "https://services5.arcgis.com/K90UQIB09TmTjUL8/arcgis/rest/services/survey123_2506405863a54fdd9e32f2028214f312_results/FeatureServer/0"

# ==================== FUNCIONES (sin cambios) ====================
def ia_interpretar_estado(text):
    texto_limpio = unidecode(text.lower())
    alertas_criticas = {
        'SUSPENDIDO': [r'suspendido', r'suspension', r'corte de servicio'],
        'RETIRADO': [r'retirado', r'desvinculado', r'egreso'],
        'INACTIVO': [r'inactivo', r'estado inactivo', r'no activo'],
        'SIN DERECHO A SERVICIO': [r'sin derecho', r'no tiene derecho', r'sin cobertura', r'no cuenta con cobertura', r'no vigente', r'expirado']
    }
    hallazgos = []
    for categoria, patrones in alertas_criticas.items():
        for patron in patrones:
            if re.search(patron, texto_limpio):
                hallazgos.append(categoria)
                break
    return ", ".join(list(set(hallazgos))) if hallazgos else None, bool(hallazgos)

def extract_content_smart(pdf_path):
    full_text = ""
    is_ocr = False
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:2]:
                extracted = page.extract_text()
                if extracted:
                    full_text += extracted + "\n"
        if len(full_text.strip()) < 60:
            is_ocr = True
            images = convert_from_path(pdf_path, first_page=1, last_page=2)
            for img in images:
                full_text += pytesseract.image_to_string(img, lang='spa')
    except:
        pass
    return full_text, is_ocr

def process_pdf(oid, report_dates):
    alert_results = []
    try:
        att_resp = requests.get(f"{base_url}/{oid}/attachments?f=json", timeout=10).json()
        for att in att_resp.get('attachmentInfos', []):
            if att['contentType'] == 'application/pdf':
                pdf_url = f"{base_url}/{oid}/attachments/{att['id']}"
                content = requests.get(pdf_url).content
                fname = f"temp_{oid}_{att['id']}.pdf"
                with open(fname, 'wb') as f:
                    f.write(content)
                text, used_ocr = extract_content_smart(fname)
                interpretacion, es_alerta = ia_interpretar_estado(text)
                if es_alerta:
                    mes_anio_registro = report_dates.get(oid, "Sin mes/año")
                    alert_results.append({
                        'ObjectID': oid,
                        'Mes_Registro': mes_anio_registro,
                        'Nombre_Archivo': att['name'],
                        'Hallazgo_IA': interpretacion,
                        'Metodo': "Visión OCR" if used_ocr else "Digital",
                        'URL_Documento': pdf_url,
                        'Fecha_Analisis': datetime.now().strftime('%d/%m/%Y %H:%M')
                    })
                if os.path.exists(fname):
                    os.remove(fname)
    except:
        pass
    return alert_results

# ==================== LÓGICA PRINCIPAL ====================
anios_disponibles = list(range(2023, 2031))
meses_disponibles = ["Todos", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

col1, col2 = st.columns([1, 1])
with col1:
    selected_year = st.selectbox("Año:", anios_disponibles, index=anios_disponibles.index(2026) if 2026 in anios_disponibles else 0)
with col2:
    selected_month = st.selectbox("Mes:", meses_disponibles, index=0)

if st.button("▶️ Ejecutar análisis", type="primary", use_container_width=True):
    with st.spinner("🔍 Consultando registros..."):
        # Construcción de la consulta
        if selected_month == "Todos":
            where_clause = f"a_o_de_reporte={selected_year}"
            mes_label = f"todo {selected_year}"
        else:
            where_clause = f"a_o_de_reporte={selected_year} AND mes_que_reporta='{selected_month.upper()}'"
            mes_label = f"{selected_month} {selected_year}"

        query_url = f"{base_url}/query?where={where_clause}&outFields=objectid,mes_que_reporta,a_o_de_reporte&returnGeometry=false&f=json&orderByFields=a_o_de_reporte ASC"
        response = requests.get(query_url).json()
        features = response.get('features', [])

        objectids = []
        report_dates = {}
        meses_es = {'ENERO': 'Enero', 'FEBRERO': 'Febrero', 'MARZO': 'Marzo', 'ABRIL': 'Abril', 'MAYO': 'Mayo',
                    'JUNIO': 'Junio', 'JULIO': 'Julio', 'AGOSTO': 'Agosto', 'SEPTIEMBRE': 'Septiembre',
                    'OCTUBRE': 'Octubre', 'NOVIEMBRE': 'Noviembre', 'DICIEMBRE': 'Diciembre'}

        for feature in features:
            attrs = feature.get('attributes', {})
            oid = attrs.get('objectid')
            if oid is not None:
                objectids.append(oid)
                mes_raw = attrs.get('mes_que_reporta')
                anio = attrs.get('a_o_de_reporte')
                if mes_raw and anio:
                    mes_norm = meses_es.get(str(mes_raw).upper(), str(mes_raw).capitalize())
                    report_dates[oid] = f"{mes_norm} {anio}"
                else:
                    report_dates[oid] = "Sin mes/año"

        objectids = sorted(set(objectids))
        total_docs = len(objectids)

        if total_docs == 0:
            st.warning(f"ℹ️ No se encontraron registros para {mes_label}.")
        else:
            st.info(f"Escaneando **{total_docs}** registros... (puede tardar varios minutos)")

            # Barra de progreso en vivo
            progress_bar = st.progress(0)
            status_text = st.empty()

            alert_data = []
            processed = 0

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(process_pdf, oid, report_dates) for oid in objectids]
                for future in as_completed(futures):
                    alert_data.extend(future.result())
                    processed += 1
                    progress_bar.progress(processed / total_docs)
                    status_text.text(f"📄 Documentos procesados: **{processed} / {total_docs}**")

            progress_bar.progress(1.0)
            status_text.success("✅ ¡Procesamiento completado!")

            # ==================== RESULTADOS ====================
            if alert_data:
                df = pd.DataFrame(alert_data)
                safe_month = selected_month.replace(" ", "_") if selected_month != "Todos" else "Todos"

                # Botón de descarga
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Descargar CSV completo",
                    data=csv,
                    file_name=f"solo_alertas_afiliacion_{selected_year}_{safe_month}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

                st.warning(f"⚠️ Se encontraron **{len(alert_data)}** documentos con alertas de afiliación.")

                # Tabla bonita (igual que en Colab)
                html_table = f"""
                <style>
                    .alertas-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-family: Arial, sans-serif; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
                    .alertas-table th {{ background-color: #dc3545; color: white; padding: 14px; text-align: left; }}
                    .alertas-table td {{ padding: 14px; border-bottom: 1px solid #ddd; }}
                    .alertas-table tr:nth-child(even) {{ background-color: #f8f9fa; }}
                    .alertas-table tr:hover {{ background-color: #e9ecef; }}
                    .btn-ver {{ background: #007bff; color: white; padding: 8px 16px; text-decoration: none; border-radius: 5px; }}
                </style>
                <div style="overflow-x: auto;">
                    <table class="alertas-table">
                        <thead><tr>
                            <th>ObjectID</th><th>Mes que reporta</th><th>Hallazgo IA</th><th>Origen</th><th>Acceso</th>
                        </tr></thead>
                        <tbody>
                """
                for _, r in df.iterrows():
                    html_table += f"""
                        <tr>
                            <td>{r['ObjectID']}</td>
                            <td>{r['Mes_Registro']}</td>
                            <td style="color:#dc3545; font-weight:bold;">⚠️ {r['Hallazgo_IA']}</td>
                            <td>{r['Metodo']}<br><small>{r['Nombre_Archivo']}</small></td>
                            <td><a href="{r['URL_Documento']}" target="_blank" class="btn-ver">Ver PDF</a></td>
                        </tr>
                    """
                html_table += "</tbody></table></div>"
                st.markdown(html_table, unsafe_allow_html=True)

                # Resumen
                if 'Mes_Registro' in df.columns:
                    conteo = df['Mes_Registro'].value_counts()
                    st.subheader("Resumen de alertas por mes")
                    st.bar_chart(conteo)
                    st.dataframe(conteo, use_container_width=True)
            else:
                st.success("✅ No se encontraron alertas en los registros analizados.")
