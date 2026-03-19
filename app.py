import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from supabase import create_client, Client
from datetime import datetime, timedelta
import calendar
from fpdf import FPDF
import tempfile
import os
import base64

# --- 1. CONFIGURACIÓN Y ESTILO CORPORATIVO ---
st.set_page_config(page_title="Coordinación FPS", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #F4F6F9; color: #31333F; }
    h1, h2, h3 { color: #003366 !important; font-weight: 700 !important; }
    .stButton>button { background-color: #FF6600; color: white; border-radius: 5px; border: none; font-weight: bold; height: 3em; width: 100%; transition: 0.3s; }
    .stButton>button:hover { background-color: #CC5200; color: white; }
    .stTabs [aria-selected="true"] { background-color: #003366 !important; color: white !important; }
    .especialista-pill { display: inline-block; background-color: #D5F5E3; color: #196F3D; padding: 5px 15px; border-radius: 20px; margin-right: 10px; margin-bottom: 10px; font-weight: 600; font-size: 0.9em; border: 1px solid #A9DFBF; }
    .login-container { max-width: 400px; margin: 50px auto; padding: 30px; background-color: white; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-top: 5px solid #E6007E; }
    </style>
""", unsafe_allow_html=True)

# --- CONEXIÓN A SUPABASE ---
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

try:
    supabase: Client = init_connection()
except Exception:
    st.error("Error crítico: No se pudo conectar a la base de datos Supabase. Verifique secrets.toml.")
    st.stop()

# --- INICIALIZACIÓN DE PROYECTOS INTERNOS ---
try:
    aus_nv = supabase.table("notas_venta").select("id_nv").eq("id_nv", "AUSENCIA").execute()
    if not aus_nv.data:
        supabase.table("notas_venta").insert({"id_nv": "AUSENCIA", "cliente": "Gestión Interna (RRHH)", "tipo_servicio": "SE TERRENO", "lugar": "Oficina/Casa", "moneda": "CLP", "monto_vendido": 0.0, "hh_vendidas": 0.0, "estado": "Abierta"}).execute()
    int_nv = supabase.table("notas_venta").select("id_nv").eq("id_nv", "INTERNO").execute()
    if not int_nv.data:
        supabase.table("notas_venta").insert({"id_nv": "INTERNO", "cliente": "Gestión Interna (Operaciones)", "tipo_servicio": "SE TERRENO", "lugar": "Oficina/Nave FPS", "moneda": "CLP", "monto_vendido": 0.0, "hh_vendidas": 0.0, "estado": "Abierta"}).execute()
except Exception:
    pass

def safe_insert_asignacion(payload):
    try:
        return supabase.table("asignaciones_personal").insert(payload).execute()
    except Exception as ex_db:
        err_str = str(ex_db)
        if "Could not find" in err_str or "dias_extras" in err_str or "hora_inicio_t" in err_str:
            payload_clean = payload.copy()
            for col in ["dias_extras", "justificacion", "hora_inicio_t", "hora_fin_t", "horas_diarias"]:
                payload_clean.pop(col, None)
            res = supabase.table("asignaciones_personal").insert(payload_clean).execute()
            st.toast("⚠️ BD desactualizada. Ejecute comandos SQL para activar todas las funciones.", icon="⚠️")
            return res
        else:
            raise ex_db

# --- CONSTANTES GLOBALES ---
ESPECIALISTAS = ["Felipe Romero", "David Colina", "Adelmo Calderon", "Jose Valenzuela", "Jose Peña", "German Contreras", "Esteban Romero", "Nicolas Salazar", "Javier Segovia", "Jonathan Aguilar", "Ignacio Castro", "Javier Rivera"]
ABREVIATURAS = {"Entrega materiales": "Mat", "Montaje de detección": "M.Det", "Montaje de supresión": "M.Sup", "Montaje de VESDA": "M.VESDA", "Cableado y conexionado": "Cabl", "Programación": "Prog", "PEM": "PEM", "Entrega de red line": "RedLine"}
FERIADOS_CHILE_2026 = ["01-01-2026", "03-04-2026", "04-04-2026", "01-05-2026", "21-05-2026", "29-06-2026", "16-07-2026", "15-08-2026", "18-09-2026", "19-09-2026", "12-10-2026", "31-10-2026", "01-11-2026", "08-12-2026", "25-12-2026"]
DIAS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MESES_ES = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}

def calcular_fecha_fin_dinamica(f_ini, dias_totales, incluye_finde):
    if dias_totales <= 0: return f_ini
    dias_contados, fecha_actual = 0, f_ini
    while dias_contados < dias_totales:
        es_feriado = fecha_actual.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
        es_finde = fecha_actual.weekday() >= 5
        if not incluye_finde:
            if not es_finde and not es_feriado: dias_contados += 1
        else:
            dias_contados += 1
        if dias_contados < dias_totales: fecha_actual += timedelta(days=1)
    return fecha_actual

def calcular_hh_ssee(f_ini, f_fin, incluye_finde=False, horas_diarias=None):
    hh = 0
    if f_fin < f_ini: return 0
    for i in range((f_fin - f_ini).days + 1):
        fecha_actual = f_ini + timedelta(days=i)
        dia_semana = fecha_actual.weekday()
        if not incluye_finde and (dia_semana >= 5 or fecha_actual.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026): continue 
        if horas_diarias is not None and horas_diarias > 0: hh += horas_diarias
        else: hh += 8.5 if dia_semana == 4 else 9.5 
    return hh

def obtener_nvs(estado_filter=None):
    query = supabase.table("notas_venta").select("*").neq("id_nv", "AUSENCIA").neq("id_nv", "INTERNO")
    if estado_filter: query = query.eq("estado", estado_filter)
    return query.execute().data

# --- CONTROL DE SESIÓN ---
if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'form_key_comercial' not in st.session_state: st.session_state.form_key_comercial = 0

def logout():
    try: supabase.auth.sign_out()
    except: pass
    st.session_state.authenticated = False
    st.session_state.user_email = ""

def login_screen():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.markdown("<div class='login-container'><h2 style='text-align: center; color: #E6007E;'>🔐 Acceso Coordinación FPS</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            email = st.text_input("Correo Electrónico")
            password = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Ingresar al Sistema", use_container_width=True):
                if email and password:
                    try:
                        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                        if response.session:
                            st.session_state.authenticated = True
                            st.session_state.user_email = email
                            st.rerun()
                    except Exception: st.error("Credenciales inválidas.")
                else: st.warning("Complete todos los campos.")
        st.markdown("</div>", unsafe_allow_html=True)

# --- APLICACIÓN PRINCIPAL ---
def main_app():
    st.sidebar.markdown("<div style='text-align: center; padding: 15px 0; background-color: white; border-radius: 8px; margin-bottom: 20px; border-left: 6px solid #E6007E;'><h2 style='margin: 0; color: #E6007E;'>COORDINACIÓN<br><span style='color: #00AEEF;'>FPS</span></h2></div>", unsafe_allow_html=True)
    st.sidebar.markdown(f"<p style='text-align:center;'>👤 <b>{st.session_state.user_email}</b></p>", unsafe_allow_html=True)
    st.sidebar.button("🚪 Cerrar Sesión", on_click=logout, use_container_width=True)
    st.sidebar.divider()
    tasa_cambio = st.sidebar.number_input("Valor del Dólar (CLP)", min_value=1.0, value=950.0, step=1.0)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📝 1. Comercial", "🗓️ 2. Matriz Semanal", "⚙️ 3. Ejecución y Gantt", "💰 4. Gastos y KPIs", "📄 5. Cierre"])

    # === MÓDULO 1: COMERCIAL ===
    with tab1:
        st.header("Gestión Comercial (Presupuesto)")
        col_form, col_admin = st.columns([2, 1])
        with col_form:
            if 'nv_pending' not in st.session_state: st.session_state.nv_pending = None
            if 'nv_conflicts' not in st.session_state: st.session_state.nv_conflicts = []

            if st.session_state.nv_pending is not None:
                st.warning("⚠️ **Cruces de Fechas Detectados**")
                for conf in st.session_state.nv_conflicts: st.write(f"- 👨‍🔧 **{conf['especialista']}** asignado a **{conf['id_nv']}** ({conf['fecha_inicio']} al {conf['fecha_fin']}).")
                decision = st.radio("¿Cómo proceder?", ["Mantener en ambos servicios", "Quitar de los servicios anteriores"])
                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    if st.button("✅ Confirmar y Guardar", use_container_width=True):
                        try:
                            payload = st.session_state.nv_pending
                            supabase.table("notas_venta").insert({"id_nv": payload["id_nv"], "cliente": payload["cliente"], "tipo_servicio": payload["tipo_servicio"], "lugar": payload["lugar"], "moneda": payload["moneda"], "monto_vendido": payload["monto_vendido"], "hh_vendidas": payload["hh_vendidas"], "estado": "Abierta"}).execute()
                            if "Quitar" in decision:
                                for conf in st.session_state.nv_conflicts: supabase.table("asignaciones_personal").delete().eq("id", conf['id']).execute()
                            for esp in payload["especialistas_sel"]:
                                safe_insert_asignacion({"id_nv": payload["id_nv"], "especialista": esp, "fecha_inicio": str(payload["f_ini"]), "fecha_fin": str(payload["f_f"]), "hh_asignadas": 0, "actividad_ssee": "PROYECCION_GLOBAL", "comentarios": "EXTRAS" if payload["es_continuo"] else "LIBRES", "progreso": 0, "hora_inicio_t": payload["h_inicio_val"], "hora_fin_t": payload["h_fin_val"], "horas_diarias": payload["h_diarias_val"]})
                            st.session_state.nv_pending, st.session_state.nv_conflicts = None, []
                            st.session_state.form_key_comercial += 1
                            st.success(f"✅ NV guardada."); st.rerun()
                        except Exception as e: st.error(f"Error: {e}")
                with c_btn2:
                    if st.button("❌ Cancelar", type="secondary", use_container_width=True): st.session_state.nv_pending, st.session_state.nv_conflicts = None, []; st.rerun()
            else:
                col_t1, col_t2 = st.columns([3, 1])
                with col_t1: st.subheader("Crear Nueva Nota de Venta")
                with col_t2:
                    if st.button("🔄 Nueva", use_container_width=True): st.session_state.form_key_comercial += 1; st.rerun()

                with st.form(key=f"form_comercial_{st.session_state.form_key_comercial}"):
                    c1, c2, c3 = st.columns(3)
                    id_nv_base = c1.text_input("ID Nota de Venta base")
                    item_nv = c1.text_input("Ítem / Fase (Opcional)")
                    cliente = c2.text_input("Cliente")
                    tipo = c2.selectbox("Tipo de Servicio", ["SSEE", "SE TERRENO"])
                    lugar = c3.text_input("Lugar / Faena")
                    col_mon, col_mnt = c3.columns([1, 2])
                    moneda = col_mon.selectbox("Moneda", ["CLP", "USD"])
                    if moneda == "CLP": monto_str = col_mnt.text_input("Monto Ofertado", value="")
                    else: monto_usd = col_mnt.number_input("Monto Ofertado", min_value=0.0, step=0.01)
                    
                    st.divider()
                    st.markdown("### Proyección Matriz Semanal")
                    if tipo == "SE TERRENO":
                        c_th1, c_th2, c_th3 = st.columns(3)
                        h_inicio_val = c_th1.time_input("Hora Inicio", value=datetime.strptime('08:00', '%H:%M').time())
                        h_fin_val = c_th2.time_input("Hora Fin", value=datetime.strptime('17:30', '%H:%M').time())
                        h_diarias_val = c_th3.number_input("Horas día", value=9.5, step=0.5)
                    else:
                        h_inicio_val, h_fin_val, h_diarias_val = None, None, None
                    
                    c4, c5, c6 = st.columns(3)
                    dias_v = c4.number_input("Días Vendidos", min_value=0.0, step=1.0)
                    f_ini = c5.date_input("Fecha de Inicio", format="DD/MM/YYYY", value=None)
                    especialistas_sel = c6.multiselect("Especialistas", ESPECIALISTAS)
                    incluye_finde = st.radio("¿Fines de semana?", ["No", "Sí (Días continuos)"], horizontal=True)

                    if st.form_submit_button("Guardar Nota de Venta", use_container_width=True):
                        id_nv = f"{id_nv_base.strip()} - {item_nv.strip()}" if item_nv.strip() else id_nv_base.strip()
                        monto = float(str(monto_str).replace(".", "").replace(",", "").strip()) if moneda == "CLP" and str(monto_str).replace(".", "").isdigit() else (monto_usd if moneda == "USD" else 0.0)
                        
                        if id_nv and cliente:
                            verificacion = supabase.table("notas_venta").select("id_nv").eq("id_nv", id_nv).execute()
                            if len(verificacion.data) > 0: st.warning("⚠️ ID ya existe.")
                            else:
                                if especialistas_sel and dias_v > 0 and f_ini is not None:
                                    es_continuo = incluye_finde == "Sí (Días continuos)"
                                    f_f = calcular_fecha_fin_dinamica(f_ini, dias_v, es_continuo)
                                    conflictos = [a for a in supabase.table("asignaciones_personal").select("*").in_("especialista", especialistas_sel).execute().data if f_ini <= pd.to_datetime(a['fecha_fin']).date() and f_f >= pd.to_datetime(a['fecha_inicio']).date()]
                                    if conflictos:
                                        st.session_state.nv_pending = {"id_nv": id_nv, "cliente": cliente, "tipo_servicio": tipo, "lugar": lugar, "moneda": moneda, "monto_vendido": monto, "hh_vendidas": dias_v, "estado": "Abierta", "especialistas_sel": especialistas_sel, "f_ini": f_ini, "f_f": f_f, "es_continuo": es_continuo, "h_inicio_val": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00', "h_fin_val": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30', "h_diarias_val": h_diarias_val}
                                        st.session_state.nv_conflicts = conflictos
                                        st.rerun()
                                    else:
                                        supabase.table("notas_venta").insert({"id_nv": id_nv, "cliente": cliente, "tipo_servicio": tipo, "lugar": lugar, "moneda": moneda, "monto_vendido": monto, "hh_vendidas": dias_v, "estado": "Abierta"}).execute()
                                        for esp in especialistas_sel: safe_insert_asignacion({"id_nv": id_nv, "especialista": esp, "fecha_inicio": str(f_ini), "fecha_fin": str(f_f), "hh_asignadas": 0, "actividad_ssee": "PROYECCION_GLOBAL", "comentarios": "EXTRAS" if es_continuo else "LIBRES", "progreso": 0, "hora_inicio_t": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00', "hora_fin_t": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30', "horas_diarias": h_diarias_val if h_diarias_val else 0})
                                        st.success("✅ Guardado."); st.session_state.form_key_comercial += 1; st.rerun()
                                else:
                                    supabase.table("notas_venta").insert({"id_nv": id_nv, "cliente": cliente, "tipo_servicio": tipo, "lugar": lugar, "moneda": moneda, "monto_vendido": monto, "hh_vendidas": dias_v, "estado": "Abierta"}).execute()
                                    st.success("✅ Guardado."); st.session_state.form_key_comercial += 1; st.rerun()
                        else: st.warning("⚠️ Ingrese ID y Cliente.")
        
        with col_admin:
            st.subheader("Administración y Edición")
            nvs_admin = obtener_nvs()
            if nvs_admin:
                opciones_admin = {f"{n['id_nv']} - {n['cliente']}": n for n in nvs_admin}
                tab_edit, tab_del = st.tabs(["✏️ Editar", "🗑️ Eliminar"])
                with tab_edit:
                    nv_a_editar_label = st.selectbox("Editar Proyecto", list(opciones_admin.keys()))
                    nv_data = opciones_admin[nv_a_editar_label]
                    with st.form("form_edit_nv"):
                        st.text_input("ID (No editable)", value=nv_data['id_nv'], disabled=True)
                        new_cliente = st.text_input("Cliente", value=nv_data['cliente'])
                        new_tipo = st.selectbox("Tipo", ["SSEE", "SE TERRENO"], index=0 if nv_data['tipo_servicio'] == 'SSEE' else 1)
                        new_lugar = st.text_input("Lugar", value=nv_data.get('lugar', ''))
                        c_mon_e, c_mnt_e = st.columns([1, 2])
                        new_moneda = c_mon_e.selectbox("Moneda", ["CLP", "USD"], index=0 if nv_data.get('moneda', 'CLP') == 'CLP' else 1)
                        if new_moneda == "CLP": new_monto_str = c_mnt_e.text_input("Monto", value=f"{int(nv_data.get('monto_vendido', 0))}")
                        else: new_monto_usd = c_mnt_e.number_input("Monto", min_value=0.0, value=float(nv_data.get('monto_vendido', 0.0)))
                        if st.form_submit_button("Actualizar"):
                            final_monto = float(str(new_monto_str).replace(".", "").strip()) if new_moneda == "CLP" and str(new_monto_str).replace(".", "").isdigit() else (new_monto_usd if new_moneda == "USD" else 0.0)
                            supabase.table("notas_venta").update({"cliente": new_cliente, "tipo_servicio": new_tipo, "lugar": new_lugar, "moneda": new_moneda, "monto_vendido": final_monto}).eq("id_nv", nv_data['id_nv']).execute()
                            st.success("✅ Actualizado"); st.rerun()
                with tab_del:
                    nv_a_borrar_label = st.selectbox("Eliminar Proyecto", list(opciones_admin.keys()))
                    id_a_borrar = opciones_admin[nv_a_borrar_label]['id_nv']
                    if st.checkbox("Confirmar eliminación"):
                        if st.button("🗑️ Eliminar"):
                            supabase.table("notas_venta").delete().eq("id_nv", id_a_borrar).execute()
                            st.success("✅ Eliminado."); st.rerun()

    # === MÓDULO 2: MATRIZ ===
    with tab2:
        st.header("Matriz de Recursos (Proyección Global)")
        nvs_activas_comercial = [n for n in obtener_nvs("Abierta") if n['id_nv'] != "INTERNO"]
        dict_nvs_label = {f"{n['id_nv']} - {n['cliente']}": n for n in nvs_activas_comercial} if nvs_activas_comercial else {}
        
        st.markdown("### ⚙️ Panel de Asignación y Disponibilidad")
        col_exp1, col_exp2, col_exp3 = st.columns(3)
        
        with col_exp1:
            with st.expander("💼 Proyección Comercial", expanded=False):
                tab_proy1, tab_proy2 = st.tabs(["Asignar Proyección", "Eliminar Proyección"])
                with tab_proy1:
                    with st.form("form_proyeccion"):
                        if dict_nvs_label:
                            nv_label_sel = st.selectbox("Proyecto", list(dict_nvs_label.keys()))
                            nv_data_sel = dict_nvs_label[nv_label_sel]
                            especialistas_sel = st.multiselect("Especialistas", ESPECIALISTAS)
                            if nv_data_sel.get('tipo_servicio') == 'SE TERRENO':
                                c_t1, c_t2, c_t3 = st.columns(3)
                                h_inicio_val = c_t1.time_input("Inicio", value=datetime.strptime('08:00', '%H:%M').time())
                                h_fin_val = c_t2.time_input("Fin", value=datetime.strptime('17:30', '%H:%M').time())
                                h_diarias_val = c_t3.number_input("Horas día", value=9.5, step=0.5)
                            else:
                                h_inicio_val, h_fin_val, h_diarias_val = None, None, None
                            
                            c_f1, c_f2 = st.columns(2)
                            f_ini = c_f1.date_input("Fecha Inicio", format="DD/MM/YYYY")
                            dias_proy = c_f2.number_input("Días totales", min_value=1.0, value=float(nv_data_sel.get('hh_vendidas', 5.0)))
                            incluye_finde = st.radio("¿Fines de semana?", ["No", "Sí"], horizontal=True)
                            
                            if st.form_submit_button("Guardar Proyección", use_container_width=True):
                                supabase.table("asignaciones_personal").delete().eq("id_nv", nv_data_sel['id_nv']).eq("actividad_ssee", "PROYECCION_GLOBAL").execute()
                                f_f = calcular_fecha_fin_dinamica(f_ini, dias_proy, incluye_finde == "Sí")
                                for esp in especialistas_sel: safe_insert_asignacion({"id_nv": nv_data_sel['id_nv'], "especialista": esp, "fecha_inicio": str(f_ini), "fecha_fin": str(f_f), "hh_asignadas": 0, "actividad_ssee": "PROYECCION_GLOBAL", "comentarios": "EXTRAS" if incluye_finde == "Sí" else "LIBRES", "progreso": 0, "hora_inicio_t": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00', "hora_fin_t": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30', "horas_diarias": h_diarias_val if h_diarias_val else 0})
                                st.success("✅ Actualizado"); st.rerun()
                with tab_proy2:
                    proy_raw = supabase.table("asignaciones_personal").select("*").eq("actividad_ssee", "PROYECCION_GLOBAL").execute().data
                    if proy_raw:
                        df_proy = pd.DataFrame(proy_raw)
                        op_proy = {f"{r['especialista']} | {r['id_nv']} | {r['fecha_inicio']} a {r['fecha_fin']}": r['id'] for _, r in df_proy.iterrows()}
                        sel_proy = st.selectbox("Eliminar proyección", list(op_proy.keys()))
                        if st.button("🗑️ Eliminar Proyección"):
                            supabase.table("asignaciones_personal").delete().eq("id", op_proy[sel_proy]).execute()
                            st.success("✅ Eliminada"); st.rerun()
                    else: st.write("No hay proyecciones.")

        with col_exp2:
            with st.expander("🏢 Labores Internas", expanded=False):
                tab_int1, tab_int2 = st.tabs(["Asignar Labor", "Gestionar Activas"])
                with tab_int1:
                    with st.form("form_internas"):
                        esp_int = st.multiselect("Especialista(s)", ESPECIALISTAS)
                        tipo_int = st.selectbox("Labor", ["Informe de Visita Técnica", "Trabajos en Nave FPS (Taller)", "Carga de Cilindros", "Cursos y Capacitación", "Trabajo Administrativo", "Otro"])
                        desc_int = st.text_input("Detalle")
                        c_d1, c_d2 = st.columns(2)
                        f_ini_int, f_fin_int = c_d1.date_input("Inicio", format="DD/MM/YYYY"), c_d2.date_input("Fin", format="DD/MM/YYYY")
                        if st.form_submit_button("Guardar Labor", use_container_width=True) and esp_int and f_ini_int <= f_fin_int:
                            hh_final = calcular_hh_ssee(f_ini_int, f_fin_int, False)
                            for esp in esp_int: safe_insert_asignacion({"id_nv": "INTERNO", "especialista": esp, "fecha_inicio": str(f_ini_int), "fecha_fin": str(f_fin_int), "hh_asignadas": hh_final, "actividad_ssee": f"{tipo_int} - {desc_int}" if desc_int else tipo_int, "comentarios": "LIBRES", "progreso": 100, "hora_inicio_t": "08:00", "hora_fin_t": "17:30", "horas_diarias": 9.5})
                            st.success("✅ Labor registrada"); st.rerun()
                with tab_int2:
                    int_raw = supabase.table("asignaciones_personal").select("*").eq("id_nv", "INTERNO").execute().data
                    if int_raw:
                        df_int = pd.DataFrame(int_raw)
                        op_int = {f"{r['especialista']} | {r['actividad_ssee']} | {r['fecha_inicio']}": r['id'] for _, r in df_int.iterrows()}
                        sel_int = st.selectbox("Eliminar labor", list(op_int.keys()))
                        if st.button("🗑️ Eliminar Labor Interna"):
                            supabase.table("asignaciones_personal").delete().eq("id", op_int[sel_int]).execute()
                            st.success("✅ Eliminada"); st.rerun()
                    else: st.write("No hay labores internas.")

        with col_exp3:
            with st.expander("🌴 Ausencias", expanded=False):
                tab_aus1, tab_aus2 = st.tabs(["Ingresar", "Cancelar"])
                with tab_aus1:
                    with st.form("form_ausencia"):
                        esp_aus = st.multiselect("Especialista(s)", ESPECIALISTAS)
                        tipo_aus = st.selectbox("Tipo", ["Vacaciones", "Permiso Administrativo", "Licencia Médica", "Falta Injustificada"])
                        c_a1, c_a2 = st.columns(2)
                        f_ini_aus, f_fin_aus = c_a1.date_input("Inicio", format="DD/MM/YYYY"), c_a2.date_input("Fin", format="DD/MM/YYYY")
                        desc_aus = st.text_input("Motivo")
                        if st.form_submit_button("Registrar Ausencia", use_container_width=True) and esp_aus and f_ini_aus <= f_fin_aus:
                            hh_final = calcular_hh_ssee(f_ini_aus, f_fin_aus, False)
                            for esp in esp_aus: safe_insert_asignacion({"id_nv": "AUSENCIA", "especialista": esp, "fecha_inicio": str(f_ini_aus), "fecha_fin": str(f_fin_aus), "hh_asignadas": hh_final, "actividad_ssee": f"{tipo_aus} - {desc_aus}" if desc_aus else tipo_aus, "comentarios": "LIBRES", "progreso": 100})
                            st.success("✅ Ausencia registrada"); st.rerun()
                with tab_aus2:
                    aus_raw = supabase.table("asignaciones_personal").select("*").eq("id_nv", "AUSENCIA").execute().data
                    if aus_raw:
                        df_aus = pd.DataFrame(aus_raw)
                        op_aus = {f"{r['especialista']} | {r['actividad_ssee']} | {r['fecha_inicio']}": r['id'] for _, r in df_aus.iterrows()}
                        sel_aus = st.selectbox("Eliminar ausencia", list(op_aus.keys()))
                        if st.button("🗑️ Cancelar Ausencia"):
                            supabase.table("asignaciones_personal").delete().eq("id", op_aus[sel_aus]).execute()
                            st.success("✅ Cancelada"); st.rerun()

        st.divider()
        col_start, col_days = st.columns(2)
        f_base = col_start.date_input("📅 Fecha de inicio de matriz", value=datetime.today().date())
        dias_a_mostrar = col_days.slider("Días adelante", 1, 60, 14) 
        
        fechas_rango = [f_base + timedelta(days=i) for i in range(dias_a_mostrar)]
        cols_int = [d.strftime("%d-%m-%Y") for d in fechas_rango]
        cols_disp = [f"{DIAS_ES[d.weekday()]} {d.strftime('%d/%m')}" for d in fechas_rango]
        matriz_final = pd.DataFrame(index=ESPECIALISTAS, columns=cols_int)
        for col in cols_int:
            f_obj = datetime.strptime(col, "%d-%m-%Y").date()
            matriz_final[col] = "⌛ No Hábil" if (f_obj.weekday() >= 5 or col in FERIADOS_CHILE_2026) else "🟢 Disponible"
            
        asig_raw = supabase.table("asignaciones_personal").select("*").execute().data
        mapa_clientes = {n['id_nv']: n['cliente'] for n in obtener_nvs()} if obtener_nvs() else {}

        if asig_raw:
            for a in asig_raw:
                try: f_i, f_f = pd.to_datetime(a['fecha_inicio']).date(), pd.to_datetime(a['fecha_fin']).date()
                except: continue
                
                if a['id_nv'] == 'AUSENCIA':
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        if d in fechas_rango: matriz_final.at[a['especialista'], d.strftime("%d-%m-%Y")] = f"🌴 {a['actividad_ssee']}"
                elif a['id_nv'] == 'INTERNO':
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        if d.weekday() < 5 and d.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026 and d in fechas_rango:
                            col = d.strftime("%d-%m-%Y")
                            val = str(matriz_final.at[a['especialista'], col])
                            if '🌴' not in val: matriz_final.at[a['especialista'], col] = f"🏢 {a['actividad_ssee']}" if val in ["🟢 Disponible", "⌛ No Hábil"] else val + f" + 🏢 {a['actividad_ssee']}"
                elif a.get('actividad_ssee') == 'PROYECCION_GLOBAL':
                    es_cont = a.get('comentarios') == 'EXTRAS'
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        if not es_cont and (d.weekday() >= 5 or d.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026): continue
                        if d in fechas_rango:
                            col = d.strftime("%d-%m-%Y")
                            val = str(matriz_final.at[a['especialista'], col])
                            if '🌴' not in val:
                                e = f"{a['id_nv']} [{mapa_clientes.get(a['id_nv'], 'N/A')}]"
                                matriz_final.at[a['especialista'], col] = e if val in ["🟢 Disponible", "⌛ No Hábil"] else val + f" + {e}"
        
        matriz_final.columns = cols_disp
        def style_m(x):
            if 'No Hábil' in str(x): return 'background-color: #F0F0F0; color: #A0A0A0'
            if '🌴' in str(x): return 'background-color: #FADBD8; color: #C0392B; font-weight: bold'
            if '🏢' in str(x): return 'background-color: #D6EAF8; color: #21618C; font-weight: bold'
            if 'Disponible' in str(x): return 'background-color: #E6F2FF; color: #003366'
            return 'background-color: #D5F5E3; color: #196F3D; font-weight: bold'
        st.dataframe(matriz_final.style.map(style_m), use_container_width=True, height=550)

    # === MÓDULO 3: GANTT ===
    with tab3:
        st.header("Ejecución: Alcance, Programación Viva y Gantt")
        nvs_activas = obtener_nvs("Abierta")
        if nvs_activas:
            dict_nvs_label = {f"{n['id_nv']} - {n['cliente']}": n for n in nvs_activas}
            c_asig, c_prog = st.columns([1, 1.5])
            with c_asig:
                st.subheader("1. Alcance del Proyecto")
                nv_label_sel = st.selectbox("Proyecto", list(dict_nvs_label.keys()))
                nv_id_sel = dict_nvs_label[nv_label_sel]['id_nv']
                tab_alc_add, tab_alc_del = st.tabs(["➕ Añadir Labor", "🗑️ Eliminar Labor"])
                
                with tab_alc_add:
                    with st.form("form_alcance"):
                        if dict_nvs_label[nv_label_sel]['tipo_servicio'] == "SSEE": act_sel = st.multiselect("Agregar", list(ABREVIATURAS.keys()))
                        else: act_sel = [x for x in [st.text_input("Nombre de Actividad")] if x]
                        if st.form_submit_button("Añadir al Alcance") and act_sel:
                            exist = [e['actividad_ssee'] for e in supabase.table("asignaciones_personal").select("actividad_ssee").eq("id_nv", nv_id_sel).execute().data]
                            for act in act_sel:
                                if act not in exist: safe_insert_asignacion({"id_nv": nv_id_sel, "especialista": "Sin Asignar", "fecha_inicio": str(datetime.today().date()), "fecha_fin": str(datetime.today().date()), "hh_asignadas": 0, "actividad_ssee": act, "comentarios": "SIN_PROGRAMAR", "progreso": 0, "hora_inicio_t": '08:00', "hora_fin_t": '17:30', "horas_diarias": 0})
                            st.success("✅ Actividades añadidas."); st.rerun()
                
                with tab_alc_del:
                    exist_del = supabase.table("asignaciones_personal").select("actividad_ssee").eq("id_nv", nv_id_sel).neq("actividad_ssee", "PROYECCION_GLOBAL").execute().data
                    if exist_del:
                        with st.form("form_del_alcance"):
                            act_del = st.selectbox("Labor a Eliminar", list(set([e['actividad_ssee'] for e in exist_del])))
                            if st.form_submit_button("🗑️ Eliminar"):
                                supabase.table("asignaciones_personal").delete().eq("id_nv", nv_id_sel).eq("actividad_ssee", act_del).execute()
                                st.success("✅ Eliminada."); st.rerun()

            with c_prog:
                st.subheader("2. Programación Viva y Avances")
                asig_all_raw = supabase.table("asignaciones_personal").select("*").eq("id_nv", nv_id_sel).execute().data
                esps_matriz = list(set([x['especialista'] for x in asig_all_raw if x.get('actividad_ssee') == 'PROYECCION_GLOBAL' and x.get('especialista') != 'Sin Asignar'])) if asig_all_raw else []
                df_temp = pd.DataFrame(asig_all_raw) if asig_all_raw else pd.DataFrame()
                if not df_temp.empty: df_temp = df_temp[df_temp['actividad_ssee'] != 'PROYECCION_GLOBAL']
                
                if not df_temp.empty:
                    acts_uni = df_temp['actividad_ssee'].unique()
                    av_tot = df_temp.groupby('actividad_ssee')['progreso'].max().sum() / len(ABREVIATURAS) if dict_nvs_label[nv_label_sel]['tipo_servicio'] == "SSEE" else df_temp.groupby('actividad_ssee')['progreso'].max().mean()
                    st.progress(int(av_tot)); st.markdown("---")
                    
                    for act in acts_uni:
                        df_act = df_temp[df_temp['actividad_ssee'] == act].copy()
                        df_act['f_dt'] = pd.to_datetime(df_act['fecha_inicio'])
                        df_last = df_act[df_act['f_dt'] == df_act['f_dt'].max()]
                        c_prog = int(df_last['progreso'].max())
                        just_str = str(df_last['justificacion'].dropna().iloc[0]) if not df_last['justificacion'].dropna().empty else ""
                        is_paused = "[PAUSADA]" in just_str.upper()
                        
                        estado = "⚪ Sin Fecha" if df_last['comentarios'].iloc[0] == "SIN_PROGRAMAR" else ("⏸️ PAUSADA" if is_paused else ("⚠️ ATRASADA" if pd.to_datetime(df_last['fecha_fin'].max()).date() < datetime.today().date() and c_prog < 100 else "🟢 Programado"))
                        
                        with st.expander(f"{estado} | 📌 {act} - {c_prog}%"):
                            with st.form(key=f"f_{nv_id_sel}_{act}"):
                                accion = st.radio("Acción:", ["▶️ Reanudar Actividad", "Actualizar Avance"] if is_paused else ["Actualizar Avance / Fechas", "⏸️ Pausar Actividad"], horizontal=True)
                                c_p, c_f = st.columns([1, 1.5])
                                n_p = c_p.slider("Avance %", 0, 100, c_prog)
                                
                                c_d, c_e = st.columns(2)
                                if "Pausar" in accion:
                                    f_ini, f_pausa = df_last['f_dt'].max().date(), c_f.date_input("Fecha pausa", value=datetime.today().date())
                                    d_trab = max(1, (f_pausa - f_ini).days + 1)
                                    just = st.text_input("Motivo (Requerido)", value=just_str.replace("[PAUSADA]", "").strip())
                                elif "Reanudar" in accion:
                                    f_ini = c_f.date_input("Nueva Fecha Inicio", value=datetime.today().date())
                                    d_trab = c_d.number_input("Días restantes", min_value=1, value=1)
                                    just = st.text_input("Comentario")
                                else:
                                    f_ini = c_f.date_input("Inicio", value=df_last['f_dt'].max().date())
                                    d_trab = c_d.number_input("Días", min_value=1, value=max(1, (pd.to_datetime(df_last['fecha_fin'].max()).date() - f_ini).days + 1))
                                    just = st.text_input("Justificación", value=just_str)
                                
                                d_extra = c_d.number_input("Días Extra", min_value=0, value=int(df_last['dias_extras'].max()) if 'dias_extras' in df_last else 0)
                                ext = c_d.radio("Fines semana", ["Libres", "Extras"], index=1 if 'EXTRAS' in df_last['comentarios'].values else 0)
                                
                                if dict_nvs_label[nv_label_sel]['tipo_servicio'] == 'SE TERRENO':
                                    ct1, ct2, ct3 = st.columns(3)
                                    hi = ct1.time_input("Hora Ini", value=datetime.strptime(df_last['hora_inicio_t'].iloc[0] if 'hora_inicio_t' in df_last and pd.notna(df_last['hora_inicio_t'].iloc[0]) else '08:00', '%H:%M').time())
                                    hf = ct2.time_input("Hora Fin", value=datetime.strptime(df_last['hora_fin_t'].iloc[0] if 'hora_fin_t' in df_last and pd.notna(df_last['hora_fin_t'].iloc[0]) else '17:30', '%H:%M').time())
                                    hd = ct3.number_input("HH día", value=float(df_last['horas_diarias'].iloc[0]) if 'horas_diarias' in df_last and pd.notna(df_last['horas_diarias'].iloc[0]) and float(df_last['horas_diarias'].iloc[0])>0 else 9.5)
                                else: hi, hf, hd = None, None, None
                                
                                esps = c_e.multiselect("Técnicos", ESPECIALISTAS, default=[e for e in df_last['especialista'].unique() if e in ESPECIALISTAS] or esps_matriz)
                                mod = c_e.radio("Modalidad", ["Simultáneo", "Contra Turno"])
                                
                                if st.form_submit_button("Guardar"):
                                    try:
                                        if "Reanudar" in accion:
                                            for rid in df_last['id'].tolist(): supabase.table("asignaciones_personal").update({"justificacion": str(df_last[df_last['id']==rid]['justificacion'].iloc[0]).replace("[PAUSADA]", "").strip() + " (Fin)"}).eq("id", rid).execute()
                                        else:
                                            for rid in df_last['id'].tolist(): supabase.table("asignaciones_personal").delete().eq("id", rid).execute()
                                        
                                        supabase.table("asignaciones_personal").update({"progreso": n_p}).eq("id_nv", nv_id_sel).eq("actividad_ssee", act).execute()
                                        
                                        f_f = calcular_fecha_fin_dinamica(f_ini, d_trab, "Extras" in ext)
                                        hh = calcular_hh_ssee(f_ini, f_f, "Extras" in ext, hd) / (len(esps) if "Contra Turno" in mod and len(esps)>1 else 1)
                                        final_j = f"[PAUSADA] {just}" if "Pausar" in accion else just
                                        
                                        for e in (esps if esps else ["Sin Asignar"]):
                                            safe_insert_asignacion({"id_nv": nv_id_sel, "especialista": e, "fecha_inicio": str(f_ini), "fecha_fin": str(f_f), "hh_asignadas": hh if e != "Sin Asignar" else 0, "actividad_ssee": act, "comentarios": "EXTRAS" if "Extras" in ext else "LIBRES", "progreso": n_p, "dias_extras": d_extra, "justificacion": final_j, "hora_inicio_t": hi.strftime('%H:%M') if hi else '08:00', "hora_fin_t": hf.strftime('%H:%M') if hf else '17:30', "horas_diarias": hd if hd else 0})
                                        st.success("✅ Guardado."); st.rerun()
                                    except Exception as e: st.error(f"Error: {e}")
                
        st.divider()
        st.subheader("3. Cronograma Operativo (Gantt)")
        cv1, cv2, cv3, cv4 = st.columns([1,1,1,1])
        v_gantt = cv1.radio("Vista:", ["Global", "Por Proyecto"])
        f_tipo = cv2.radio("Filtro Tipo:", ["Todos", "SSEE", "SE TERRENO"])
        f_tiemp = cv3.radio("Ventana:", ["Todo", "15 Días", "1 Mes"], index=1)
        d_ini_g = cv4.date_input("Inicio", value=datetime.today().date())

        g_raw = supabase.table("asignaciones_personal").select("*").execute().data
        if g_raw:
            df_g = pd.DataFrame(g_raw)
            df_g = df_g[(df_g['actividad_ssee'] != 'PROYECCION_GLOBAL') & (~df_g['id_nv'].isin(['INTERNO', 'AUSENCIA']))]
            n_t = {n['id_nv']: n['tipo_servicio'] for n in obtener_nvs()} if obtener_nvs() else {}
            n_c = {n['id_nv']: n['cliente'] for n in obtener_nvs()} if obtener_nvs() else {}
            
            if v_gantt == "Por Proyecto": df_g = df_g[df_g['id_nv'] == nv_id_sel]
            elif f_tipo != "Todos": df_g = df_g[df_g['id_nv'].map(n_t) == f_tipo]
            
            if not df_g.empty:
                df_g['start_ts'] = pd.to_datetime(df_g['fecha_inicio'].astype(str) + ' ' + df_g['hora_inicio_t'].fillna('08:00'))
                df_g['end_ts'] = pd.to_datetime(df_g['fecha_fin'].astype(str) + ' ' + df_g['hora_fin_t'].fillna('17:30'))
                df_g = df_g[df_g['comentarios'] != 'SIN_PROGRAMAR']
                
                df_grp = df_g.groupby(['id_nv', 'actividad_ssee', 'start_ts', 'end_ts', 'progreso', 'justificacion']).agg({'especialista': lambda x: ", ".join(set(x))}).reset_index()
                df_grp['Eje_Y'] = df_grp['id_nv'] + " | " + df_grp['actividad_ssee']
                
                rows = []
                for _, r in df_grp.iterrows():
                    bl = f"{r['id_nv'].split(' - ')[0]} ({r['progreso']}%)"
                    r['Etiqueta_Barra'] = f"<b>⏸️ {bl}</b>" if "[PAUSADA]" in str(r['justificacion']).upper() else f"<b>{bl}</b>"
                    rows.append(r)
                
                df_p = pd.DataFrame(rows)
                t_i = pd.to_datetime(d_ini_g)
                t_f = t_i + pd.Timedelta(days=15 if f_tiemp == "15 Días" else (30 if f_tiemp == "1 Mes" else 180))
                if f_tiemp != "Todo": df_p = df_p[(df_p['end_ts'] >= t_i) & (df_p['start_ts'] <= t_f)]
                
                if not df_p.empty:
                    fig = px.timeline(df_p, x_start="start_ts", x_end="end_ts", y="Eje_Y", color="actividad_ssee", text="Etiqueta_Barra", color_discrete_sequence=px.colors.qualitative.Set1)
                    fig.update_traces(textposition='auto', insidetextanchor='middle', textfont=dict(size=14, color='black'), marker_line_width=0, opacity=0.95)
                    fig.update_yaxes(autorange="reversed", title="", tickfont=dict(size=14))
                    fig.update_xaxes(range=[t_i.strftime("%Y-%m-%d 00:00:00"), t_f.strftime("%Y-%m-%d 23:59:59")], dtick=86400000, tickformat="%d/%m", title="")
                    fig.update_layout(height=max(250, len(df_p['Eje_Y'].unique())*80), plot_bgcolor='white', legend=dict(orientation="h", y=1.05))
                    st.plotly_chart(fig, use_container_width=True)

    # === MÓDULO 4: KPIS ===
    with tab4:
        st.header("Análisis de Datos y Control Financiero")
        nvs_all = obtener_nvs()
        if not nvs_all: st.warning("No hay proyectos.")
        else:
            h_raw = supabase.table("hitos_facturacion").select("*").execute().data
            df_h = pd.DataFrame(h_raw) if h_raw else pd.DataFrame(columns=["id", "id_nv", "mes", "anio", "porcentaje", "monto", "estado"])
            
            with st.expander("➕ REGISTRAR GASTO (CLP)"):
                with st.form("f_g"):
                    cg1, cg2, cg3, cg4 = st.columns(4)
                    nv_g = cg1.selectbox("Proyecto", [n['id_nv'] for n in obtener_nvs("Abierta")])
                    t_g = cg2.selectbox("Ítem", ["Rendigastos", "Viático", "Hospedaje", "Pasajes", "Insumos"])
                    m_g = cg3.number_input("Monto (CLP)", min_value=0)
                    f_g = cg4.date_input("Fecha")
                    if st.form_submit_button("Guardar"): supabase.table("control_gastos").insert({"id_nv": nv_g, "tipo_gasto": t_g, "monto_gasto": m_g, "fecha_gasto": str(f_g)}).execute(); st.rerun()

            df_nv = pd.DataFrame(nvs_all)
            g_raw = supabase.table("control_gastos").select("*").execute().data
            df_g_agg = pd.DataFrame(g_raw).groupby('id_nv')['monto_gasto'].sum().reset_index() if g_raw else pd.DataFrame(columns=['id_nv', 'monto_gasto'])
            
            asig_all_raw = supabase.table("asignaciones_personal").select("*").execute().data
            df_hh_raw = pd.DataFrame([a for a in asig_all_raw if a['id_nv'] not in ['AUSENCIA', 'INTERNO'] and a['comentarios'] != 'SIN_PROGRAMAR']) if asig_all_raw else pd.DataFrame()
            
            if not df_hh_raw.empty:
                df_hh_raw['hd'] = pd.to_numeric(df_hh_raw['horas_diarias'], errors='coerce').fillna(9.0)
                df_hh_raw.loc[df_hh_raw['hd'] <= 0, 'hd'] = 9.0
                df_hh_raw['d_eje'] = pd.to_numeric(df_hh_raw['hh_asignadas'], errors='coerce').fillna(0) / df_hh_raw['hd']
                df_hh_agg = df_hh_raw.groupby('id_nv')['d_eje'].sum().reset_index()
                
                df_p = df_hh_raw.groupby(['id_nv', 'actividad_ssee'])['progreso'].max().reset_index().groupby('id_nv')['progreso'].mean().reset_index()
                df_hh_agg = df_hh_agg.merge(df_p, on='id_nv', how='left').rename(columns={'progreso': 'Avance_%'})
            else: df_hh_agg = pd.DataFrame(columns=['id_nv', 'd_eje', 'Avance_%'])
            
            df_k = df_nv.merge(df_g_agg, on='id_nv', how='left').merge(df_hh_agg, on='id_nv', how='left').fillna(0)
            df_k['Proyecto_Label'] = df_k['id_nv'] + " (" + df_k['cliente'] + ")"
            df_k['monto_facturado_hitos'] = df_k['id_nv'].map(df_h[df_h['estado']=='Facturada'].groupby('id_nv')['monto'].sum()).fillna(0)
            df_k['monto_pendiente'] = df_k.apply(lambda r: max(0, r['monto_vendido'] - r['monto_facturado_hitos']) if r['estado'] != 'Cerrada' else 0, axis=1)
            df_k['monto_gasto_ajustado'] = df_k.apply(lambda r: r['monto_gasto']/tasa_cambio if r['moneda']=='USD' else r['monto_gasto'], axis=1)
            df_k['Margen'] = df_k['monto_vendido'] - df_k['monto_gasto_ajustado']

            # Global Variables for Tabs
            df_all_valid = pd.DataFrame([a for a in asig_all_raw if a['id_nv'] not in ['AUSENCIA', 'INTERNO'] and a['comentarios'] != 'SIN_PROGRAMAR']) if asig_all_raw else pd.DataFrame()
            año_act, mes_act = datetime.today().year, datetime.today().month
            lista_anios = list(range(año_act - 2, año_act + 2))
            
            c_f1, c_f2 = st.columns(2)
            m_sel = c_f1.selectbox("Mes:", list(MESES_ES.values()), index=mes_act-1)
            a_sel = c_f2.selectbox("Año:", lista_anios, index=lista_anios.index(año_act))
            m_num = list(MESES_ES.keys())[list(MESES_ES.values()).index(m_sel)]
            f_i_m, f_f_m = datetime(a_sel, m_num, 1).date(), datetime(a_sel, m_num, calendar.monthrange(a_sel, m_num)[1]).date()

            t_g, t_i, t_o, t_h, t_t, t_p, t_pa, t_f = st.tabs(["🌍 Global", "🔍 Individual", "👥 Ocupación", "📅 Trazabilidad", "📋 Facturación", "⏳ Backlog", "📈 Proyección Anual", "✅ Historial Facturado"])

            with t_g:
                d_hab_m = sum(1 for i in range((f_f_m - f_i_m).days + 1) if (f_i_m + timedelta(days=i)).weekday() < 5 and (f_i_m + timedelta(days=i)).strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026)
                c_neta = d_hab_m * len(ESPECIALISTAS) - sum(1 for a in asig_all_raw if a['id_nv']=='AUSENCIA' for d in range((pd.to_datetime(a['fecha_fin']).date() - pd.to_datetime(a['fecha_inicio']).date()).days + 1) if f_i_m <= pd.to_datetime(a['fecha_inicio']).date() + timedelta(days=d) <= f_f_m and (pd.to_datetime(a['fecha_inicio']).date() + timedelta(days=d)).weekday() < 5) if asig_all_raw else d_hab_m * len(ESPECIALISTAS)
                
                tot_p, tot_e, hoy = 0, 0, datetime.today().date()
                if not df_all_valid.empty:
                    for _, a in df_all_valid.iterrows():
                        fi, ff = pd.to_datetime(a['fecha_inicio']).date(), pd.to_datetime(a['fecha_fin']).date()
                        os, oe = max(fi, f_i_m), min(ff, f_f_m)
                        if os <= oe:
                            inc = 'EXTRAS' in str(a.get('comentarios', '')).upper()
                            tot_p += sum(1 for i in range((oe - os).days + 1) if inc or ((os+timedelta(days=i)).weekday() < 5 and (os+timedelta(days=i)).strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026))
                            re = min(oe, hoy)
                            if os <= re: tot_e += sum(1 for i in range((re - os).days + 1) if inc or ((os+timedelta(days=i)).weekday() < 5 and (os+timedelta(days=i)).strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026))
                
                c1, c2 = st.columns(2)
                c1.metric("Cartera Ofertada (USD)", f"USD ${sum(r['monto_vendido'] if r['moneda']=='USD' else r['monto_vendido']/tasa_cambio for _,r in df_k.iterrows()):,.2f}")
                c2.metric("Gasto Acumulado (USD)", f"USD ${sum(r['monto_gasto'] for _,r in df_g_agg.iterrows())/tasa_cambio:,.2f}")
                
                cg1, cg2 = st.columns(2)
                with cg1:
                    fig_t = px.bar(pd.DataFrame({"C": ["Días Equipo", "Planificado (Matriz)", "Real (Gantt)"], "V": [c_neta, tot_p, tot_e]}), x="C", y="V", color="C", text="V", color_discrete_map={"Días Equipo": "#95A5A6", "Planificado (Matriz)": "#3498DB", "Real (Gantt)": "#2ECC71"})
                    fig_t.update_traces(textposition='outside'); fig_t.update_layout(yaxis_title="Días", showlegend=False, plot_bgcolor='white')
                    st.plotly_chart(fig_t, use_container_width=True)
                with cg2:
                    df_s = df_k[df_k['tipo_servicio'] == 'SSEE'].sort_values('Avance_%')
                    df_t = df_k[df_k['tipo_servicio'] == 'SE TERRENO'].sort_values('Avance_%')
                    if not df_s.empty: st.plotly_chart(px.bar(df_s, y="Proyecto_Label", x="Avance_%", title="🔹 SSEE (Salas Eléctricas)", text="Avance_%").update_traces(texttemplate='%{text:.1f}%'), use_container_width=True)
                    if not df_t.empty: st.plotly_chart(px.bar(df_t, y="Proyecto_Label", x="Avance_%", title="🔸 SE Terreno", text="Avance_%").update_traces(texttemplate='%{text:.1f}%'), use_container_width=True)

            with t_i:
                nv_sel = st.selectbox("Proyecto", df_k['Proyecto_Label'].tolist())
                if nv_sel:
                    r_nv = df_k[df_k['Proyecto_Label'] == nv_sel].iloc[0]
                    d_p_m, d_e_t, hoy = 0, 0, datetime.today().date()
                    if asig_all_raw:
                        d_p_m = len(set(f_i_m + timedelta(days=x) for a in asig_all_raw if a['id_nv']==r_nv['id_nv'] and a['actividad_ssee']=='PROYECCION_GLOBAL' for x in range((pd.to_datetime(a['fecha_fin']).date() - pd.to_datetime(a['fecha_inicio']).date()).days + 1) if ('EXTRAS' in str(a.get('comentarios')).upper() or ((pd.to_datetime(a['fecha_inicio']).date() + timedelta(days=x)).weekday() < 5 and (pd.to_datetime(a['fecha_inicio']).date() + timedelta(days=x)).strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026))))
                        d_e_t = len(set(pd.to_datetime(a['fecha_inicio']).date() + timedelta(days=x) for a in asig_all_raw if a['id_nv']==r_nv['id_nv'] and a['actividad_ssee']!='PROYECCION_GLOBAL' for x in range((pd.to_datetime(a['fecha_fin']).date() - pd.to_datetime(a['fecha_inicio']).date()).days + 1) if pd.to_datetime(a['fecha_inicio']).date() + timedelta(days=x) <= hoy and ('EXTRAS' in str(a.get('comentarios')).upper() or ((pd.to_datetime(a['fecha_inicio']).date() + timedelta(days=x)).weekday() < 5 and (pd.to_datetime(a['fecha_inicio']).date() + timedelta(days=x)).strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026))))
                    
                    st.metric("Balance de Días", f"{d_e_t} Reales / {d_p_m} Plan (Restan {d_p_m - d_e_t})")
                    fig_b = go.Figure()
                    fig_b.add_trace(go.Bar(name='Planificado', x=['Tiempos'], y=[d_p_m], marker_color='#3498DB', text=[f"{d_p_m} Plan"], textposition='outside', width=0.4))
                    fig_b.add_trace(go.Bar(name='Real', x=['Tiempos'], y=[d_e_t], marker_color="#E74C3C" if d_e_t > d_p_m else "#2ECC71", text=[f"{d_e_t} Real"], textposition='inside', width=0.25))
                    fig_b.update_layout(barmode='overlay', plot_bgcolor='white', height=300); st.plotly_chart(fig_b, use_container_width=True)

            with t_o:
                f_oc = st.radio("Área:", ["Global", "SSEE", "SE Terreno", "Oficina"], horizontal=True)
                dias_m = [f_i_m + timedelta(days=i) for i in range((f_f_m - f_i_m).days + 1)]
                tot_d_m = len(dias_m)
                mapa_ts = {n['id_nv']: n['tipo_servicio'] for n in nvs_all} if nvs_all else {}
                mapa_ts.update({'INTERNO': 'INTERNO', 'AUSENCIA': 'AUSENCIA'})
                
                dat_oc = []
                for esp in ESPECIALISTAS:
                    ds, dt, di, da = set(), set(), set(), set()
                    for a in [x for x in asig_all_raw if x.get('especialista')==esp and x.get('comentarios')!='SIN_PROGRAMAR'] if asig_all_raw else []:
                        try: fi, ff = pd.to_datetime(a['fecha_inicio']).date(), pd.to_datetime(a['fecha_fin']).date()
                        except: continue
                        ts = mapa_ts.get(a.get('id_nv'))
                        inc = 'EXTRAS' in str(a.get('comentarios','')).upper()
                        for d in dias_m:
                            if fi <= d <= ff and (inc or (d.weekday() < 5 and d.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026)):
                                if ts == 'AUSENCIA': da.add(d)
                                elif ts == 'INTERNO': di.add(d)
                                elif ts == 'SSEE': ds.add(d)
                                elif ts == 'SE TERRENO': dt.add(d)
                    ds, dt, di = ds - da, dt - da, di - da
                    d_graf = len(ds) if f_oc=="SSEE" else (len(dt) if f_oc=="SE Terreno" else (len(di) if f_oc=="Oficina" else len(ds|dt|di)))
                    dat_oc.append({"Especialista": esp, "Trabajados": d_graf, "Disponibles": max(0, tot_d_m - d_graf), "%": round((d_graf/tot_d_m*100) if tot_d_m>0 else 0, 1)})
                
                df_oc = pd.DataFrame(dat_oc).sort_values("%", ascending=False)
                st.plotly_chart(px.bar(df_oc, x="Especialista", y=["Trabajados", "Disponibles"], color_discrete_map={"Trabajados": "#3498DB", "Disponibles": "#2ECC71"}).update_layout(barmode='stack', plot_bgcolor='white'), use_container_width=True)

            with t_h:
                nv_h = st.selectbox("Proyecto Historial:", df_k['Proyecto_Label'].tolist())
                if nv_h and asig_all_raw:
                    df_h_r = pd.DataFrame([a for a in asig_all_raw if a['id_nv'] == df_k[df_k['Proyecto_Label']==nv_h].iloc[0]['id_nv'] and a['actividad_ssee']!='PROYECCION_GLOBAL'])
                    if not df_h_r.empty:
                        df_h_r['hd'] = pd.to_numeric(df_h_r['horas_diarias'], errors='coerce').fillna(9.0)
                        df_h_r['dh'] = pd.to_numeric(df_h_r['hh_asignadas'], errors='coerce').fillna(0) / df_h_r['hd']
                        grp = df_h_r.groupby(['actividad_ssee', 'fecha_inicio', 'fecha_fin', 'justificacion', 'progreso']).agg({'especialista': lambda x: ", ".join(set(x)), 'dh': 'sum'}).reset_index()
                        st.dataframe(grp, use_container_width=True)

            with t_t:
                st.markdown(f"### 💸 Pronóstico Activo {m_sel} {a_sel}")
                df_hm = df_h[(df_h['mes']==m_num) & (df_h['anio']==a_sel)].copy()
                if not df_hm.empty: df_hm = df_hm.merge(df_k[['id_nv', 'cliente', 'moneda', 'monto_pendiente']], on='id_nv', how='left')
                
                n_filas = []
                if not df_all_valid.empty:
                    df_mf = df_all_valid.groupby('id_nv')['fecha_fin'].max().reset_index()
                    df_mf['fecha_fin'] = pd.to_datetime(df_mf['fecha_fin']).dt.date
                    for _, r in df_k.merge(df_mf, on='id_nv', how='inner').iterrows():
                        if pd.to_datetime(r['fecha_fin']).month == m_num and pd.to_datetime(r['fecha_fin']).year == a_sel and r['monto_pendiente'] > 0 and df_h[df_h['id_nv']==r['id_nv']].empty:
                            n_filas.append({'id': 'Auto', 'id_nv': r['id_nv'], 'cliente': r['cliente'], 'moneda': r['moneda'], 'porcentaje': 100, 'monto': r['monto_pendiente'], 'estado': 'Pronóstico Auto'})
                
                df_hm = pd.concat([df_hm, pd.DataFrame(n_filas)], ignore_index=True) if n_filas else df_hm
                if not df_hm.empty:
                    df_hm['usd'] = df_hm.apply(lambda r: r['monto'] if r['moneda']=='USD' else r['monto']/tasa_cambio, axis=1)
                    st.metric("Total Pronosticado (USD)", f"USD ${df_hm['usd'].sum():,.2f}")
                    st.dataframe(df_hm[['id_nv', 'cliente', 'porcentaje', 'monto', 'estado']], use_container_width=True)
                else: st.info("Sin facturación pronosticada.")
                
                st.divider()
                st.markdown("### ⚙️ Crear Parcialidad / Hito")
                nv_h_sel = st.selectbox("Proyecto a planificar:", df_k['Proyecto_Label'].tolist())
                if nv_h_sel:
                    r_ph = df_k[df_k['Proyecto_Label']==nv_h_sel].iloc[0]
                    rest = r_ph['monto_vendido'] - df_h[df_h['id_nv']==r_ph['id_nv']]['monto'].sum()
                    st.write(f"**Restante:** {r_ph['moneda']} ${rest:,.2f}")
                    if rest > 0:
                        with st.form("form_add_hito"):
                            c_hm, c_ha, c_hp = st.columns(3)
                            h_mes = c_hm.selectbox("Mes de Facturación", list(MESES_ES.values()))
                            h_anio = c_ha.selectbox("Año", lista_anios, index=lista_anios.index(año_act))
                            h_val = c_hp.number_input("Monto a cobrar", max_value=float(rest), value=float(rest))
                            if st.form_submit_button("Agregar Hito") and h_val > 0:
                                supabase.table("hitos_facturacion").insert({"id_nv": r_ph['id_nv'], "mes": list(MESES_ES.keys())[list(MESES_ES.values()).index(h_mes)], "anio": h_anio, "porcentaje": (h_val/r_ph['monto_vendido'])*100, "monto": h_val, "estado": "Pendiente"}).execute()
                                st.success("✅ Guardado"); st.rerun()

            with t_pa:
                st.subheader("Servicios Pendientes (Backlog)")
                df_pe = df_k[df_k['monto_pendiente'] > 0].copy()
                if not df_pe.empty:
                    df_pe['usd'] = df_pe.apply(lambda r: r['monto_pendiente'] if r['moneda']=='USD' else r['monto_pendiente']/tasa_cambio, axis=1)
                    st.metric("Total Backlog (USD)", f"USD ${df_pe['usd'].sum():,.2f}")
                    st.dataframe(df_pe[['id_nv', 'cliente', 'tipo_servicio', 'monto_pendiente', 'estado_facturacion']], use_container_width=True)

            with t_p:
                st.subheader("📈 Proyección Anual")
                hc = df_h.copy()
                if not hc.empty: hc = hc.merge(df_k[['id_nv', 'moneda']], on='id_nv', how='left')
                hc['clp'] = hc.apply(lambda r: r['monto'] if r['moneda']=='CLP' else r['monto']*tasa_cambio, axis=1) if not hc.empty else 0
                hc['Tipo'] = hc['estado'].apply(lambda x: 'Facturado' if x=='Facturada' else 'Proyectado') if not hc.empty else ''
                
                ar = []
                if not df_all_valid.empty:
                    mf = df_all_valid.groupby('id_nv')['fecha_fin'].max().reset_index()
                    for _, r in df_k.merge(mf, on='id_nv', how='inner').iterrows():
                        if df_h[df_h['id_nv']==r['id_nv']].empty and r['monto_pendiente'] > 0:
                            ar.append({'mes': pd.to_datetime(r['fecha_fin']).month, 'anio': pd.to_datetime(r['fecha_fin']).year, 'clp': r['monto_pendiente'] if r['moneda']=='CLP' else r['monto_pendiente']*tasa_cambio, 'Tipo': 'Proyectado'})
                
                cf = pd.concat([hc[['mes', 'anio', 'clp', 'Tipo']], pd.DataFrame(ar)], ignore_index=True) if ar else hc
                if not cf.empty:
                    cf['ord'] = cf.apply(lambda r: f"{int(r['anio'])}-{int(r['mes']):02d}", axis=1)
                    cf['ma'] = cf.apply(lambda r: f"{MESES_ES[int(r['mes'])]} {int(r['anio'])}", axis=1)
                    grp_c = cf.groupby(['ord', 'ma', 'Tipo'])['clp'].sum().reset_index().sort_values('ord')
                    fig_p = px.bar(grp_c, x='ma', y='clp', color='Tipo', text='clp', color_discrete_map={'Facturado': '#2ECC71', 'Proyectado': '#3498DB'})
                    fig_p.add_hline(y=110000000, line_dash="dash", line_color="#FF6600", annotation_text="Meta $110M CLP")
                    fig_p.update_traces(texttemplate='$%{text:,.0f}', textposition='inside'); fig_p.update_layout(barmode='stack')
                    st.plotly_chart(fig_p, use_container_width=True)

            with t_f:
                st.subheader("✅ Historial Facturado")
                hf = df_h[df_h['estado']=='Facturada']
                if not hf.empty: st.dataframe(hf, use_container_width=True)
                else: st.info("Sin registros facturados.")

    # === MÓDULO 5: CIERRE Y PDF ===
    with tab5:
        st.header("Cierre Técnico y Reporte")
        nv_c_label = st.selectbox("Cerrar Proyecto", [n['id_nv'] for n in obtener_nvs("Abierta")]) if obtener_nvs("Abierta") else None
        if nv_c_label and st.button("🔴 CERRAR Y GENERAR PDF"):
            supabase.table("notas_venta").update({"estado": "Cerrada"}).eq("id_nv", nv_c_label).execute()
            st.success(f"Proyecto {nv_c_label} cerrado.")

if not st.session_state.authenticated: login_screen()
else: main_app()
