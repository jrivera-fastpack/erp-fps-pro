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
    st.error("Error crítico: No se pudo conectar a la base de datos Supabase. Verifique secrets.toml o la configuración en Streamlit Cloud.")
    st.stop()

# --- INICIALIZACIÓN DE PROYECTOS INTERNOS (RRHH Y OPERACIONES) ---
try:
    aus_nv = supabase.table("notas_venta").select("id_nv").eq("id_nv", "AUSENCIA").execute()
    if not aus_nv.data:
        supabase.table("notas_venta").insert({
            "id_nv": "AUSENCIA", "cliente": "Gestión Interna (RRHH)", "tipo_servicio": "SE TERRENO", 
            "lugar": "Oficina/Casa", "moneda": "CLP", "monto_vendido": 0.0, 
            "hh_vendidas": 0.0, "estado": "Abierta"
        }).execute()
        
    int_nv = supabase.table("notas_venta").select("id_nv").eq("id_nv", "INTERNO").execute()
    if not int_nv.data:
        supabase.table("notas_venta").insert({
            "id_nv": "INTERNO", "cliente": "Gestión Interna (Operaciones)", "tipo_servicio": "SE TERRENO", 
            "lugar": "Oficina/Nave FPS", "moneda": "CLP", "monto_vendido": 0.0, 
            "hh_vendidas": 0.0, "estado": "Abierta"
        }).execute()
except Exception:
    pass

# --- FUNCIÓN DE INSERCIÓN BLINDADA ---
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
            st.toast("⚠️ Base de datos desactualizada. Ejecute comandos SQL para activar horarios personalizados y KPIs.", icon="⚠️")
            return res
        else:
            raise ex_db

# --- CONSTANTES GLOBALES ---
ESPECIALISTAS = [
    "Felipe Romero", "David Colina", "Adelmo Calderon", "Jose Valenzuela", 
    "Jose Peña", "German Contreras", "Esteban Romero", "Nicolas Salazar", 
    "Javier Segovia", "Jonathan Aguilar", "Ignacio Castro", "Javier Rivera"
]

ABREVIATURAS = {
    "Entrega materiales": "Mat", 
    "Montaje de detección": "M.Det", 
    "Montaje de supresión": "M.Sup", 
    "Montaje de VESDA": "M.VESDA",
    "Cableado y conexionado": "Cabl", 
    "Programación": "Prog", 
    "PEM": "PEM", 
    "Entrega de red line": "RedLine"
}

FERIADOS_CHILE_2026 = [
    "01-01-2026", "03-04-2026", "04-04-2026", "01-05-2026", "21-05-2026", 
    "29-06-2026", "16-07-2026", "15-08-2026", "18-09-2026", "19-09-2026", 
    "12-10-2026", "31-10-2026", "01-11-2026", "08-12-2026", "25-12-2026"
]

DIAS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MESES_ES = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}
LISTA_MODALIDADES = [
    "Normal (Simultáneo, Lun-Vie)", 
    "Continuo (Simultáneo, Lun-Dom)", 
    "Turno 4x3 (Simultáneo)", "Turno 4x3 (Contra Turno)", 
    "Turno 7x7 (Simultáneo)", "Turno 7x7 (Contra Turno)", 
    "Turno 14x14 (Simultáneo)", "Turno 14x14 (Contra Turno)"
]

# --- MOTOR DE GENERACIÓN DE TURNOS INTELIGENTE ---
def generar_bloques_turno(f_ini, dias_totales, modalidad, especialistas):
    bloques = []
    if not especialistas: especialistas = ["Sin Asignar"]
    
    es_turno = "Turno" in modalidad
    es_continuo = "Continuo" in modalidad or es_turno
    es_contra = "Contra Turno" in modalidad and len(especialistas) > 1
    
    if not es_turno:
        f_f = calcular_fecha_fin_dinamica(f_ini, dias_totales, es_continuo)
        for esp in especialistas:
            bloques.append({
                "especialista": esp, "f_ini": f_ini, "f_f": f_f, 
                "comentarios": "EXTRAS" if es_continuo else "LIBRES",
                "es_descanso": False
            })
        return bloques
        
    # Lógica Matemática para Turnos (4x3, 7x7, 14x14)
    dias_t = 4 if "4x3" in modalidad else (7 if "7x7" in modalidad else 14)
    dias_d = 3 if "4x3" in modalidad else (7 if "7x7" in modalidad else 14)
    ciclo = dias_t + dias_d
    
    fecha_limite = f_ini + timedelta(days=int(dias_totales) - 1)
    
    for i, esp in enumerate(especialistas):
        start_offset = (i * dias_d) if es_contra else 0
        fecha_actual = f_ini + timedelta(days=start_offset)
        
        while fecha_actual <= fecha_limite:
            f_f_bloque = fecha_actual + timedelta(days=dias_t - 1)
            
            if fecha_actual > fecha_limite: break
            if f_f_bloque > fecha_limite: f_f_bloque = fecha_limite
                
            bloques.append({
                "especialista": esp, "f_ini": fecha_actual, "f_f": f_f_bloque, 
                "comentarios": "EXTRAS", "es_descanso": False
            })
            
            # Generar bloque de descanso explícito
            f_ini_desc = f_f_bloque + timedelta(days=1)
            f_f_desc = f_ini_desc + timedelta(days=dias_d - 1)
            
            if f_ini_desc <= fecha_limite:
                if f_f_desc > fecha_limite: f_f_desc = fecha_limite
                bloques.append({
                    "especialista": esp, "f_ini": f_ini_desc, "f_f": f_f_desc, 
                    "comentarios": "DESCANSO", "es_descanso": True
                })
                
            fecha_actual += timedelta(days=ciclo)
            
    return bloques

# --- FUNCIONES AUXILIARES ---
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
            email = st.text_input("Correo Electrónico", placeholder="usuario@empresa.com")
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
    st.sidebar.header("⚙️ Configuración Global")
    tasa_cambio = st.sidebar.number_input("Valor del Dólar (CLP)", min_value=1.0, value=950.0, step=1.0)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📝 1. Comercial", "🗓️ 2. Matriz Semanal", "⚙️ 3. Ejecución y Gantt", "💰 4. Gastos y KPIs", "📄 5. Cierre y Reporte PDF"])

    # === MÓDULO 1: COMERCIAL ===
    with tab1:
        st.header("Gestión Comercial (Presupuesto)")
        col_form, col_admin = st.columns([2, 1])
        with col_form:
            if 'nv_pending' not in st.session_state: st.session_state.nv_pending = None
            if 'nv_conflicts' not in st.session_state: st.session_state.nv_conflicts = []

            if st.session_state.nv_pending is not None:
                st.warning("⚠️ **Cruces de Fechas Detectados**")
                for conf in st.session_state.nv_conflicts: 
                    st.write(f"- 👨‍🔧 **{conf['especialista']}** asignado a **{conf['id_nv']}** ({conf['fecha_inicio']} al {conf['fecha_fin']}).")
                decision = st.radio("¿Cómo proceder?", ["Mantener en ambos servicios", "Quitar de los servicios anteriores"])
                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    if st.button("✅ Confirmar y Guardar", use_container_width=True):
                        try:
                            payload = st.session_state.nv_pending
                            supabase.table("notas_venta").insert({"id_nv": payload["id_nv"], "cliente": payload["cliente"], "tipo_servicio": payload["tipo_servicio"], "lugar": payload["lugar"], "moneda": payload["moneda"], "monto_vendido": payload["monto_vendido"], "hh_vendidas": payload["hh_vendidas"], "estado": "Abierta"}).execute()
                            if "Quitar" in decision:
                                for conf in st.session_state.nv_conflicts: supabase.table("asignaciones_personal").delete().eq("id", conf['id']).execute()
                                
                            bloques_gen = generar_bloques_turno(payload["f_ini"], payload["hh_vendidas"], payload["modalidad"], payload["especialistas_sel"])
                            for b in bloques_gen:
                                safe_insert_asignacion({"id_nv": payload["id_nv"], "especialista": b['especialista'], "fecha_inicio": str(b['f_ini']), "fecha_fin": str(b['f_f']), "hh_asignadas": 0, "actividad_ssee": "PROYECCION_GLOBAL", "comentarios": b['comentarios'], "progreso": 0, "hora_inicio_t": payload["h_inicio_val"], "hora_fin_t": payload["h_fin_val"], "horas_diarias": 0 if b.get('es_descanso') else payload["h_diarias_val"]})
                            
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
                    if moneda == "CLP": monto_str = col_mnt.text_input("Monto Ofertado", value="", placeholder="Ej: 14.538.342")
                    else: monto_usd = col_mnt.number_input("Monto Ofertado", min_value=0.0, step=0.01)
                    
                    st.divider()
                    st.markdown("### Proyección Matriz Semanal")
                    
                    if tipo == "SE TERRENO":
                        st.markdown("#### 🕒 Modalidad y Horarios de Terreno")
                        c_th1, c_th2, c_th3 = st.columns(3)
                        modalidad = c_th1.selectbox("Modalidad / Turno", LISTA_MODALIDADES)
                        st.caption("💡 Si elige un Turno (4x3, 7x7), se recomienda configurar HH Día a 12.0 y Horarios de 08:00 a 20:00.")
                        
                        default_hd = 12.0 if "Turno" in modalidad else 9.5
                        h_inicio_val = c_th2.time_input("Hora Inicio", value=datetime.strptime('08:00', '%H:%M').time())
                        h_fin_val = c_th3.time_input("Hora Fin", value=datetime.strptime('20:00' if "Turno" in modalidad else '17:30', '%H:%M').time())
                        h_diarias_val = c_th3.number_input("Horas día", value=default_hd, step=0.5)
                    else:
                        modalidad = "Normal (Simultáneo, Lun-Vie)"
                        h_inicio_val, h_fin_val, h_diarias_val = None, None, None
                    
                    c4, c5, c6 = st.columns(3)
                    dias_v = c4.number_input("Rango Total de Días (Duración del Proyecto)", min_value=0.0, step=1.0)
                    f_ini = c5.date_input("Fecha de Inicio", format="DD/MM/YYYY", value=None)
                    especialistas_sel = c6.multiselect("Especialistas", ESPECIALISTAS)

                    if st.form_submit_button("Guardar Nota de Venta", use_container_width=True):
                        id_nv = f"{id_nv_base.strip()} - {item_nv.strip()}" if item_nv.strip() else id_nv_base.strip()
                        monto = float(str(monto_str).replace(".", "").replace(",", "").strip()) if moneda == "CLP" and str(monto_str).replace(".", "").isdigit() else (monto_usd if moneda == "USD" else 0.0)
                        
                        if id_nv and cliente:
                            verificacion = supabase.table("notas_venta").select("id_nv").eq("id_nv", id_nv).execute()
                            if len(verificacion.data) > 0: st.warning("⚠️ ID ya existe.")
                            else:
                                if especialistas_sel and dias_v > 0 and f_ini is not None:
                                    bloques_gen = generar_bloques_turno(f_ini, dias_v, modalidad, especialistas_sel)
                                    asig_existentes = supabase.table("asignaciones_personal").select("*").in_("especialista", especialistas_sel).execute().data
                                    
                                    conflictos = []
                                    seen_ids = set()
                                    for b in bloques_gen:
                                        for a in asig_existentes:
                                            if a['especialista'] == b['especialista']:
                                                a_ini, a_fin = pd.to_datetime(a['fecha_inicio']).date(), pd.to_datetime(a['fecha_fin']).date()
                                                if b['f_ini'] <= a_fin and b['f_f'] >= a_ini and a['id'] not in seen_ids:
                                                    conflictos.append(a)
                                                    seen_ids.add(a['id'])
                                                
                                    if conflictos:
                                        st.session_state.nv_pending = {"id_nv": id_nv, "cliente": cliente, "tipo_servicio": tipo, "lugar": lugar, "moneda": moneda, "monto_vendido": monto, "hh_vendidas": dias_v, "estado": "Abierta", "especialistas_sel": especialistas_sel, "f_ini": f_ini, "modalidad": modalidad, "h_inicio_val": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00', "h_fin_val": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30', "h_diarias_val": h_diarias_val}
                                        st.session_state.nv_conflicts = conflictos
                                        st.rerun()
                                    else:
                                        supabase.table("notas_venta").insert({"id_nv": id_nv, "cliente": cliente, "tipo_servicio": tipo, "lugar": lugar, "moneda": moneda, "monto_vendido": monto, "hh_vendidas": dias_v, "estado": "Abierta"}).execute()
                                        for b in bloques_gen: safe_insert_asignacion({"id_nv": id_nv, "especialista": b['especialista'], "fecha_inicio": str(b['f_ini']), "fecha_fin": str(b['f_f']), "hh_asignadas": 0, "actividad_ssee": "PROYECCION_GLOBAL", "comentarios": b['comentarios'], "progreso": 0, "hora_inicio_t": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00', "hora_fin_t": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30', "horas_diarias": 0 if b.get('es_descanso') else (h_diarias_val if h_diarias_val else 0)})
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
                                st.markdown("#### 🕒 Modalidad y Horarios")
                                c_t1, c_t2, c_t3 = st.columns(3)
                                modalidad_matriz = c_t1.selectbox("Turno", LISTA_MODALIDADES)
                                default_hd = 12.0 if "Turno" in modalidad_matriz else 9.5
                                h_inicio_val = c_t2.time_input("Inicio", value=datetime.strptime('08:00', '%H:%M').time())
                                h_fin_val = c_t3.time_input("Fin", value=datetime.strptime('20:00' if "Turno" in modalidad_matriz else '17:30', '%H:%M').time())
                                h_diarias_val = c_t3.number_input("Horas día", value=default_hd, step=0.5)
                            else:
                                modalidad_matriz = "Normal (Simultáneo, Lun-Vie)"
                                h_inicio_val, h_fin_val, h_diarias_val = None, None, None
                            
                            c_f1, c_f2 = st.columns(2)
                            f_ini = c_f1.date_input("Fecha Inicio", format="DD/MM/YYYY")
                            
                            val_dias_db = float(nv_data_sel.get('hh_vendidas', 5.0))
                            val_min_seguro = val_dias_db if val_dias_db >= 1.0 else 1.0
                            dias_proy = c_f2.number_input("Rango Total de Días", min_value=1.0, value=val_min_seguro)
                            
                            if st.form_submit_button("Guardar Proyección", use_container_width=True):
                                supabase.table("asignaciones_personal").delete().eq("id_nv", nv_data_sel['id_nv']).eq("actividad_ssee", "PROYECCION_GLOBAL").execute()
                                bloques_gen = generar_bloques_turno(f_ini, dias_proy, modalidad_matriz, especialistas_sel)
                                for b in bloques_gen: 
                                    safe_insert_asignacion({"id_nv": nv_data_sel['id_nv'], "especialista": b['especialista'], "fecha_inicio": str(b['f_ini']), "fecha_fin": str(b['f_f']), "hh_asignadas": 0, "actividad_ssee": "PROYECCION_GLOBAL", "comentarios": b['comentarios'], "progreso": 0, "hora_inicio_t": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00', "hora_fin_t": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30', "horas_diarias": 0 if b.get('es_descanso') else (h_diarias_val if h_diarias_val else 0)})
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
                esp_val = a.get('especialista')
                if not esp_val or esp_val not in ESPECIALISTAS:
                    continue
                    
                try: 
                    f_i, f_f = pd.to_datetime(a['fecha_inicio']).date(), pd.to_datetime(a['fecha_fin']).date()
                except: continue
                
                if a['id_nv'] == 'AUSENCIA':
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        if d in fechas_rango: 
                            matriz_final.at[esp_val, d.strftime("%d-%m-%Y")] = f"🌴 {a['actividad_ssee']}"
                
                elif a['id_nv'] == 'INTERNO':
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        if d.weekday() < 5 and d.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026 and d in fechas_rango:
                            col = d.strftime("%d-%m-%Y")
                            val = str(matriz_final.at[esp_val, col])
                            if '🌴' not in val: 
                                matriz_final.at[esp_val, col] = f"🏢 {a['actividad_ssee']}" if val in ["🟢 Disponible", "⌛ No Hábil"] else val + f" + 🏢 {a['actividad_ssee']}"
                
                elif a.get('actividad_ssee') == 'PROYECCION_GLOBAL':
                    es_cont = a.get('comentarios') == 'EXTRAS'
                    es_descanso = a.get('comentarios') == 'DESCANSO'
                    cliente_nombre = mapa_clientes.get(a['id_nv'], 'Proyectado')
                    
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        es_feriado = d.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
                        es_finde = d.weekday() >= 5
                        
                        if not es_cont and not es_descanso and (es_finde or es_feriado): continue
                        
                        if d in fechas_rango:
                            col = d.strftime("%d-%m-%Y")
                            valor_actual = str(matriz_final.at[esp_val, col])
                            
                            if '🌴' not in valor_actual:
                                etiqueta = f"🛏️ Descanso [{cliente_nombre}]" if es_descanso else f"{a['id_nv']} [{cliente_nombre}]"
                                if valor_actual in ["🟢 Disponible", "⌛ No Hábil"]: 
                                    matriz_final.at[esp_val, col] = etiqueta
                                elif etiqueta not in valor_actual: 
                                    matriz_final.at[esp_val, col] += f" + {etiqueta}"
        
        matriz_final.columns = cols_disp
        def style_m(x):
            if 'No Hábil' in str(x): return 'background-color: #F0F0F0; color: #A0A0A0'
            if '🌴' in str(x): return 'background-color: #FADBD8; color: #C0392B; font-weight: bold'
            if '🏢' in str(x): return 'background-color: #D6EAF8; color: #21618C; font-weight: bold'
            if '🛏️' in str(x): return 'background-color: #EAECEE; color: #5D6D7E; font-style: italic'
            if 'Disponible' in str(x): return 'background-color: #E6F2FF; color: #003366'
            return 'background-color: #D5F5E3; color: #196F3D; font-weight: bold'
        st.dataframe(matriz_final.style.map(style_m), use_container_width=True, height=550)

    # === MÓDULO 3: GANTT ===
    with tab3:
        st.header("Ejecución: Alcance, Programación Viva y Gantt")
        nvs_activas = obtener_nvs("Abierta")
        nv_id_sel = None
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
                    df_temp['key_grupo'] = df_temp['actividad_ssee'].fillna("General")
                    actividades_unicas = df_temp['key_grupo'].unique()
                    
                    # CORRECCIÓN DE CÁLCULO DE AVANCE: PROMEDIO DINÁMICO SOBRE LAS ACTIVIDADES REALMENTE AÑADIDAS
                    avance_total = min(100.0, max(0.0, df_temp.groupby('key_grupo')['progreso'].max().mean()))
                    st.markdown(f"**Avance Total del Proyecto: {avance_total:.1f}%**")
                    st.progress(int(avance_total))
                    st.markdown("---")
                    
                    hoy = datetime.today().date()
                    for act in actividades_unicas:
                        df_act = df_temp[df_temp['key_grupo'] == act].copy()
                        df_act['f_dt'] = pd.to_datetime(df_act['fecha_inicio'])
                        df_last = df_act[df_act['f_dt'] == df_act['f_dt'].max()]
                        c_prog = int(df_last['progreso'].max())
                        
                        just_series = df_last['justificacion'].dropna()
                        existing_just_raw = str(just_series.iloc[0]) if not just_series.empty else ""
                        is_paused = "[PAUSADA]" in existing_just_raw.upper()
                        estado = "⚪ Sin Fecha" if df_last['comentarios'].iloc[0] == "SIN_PROGRAMAR" else ("⏸️ PAUSADA" if is_paused else ("⚠️ ATRASADA" if pd.to_datetime(df_last['fecha_fin'].max()).date() < hoy and c_prog < 100 else "🟢 Programado"))
                        
                        with st.expander(f"{estado} | 📌 {act} - {c_prog}%"):
                            with st.form(key=f"f_{nv_id_sel}_{act}"):
                                accion = st.radio("Acción:", ["▶️ Reanudar Actividad", "Actualizar Avance"] if is_paused else ["Actualizar Avance / Fechas", "⏸️ Pausar Actividad"], horizontal=True)
                                c_p, c_f = st.columns([1, 1.5])
                                n_p = c_p.slider("Avance %", 0, 100, c_prog)
                                
                                c_d, c_e = st.columns(2)
                                if "Pausar" in accion:
                                    f_ini, f_pausa = df_last['f_dt'].max().date(), c_f.date_input("Fecha pausa", value=hoy)
                                    d_trab = max(1, (f_pausa - f_ini).days + 1)
                                    just = st.text_input("Motivo (Requerido)", value=existing_just_raw.replace("[PAUSADA]", "").strip())
                                elif "Reanudar" in accion:
                                    f_ini = c_f.date_input("Nueva Fecha Inicio", value=hoy)
                                    d_trab = c_d.number_input("Rango de Días (Duración)", min_value=1, value=1)
                                    just = st.text_input("Comentario")
                                else:
                                    f_ini = c_f.date_input("Inicio", value=df_last['f_dt'].max().date())
                                    d_trab = c_d.number_input("Rango de Días (Duración)", min_value=1, value=max(1, (pd.to_datetime(df_last['fecha_fin'].max()).date() - f_ini).days + 1))
                                    just = st.text_input("Justificación", value=existing_just_raw)
                                
                                val_d_extra = int(df_last['dias_extras'].max()) if 'dias_extras' in df_last.columns and pd.notna(df_last['dias_extras'].max()) else 0
                                d_extra = c_d.number_input("Días Extra", min_value=0, value=max(0, val_d_extra))
                                
                                if dict_nvs_label[nv_label_sel]['tipo_servicio'] == 'SE TERRENO':
                                    modalidad_turno = c_d.selectbox("Modalidad / Turno", LISTA_MODALIDADES)
                                    ct1, ct2, ct3 = st.columns(3)
                                    hi = ct1.time_input("Hora Ini", value=datetime.strptime(df_last['hora_inicio_t'].iloc[0] if 'hora_inicio_t' in df_last.columns and pd.notna(df_last['hora_inicio_t'].iloc[0]) else '08:00', '%H:%M').time())
                                    hf = ct2.time_input("Hora Fin", value=datetime.strptime(df_last['hora_fin_t'].iloc[0] if 'hora_fin_t' in df_last.columns and pd.notna(df_last['hora_fin_t'].iloc[0]) else '17:30', '%H:%M').time())
                                    hd = ct3.number_input("HH día", value=float(df_last['horas_diarias'].iloc[0]) if 'horas_diarias' in df_last.columns and pd.notna(df_last['horas_diarias'].iloc[0]) and float(df_last['horas_diarias'].iloc[0])>0 else 9.5)
                                else: 
                                    modalidad_turno = "Normal (Simultáneo, Lun-Vie)"
                                    hi, hf, hd = None, None, None
                                
                                esps = c_e.multiselect("Técnicos", ESPECIALISTAS, default=[e for e in df_last['especialista'].unique() if e in ESPECIALISTAS] or esps_matriz)
                                
                                if st.form_submit_button("Guardar Operación"):
                                    try:
                                        if "Reanudar" in accion:
                                            for rid in df_last['id'].tolist(): supabase.table("asignaciones_personal").update({"justificacion": str(df_last[df_last['id']==rid]['justificacion'].iloc[0]).replace("[PAUSADA]", "").strip() + " (Fin)"}).eq("id", rid).execute()
                                        else:
                                            for rid in df_last['id'].tolist(): supabase.table("asignaciones_personal").delete().eq("id", rid).execute()
                                        
                                        supabase.table("asignaciones_personal").update({"progreso": n_p}).eq("id_nv", nv_id_sel).eq("actividad_ssee", act).execute()
                                        bloques_ejecucion = generar_bloques_turno(f_ini, d_trab, modalidad_turno, esps)
                                        final_j = f"[PAUSADA] {just}" if "Pausar" in accion else just
                                        
                                        for b in bloques_ejecucion:
                                            if b['comentarios'] == 'DESCANSO':
                                                hh_b = 0
                                                final_j_b = "Descanso de Turno"
                                            else:
                                                incluye_f = b['comentarios'] == 'EXTRAS'
                                                hh_b = calcular_hh_ssee(b['f_ini'], b['f_f'], incluye_f, hd) / (len(esps) if "Contra Turno" in modalidad_turno and len(esps)>1 else 1)
                                                final_j_b = final_j
                                                
                                            safe_insert_asignacion({"id_nv": nv_id_sel, "especialista": b['especialista'], "fecha_inicio": str(b['f_ini']), "fecha_fin": str(b['f_f']), "hh_asignadas": hh_b if b['especialista'] != "Sin Asignar" else 0, "actividad_ssee": act, "comentarios": b['comentarios'], "progreso": n_p, "dias_extras": d_extra if b['comentarios'] != 'DESCANSO' else 0, "justificacion": final_j_b, "hora_inicio_t": hi.strftime('%H:%M') if hi else '08:00', "hora_fin_t": hf.strftime('%H:%M') if hf else '17:30', "horas_diarias": hd if b['comentarios'] != 'DESCANSO' else 0})
                                        st.success("✅ Guardado."); st.rerun()
                                    except Exception as e: st.error(f"Error: {e}")
                
        st.divider()
        st.subheader("3. Cronograma Operativo (Gantt)")
        cv1, cv2, cv3, cv4 = st.columns([1,1,1,1])
        v_gantt = cv1.radio("Filtro de Vista:", ["🌍 General (Todos)", "🔍 Por Proyecto Seleccionado"], horizontal=True)
        f_tipo = cv2.radio("Tipo de Servicio (Filtra la vista General):", ["Todos", "SSEE", "SE TERRENO"], horizontal=True)
        f_tiemp = cv3.radio("⏳ Ventana de Tiempo:", ["Todo el Proyecto", "1 Semana", "15 Días", "1 Mes"], horizontal=True, index=2)
        d_ini_g = cv4.date_input("📅 Fecha de inicio", value=datetime.today().date())

        g_raw = supabase.table("asignaciones_personal").select("*").execute().data
        if g_raw:
            df_g = pd.DataFrame(g_raw)
            
            # Filtramos proyecciones y excluímos INTERNO/AUSENCIA para no ensuciar el Gantt
            df_g = df_g[(df_g['actividad_ssee'] != 'PROYECCION_GLOBAL') & (~df_g['id_nv'].isin(['INTERNO', 'AUSENCIA']))]
            
            nvs_gantt_todas = obtener_nvs()
            n_t = {n['id_nv']: n['tipo_servicio'] for n in nvs_gantt_todas} if nvs_gantt_todas else {}
            n_c = {n['id_nv']: n['cliente'] for n in nvs_gantt_todas} if nvs_gantt_todas else {}
            
            if v_gantt == "🔍 Por Proyecto Seleccionado" and nv_id_sel:
                df_g = df_g[df_g['id_nv'] == nv_id_sel]
            else:
                if f_tipo != "Todos":
                    df_g['tipo_temp'] = df_g['id_nv'].map(n_t)
                    df_g = df_g[df_g['tipo_temp'] == f_tipo]
            
            if not df_g.empty:
                df_g['cliente'] = df_g['id_nv'].map(n_c)
                df_g['Labor'] = df_g['actividad_ssee'].fillna('Servicio Terreno')
                
                if 'hora_inicio_t' in df_g.columns:
                    df_g['hora_i_str'] = df_g['hora_inicio_t'].fillna('08:00').replace('', '08:00')
                    df_g['hora_f_str'] = df_g['hora_fin_t'].fillna('17:30').replace('', '17:30')
                else:
                    df_g['hora_i_str'] = '08:00'
                    df_g['hora_f_str'] = '17:30'

                df_g['start_ts'] = pd.to_datetime(df_g['fecha_inicio'].astype(str) + ' ' + df_g['hora_i_str'])
                df_g['end_ts'] = pd.to_datetime(df_g['fecha_fin'].astype(str) + ' ' + df_g['hora_f_str'])
                
                # Excluir explícitamente tareas SIN PROGRAMAR y DESCANSO del gráfico
                df_g = df_g[(df_g['comentarios'] != 'SIN_PROGRAMAR') & (df_g['comentarios'] != 'DESCANSO')]
                
                if not df_g.empty:
                    df_grp = df_g.groupby(['id_nv', 'cliente', 'Labor', 'start_ts', 'end_ts', 'progreso', 'comentarios', 'justificacion']).agg({
                        'especialista': lambda x: ", ".join(set(x))
                    }).reset_index()
                    
                    df_grp = df_grp.sort_values(by=['id_nv', 'start_ts'], ascending=[True, True])
                    df_grp['Eje_Y'] = df_grp['id_nv'] + " | " + df_grp['Labor']
                    
                    rows = []
                    for _, r in df_grp.iterrows():
                        bl = f"{r['id_nv'].split(' - ')[0]} ({r['progreso']}%)"
                        is_paused = "[PAUSADA]" in str(r['justificacion']).upper()
                        r['Etiqueta_Barra'] = f"<b>⏸️ {bl}</b>" if is_paused else f"<b>{bl}</b>"
                        
                        # Si es Turno o Continuo ("EXTRAS"), la barra no se corta y cubre los fines de semana.
                        if r.get('comentarios') == 'EXTRAS':
                            r['start_ts'] = pd.to_datetime(r['start_ts'].date()) # 00:00
                            r['end_ts'] = pd.to_datetime(r['end_ts'].date()) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1) # 23:59:59
                            r['Inicio'] = r['start_ts'].strftime('%d/%m/%Y %H:%M')
                            r['Fin'] = r['end_ts'].strftime('%d/%m/%Y %H:%M')
                            rows.append(r)
                        
                        # Generar huecos en fines de semana/feriados si la labor es "LIBRES" (Normal)
                        elif r.get('comentarios') == 'LIBRES':
                            current_chunk_start = r['start_ts']
                            current_day = r['start_ts'].date()
                            end_day = r['end_ts'].date()
                            
                            while current_day <= end_day:
                                es_feriado = current_day.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
                                es_finde = current_day.weekday() >= 5
                                
                                if es_finde or es_feriado:
                                    prev_day = current_day - timedelta(days=1)
                                    if current_chunk_start is not None and current_chunk_start.date() <= prev_day:
                                        chunk_end = pd.Timestamp.combine(prev_day, r['end_ts'].time())
                                        new_r = r.copy()
                                        new_r['start_ts'] = current_chunk_start
                                        new_r['end_ts'] = chunk_end
                                        new_r['Inicio'] = current_chunk_start.strftime('%d/%m/%Y %H:%M')
                                        new_r['Fin'] = chunk_end.strftime('%d/%m/%Y %H:%M')
                                        rows.append(new_r)
                                    current_chunk_start = None
                                else:
                                    if current_chunk_start is None:
                                        current_chunk_start = pd.Timestamp.combine(current_day, r['start_ts'].time())
                                        
                                current_day += timedelta(days=1)
                            
                            if current_chunk_start is not None and current_chunk_start <= r['end_ts']:
                                new_r = r.copy()
                                new_r['start_ts'] = current_chunk_start
                                new_r['end_ts'] = r['end_ts']
                                new_r['Inicio'] = current_chunk_start.strftime('%d/%m/%Y %H:%M')
                                new_r['Fin'] = r['end_ts'].strftime('%d/%m/%Y %H:%M')
                                rows.append(new_r)
                        else:
                            r['Inicio'] = r['start_ts'].strftime('%d/%m/%Y %H:%M')
                            r['Fin'] = r['end_ts'].strftime('%d/%m/%Y %H:%M')
                            rows.append(r)
                    
                    df_p = pd.DataFrame(rows)
                    
                    t_i = pd.to_datetime(d_ini_g)
                    if f_tiemp == "1 Semana": t_f = t_i + pd.Timedelta(days=7)
                    elif f_tiemp == "15 Días": t_f = t_i + pd.Timedelta(days=15)
                    elif f_tiemp == "1 Mes": t_f = t_i + pd.Timedelta(days=30)
                    else: 
                        t_i = df_p['start_ts'].min() if not df_p.empty else t_i
                        t_f = df_p['end_ts'].max() if not df_p.empty else t_i + pd.Timedelta(days=30)
    
                    if f_tiemp != "Todo el Proyecto" and not df_p.empty:
                        df_p = df_p[(df_p['end_ts'] >= t_i) & (df_p['start_ts'] <= t_f)]
                    
                    if not df_p.empty:
                        orden_eje_y = df_p['Eje_Y'].unique()
                        colores_globo = ['#3498DB', '#E67E22', '#2ECC71', '#E74C3C', '#9B59B6', '#1ABC9C', '#F1C40F', '#7F8C8D']
    
                        fig = px.timeline(
                            df_p, 
                            x_start="start_ts", 
                            x_end="end_ts", 
                            y="Eje_Y", 
                            color="Labor",
                            text="Etiqueta_Barra",
                            hover_data={"especialista": True, "progreso": True, "Inicio": True, "Fin": True, "start_ts": False, "end_ts": False},
                            color_discrete_sequence=colores_globo
                        )
    
                        fig.update_traces(
                            textposition='auto', 
                            insidetextanchor='middle', 
                            marker_line_width=0, 
                            opacity=0.95, 
                            width=0.75, 
                            textfont=dict(size=13, color='#000000', family="Arial"),
                            constraintext='none'
                        )
                        
                        fig.update_yaxes(autorange="reversed", title="", type="category", tickmode="linear", tickfont=dict(size=14, color='#333', family="Arial"), gridcolor='rgba(0,0,0,0.05)', categoryorder='array', categoryarray=orden_eje_y, automargin=True)
                        
                        curr = t_i.replace(hour=0, minute=0, second=0, microsecond=0)
                        end_limit = t_f.replace(hour=0, minute=0, second=0, microsecond=0)
                        
                        if (end_limit - curr).days > 90:
                            end_limit = curr + pd.Timedelta(days=90)
                            st.warning("⚠️ El rango es muy amplio. Se muestran máximo 90 días en pantalla para evitar bloqueos.")
                        
                        fig.update_xaxes(range=[t_i.strftime("%Y-%m-%d 00:00:00"), t_f.strftime("%Y-%m-%d 23:59:59")], tickformat="%d/%m/%Y", dtick=86400000, title="Fecha Operativa", tickfont=dict(size=12, color='#666'), gridcolor='rgba(0,0,0,0.05)', showline=True, linewidth=1, linecolor='rgba(0,0,0,0.2)', automargin=True)
                        
                        altura_dinamica = max(250, len(orden_eje_y) * 85)
                        fig.update_layout(height=altura_dinamica, margin=dict(l=250, r=30, t=60, b=80), plot_bgcolor='white', paper_bgcolor='white', legend_title_text='', legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), hoverlabel=dict(bgcolor="white", font_size=13, font_family="Arial"))
                        st.plotly_chart(fig, use_container_width=True)
                        
                        html_string = fig.to_html(include_plotlyjs='cdn')
                        b64 = base64.b64encode(html_string.encode('utf-8')).decode()
                        st.markdown(f'<a href="data:text/html;base64,{b64}" download="Cronograma_Gantt.html" style="display: inline-block; padding: 0.5em 1em; background-color: #003366; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; margin-top: 10px;">📥 Descargar Gantt Interactivo (HTML)</a>', unsafe_allow_html=True)
                    else:
                        st.info("No hay actividades programadas en la ventana de tiempo seleccionada.")
                else:
                    st.info("Aún no hay actividades reales programadas para este proyecto. Use el panel superior para asignar fechas.")

    # === MÓDULO 4: KPIS ===
    with tab4:
        st.header("Análisis de Datos y Control Financiero")
        nvs_all = obtener_nvs()
        if not nvs_all: st.warning("No hay proyectos.")
        else:
            h_raw = supabase.table("hitos_facturacion").select("*").execute().data
            df_h = pd.DataFrame(h_raw) if h_raw else pd.DataFrame(columns=["id", "id_nv", "mes", "anio", "porcentaje", "monto", "estado"])
            
            with st.expander("➕ REGISTRAR GASTO OPERATIVO (Siempre en CLP)"):
                st.info(f"💡 Los gastos se ingresan en Pesos Chilenos (CLP). Si la NV es en dólares, el sistema lo convertirá usando la tasa actual (1 USD = ${tasa_cambio} CLP).")
                with st.form("form_gastos"):
                    c_g1, c_g2, c_g3, c_g4 = st.columns(4)
                    nv_g = c_g1.selectbox("Proyecto", [n['id_nv'] for n in obtener_nvs("Abierta")])
                    t_g = c_g2.selectbox("Ítem", ["Rendigastos", "Viático", "Hospedaje", "Pasajes", "Insumos"])
                    m_g = c_g3.number_input("Monto (CLP)", min_value=0)
                    f_g = c_g4.date_input("Fecha")
                    if st.form_submit_button("Guardar Gasto"): 
                        try:
                            supabase.table("control_gastos").insert({"id_nv": nv_g, "tipo_gasto": t_g, "monto_gasto": m_g, "fecha_gasto": str(f_g)}).execute()
                            st.success("✅ Gasto registrado en la base de datos."); st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error al guardar el gasto: {e}")

            df_nv = pd.DataFrame(nvs_all)
            g_raw = supabase.table("control_gastos").select("*").execute().data
            df_g_agg = pd.DataFrame(g_raw).groupby('id_nv')['monto_gasto'].sum().reset_index() if g_raw else pd.DataFrame(columns=['id_nv', 'monto_gasto'])
            
            asig_all_raw = supabase.table("asignaciones_personal").select("*").execute().data
            df_ausencias = pd.DataFrame([a for a in asig_all_raw if a['id_nv'] == 'AUSENCIA']) if asig_all_raw else pd.DataFrame()
            
            df_nv_all_acts = pd.DataFrame([a for a in asig_all_raw if a['id_nv'] not in ['AUSENCIA', 'INTERNO']]) if asig_all_raw else pd.DataFrame()
            
            if not df_nv_all_acts.empty:
                # Días ejecutados: excluir SIN_PROGRAMAR y DESCANSO
                df_eje = df_nv_all_acts[~df_nv_all_acts['comentarios'].isin(['SIN_PROGRAMAR', 'DESCANSO'])].copy()
                if not df_eje.empty:
                    df_eje['hd'] = pd.to_numeric(df_eje['horas_diarias'], errors='coerce').fillna(9.0)
                    df_eje.loc[df_eje['hd'] <= 0, 'hd'] = 9.0
                    df_eje['d_eje'] = pd.to_numeric(df_eje['hh_asignadas'], errors='coerce').fillna(0) / df_eje['hd']
                    df_hh_agg = df_eje.groupby('id_nv')['d_eje'].sum().reset_index()
                else:
                    df_hh_agg = pd.DataFrame(columns=['id_nv', 'd_eje'])
                    
                # Avance: excluir PROYECCION_GLOBAL (incluir SIN_PROGRAMAR para promediar a 0 si no se ha hecho)
                df_prog_base = df_nv_all_acts[df_nv_all_acts['actividad_ssee'] != 'PROYECCION_GLOBAL'].copy()
                if not df_prog_base.empty:
                    df_p = df_prog_base.groupby(['id_nv', 'actividad_ssee'])['progreso'].max().reset_index()
                    df_p = df_p.groupby('id_nv')['progreso'].mean().reset_index()
                else:
                    df_p = pd.DataFrame(columns=['id_nv', 'progreso'])
                    
                df_hh_agg = df_hh_agg.merge(df_p, on='id_nv', how='outer').rename(columns={'progreso': 'Avance_%'})
                df_hh_agg['d_eje'] = df_hh_agg['d_eje'].fillna(0)
                df_hh_agg['Avance_%'] = df_hh_agg['Avance_%'].fillna(0)
            else: 
                df_hh_agg = pd.DataFrame(columns=['id_nv', 'd_eje', 'Avance_%'])
            
            df_k = df_nv.merge(df_g_agg, on='id_nv', how='left').merge(df_hh_agg, on='id_nv', how='left').fillna(0)
            df_k['Proyecto_Label'] = df_k['id_nv'] + " (" + df_k['cliente'] + ")"
            df_k['monto_facturado_hitos'] = df_k['id_nv'].map(df_h[df_h['estado']=='Facturada'].groupby('id_nv')['monto'].sum()).fillna(0)
            df_k['monto_pendiente'] = df_k.apply(lambda r: max(0, r['monto_vendido'] - r['monto_facturado_hitos']) if r['estado'] != 'Cerrada' else 0, axis=1)
            df_k['monto_gasto_ajustado'] = df_k.apply(lambda r: r['monto_gasto']/tasa_cambio if r['moneda']=='USD' else r['monto_gasto'], axis=1)
            df_k['Margen'] = df_k['monto_vendido'] - df_k['monto_gasto_ajustado']

            df_all_valid = pd.DataFrame([a for a in asig_all_raw if a['id_nv'] not in ['AUSENCIA', 'INTERNO'] and a['comentarios'] not in ['SIN_PROGRAMAR', 'DESCANSO']]) if asig_all_raw else pd.DataFrame()
            año_act, mes_act = datetime.today().year, datetime.today().month
            lista_anios = list(range(año_act - 2, año_act + 2))
            
            c_f1, c_f2 = st.columns(2)
            m_sel = c_f1.selectbox("Filtro Maestro - Mes:", list(MESES_ES.values()), index=mes_act-1)
            a_sel = c_f2.selectbox("Filtro Maestro - Año:", lista_anios, index=lista_anios.index(año_act))
            m_num = list(MESES_ES.keys())[list(MESES_ES.values()).index(m_sel)]
            f_i_m, f_f_m = datetime(a_sel, m_num, 1).date(), datetime(a_sel, m_num, calendar.monthrange(a_sel, m_num)[1]).date()

            t_g, t_i, t_o, t_h, t_t, t_pa, t_p, t_f = st.tabs([
                "🌍 Global Mensual", "🔍 Análisis Individual", "👥 Ocupación Personal", 
                "📅 Historial y Trazabilidad", "📋 Tabla y Facturación", "⏳ Pendientes (Backlog)", 
                "📈 Proyección Anual", "✅ Historial Facturado"
            ])

            with t_g:
                st.subheader(f"Visión Operativa Mensual ({m_sel} {a_sel})")
                d_hab_m = sum(1 for i in range((f_f_m - f_i_m).days + 1) if (f_i_m + timedelta(days=i)).weekday() < 5 and (f_i_m + timedelta(days=i)).strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026)
                
                dias_ausencia_mes = 0
                if not df_ausencias.empty:
                    for _, row_aus in df_ausencias.iterrows():
                        d_ini, d_fin = pd.to_datetime(row_aus['fecha_inicio']).date(), pd.to_datetime(row_aus['fecha_fin']).date()
                        c_date, e_date = max(d_ini, f_i_m), min(d_fin, f_f_m)
                        while c_date <= e_date:
                            if c_date.weekday() < 5 and c_date.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026: dias_ausencia_mes += 1
                            c_date += timedelta(days=1)
                
                c_neta = int((d_hab_m * len(ESPECIALISTAS)) - dias_ausencia_mes)
                
                dias_planificados = set()
                dias_reales = set()
                
                hoy = datetime.today().date()
                if not df_all_valid.empty:
                    for _, a in df_all_valid.iterrows():
                        try:
                            fi, ff = pd.to_datetime(a['fecha_inicio']).date(), pd.to_datetime(a['fecha_fin']).date()
                        except: continue
                        
                        esp = a.get('especialista')
                        if not esp or esp not in ESPECIALISTAS: continue
                            
                        os_d, oe = max(fi, f_i_m), min(ff, f_f_m)
                        if os_d <= oe:
                            inc = 'EXTRAS' in str(a.get('comentarios', '')).upper()
                            curr = os_d
                            while curr <= oe:
                                if inc or (curr.weekday() < 5 and curr.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026):
                                    if a.get('actividad_ssee') == 'PROYECCION_GLOBAL':
                                        dias_planificados.add((curr, esp))
                                    else:
                                        if curr <= hoy:
                                            dias_reales.add((curr, esp))
                                curr += timedelta(days=1)
                                
                tot_p = len(dias_planificados)
                tot_e = len(dias_reales)
                
                c1, c2 = st.columns(2)
                c1.metric("Cartera Ofertada Consolidada", f"USD ${sum(r['monto_vendido'] if r['moneda']=='USD' else r['monto_vendido']/tasa_cambio for _,r in df_k.iterrows()):,.2f}")
                c2.metric("Ejecución de Gasto Acumulado (USD)", f"USD ${sum(r['monto_gasto'] for _,r in df_g_agg.iterrows())/tasa_cambio:,.2f}")
                
                st.markdown("<br>", unsafe_allow_html=True)
                cg1, cg2 = st.columns(2)
                with cg1:
                    fig_t = go.Figure()
                    fig_t.add_trace(go.Bar(name='Planificado (Matriz Semanal)', x=['Desempeño Operativo'], y=[tot_p], marker_color='#3498DB', text=[f"{tot_p} Días Planificados" if tot_p > 0 else ""], textposition='auto', textfont=dict(weight='bold')))
                    fig_t.add_trace(go.Bar(name='Ejecutado Real (Carta Gantt)', x=['Desempeño Operativo'], y=[tot_e], marker_color='#2ECC71', text=[f"{tot_e} Días Reales" if tot_e > 0 else ""], textposition='auto', textfont=dict(weight='bold')))
                    fig_t.update_layout(
                        barmode='group', 
                        title=f"Planificado vs Real - {m_sel} {a_sel}", 
                        yaxis_title="Cantidad de Días-Hombre", 
                        plot_bgcolor='white', 
                        height=400,
                        margin=dict(l=20, r=20, t=60, b=80),
                        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5)
                    )
                    fig_t.add_hline(y=c_neta, line_dash="dash", line_color="#95A5A6", annotation_text=f"Capacidad Máx. Equipo ({c_neta} Días)", annotation_position="top right", annotation_font_color="#95A5A6", annotation_font_weight="bold")
                    fig_t.update_yaxes(range=[0, max([c_neta, tot_p, tot_e, 5]) * 1.2])
                    st.plotly_chart(fig_t, use_container_width=True)
                with cg2:
                    st.markdown(f"**Ranking de Avance Operativo (%) - {m_sel}**")
                    df_s = df_k[df_k['tipo_servicio'] == 'SSEE'].sort_values('Avance_%', ascending=False)
                    df_t = df_k[df_k['tipo_servicio'] == 'SE TERRENO'].sort_values('Avance_%', ascending=False)
                    
                    def render_ranking_table(df_sub, titulo):
                        if not df_sub.empty:
                            st.markdown(f"#### {titulo}")
                            df_show = df_sub[['Proyecto_Label', 'Avance_%']].copy()
                            df_show.rename(columns={'Proyecto_Label': 'Proyecto', 'Avance_%': 'Avance'}, inplace=True)
                            
                            def color_pct(val):
                                if val >= 100: color = '#2ECC71'
                                elif val >= 50: color = '#F39C12'
                                else: color = '#E74C3C'
                                return f'color: {color}; font-weight: bold;'
                            
                            st.dataframe(df_show.style.format({"Avance": "{:.1f}%"}).map(color_pct, subset=['Avance']), use_container_width=True, hide_index=True)
                        else:
                            st.info(f"No hay proyectos en {titulo} para este mes.")

                    render_ranking_table(df_s, "🔹 SSEE (Salas Eléctricas)")
                    render_ranking_table(df_t, "🔸 SE Terreno")

            with t_i:
                st.subheader("Buscador Analítico de Proyectos")
                nv_sel = st.selectbox("Escriba o Seleccione la Nota de Venta / Cliente:", df_k['Proyecto_Label'].tolist())
                if nv_sel:
                    r_nv = df_k[df_k['Proyecto_Label'] == nv_sel].iloc[0]
                    d_p_m, d_e_t, hoy = 0, 0, datetime.today().date()
                    df_acts_proyecto = pd.DataFrame()
                    
                    if asig_all_raw:
                        df_all_temp = pd.DataFrame(asig_all_raw)
                        
                        df_acts_matriz = df_all_temp[(df_all_temp['id_nv'] == r_nv['id_nv']) & (df_all_temp['actividad_ssee'] == 'PROYECCION_GLOBAL')]
                        if not df_acts_matriz.empty:
                            fechas_activas_matriz = set()
                            for _, row_act in df_acts_matriz.iterrows():
                                f_i = pd.to_datetime(row_act['fecha_inicio']).date()
                                f_f = pd.to_datetime(row_act['fecha_fin']).date()
                                inc = 'EXTRAS' in str(row_act.get('comentarios', '')).upper()
                                curr = f_i
                                while curr <= f_f:
                                    if f_i_m <= curr <= f_f_m: # Filtro Exacto del Mes Seleccionado
                                        if inc or (curr.weekday() < 5 and curr.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026):
                                            fechas_activas_matriz.add((curr, row_act.get('especialista')))
                                    curr += timedelta(days=1)
                            d_p_m = float(len(fechas_activas_matriz))

                        df_acts_proyecto = df_all_temp[(df_all_temp['id_nv'] == r_nv['id_nv']) & (df_all_temp['actividad_ssee'] != 'PROYECCION_GLOBAL') & (~df_all_temp['comentarios'].isin(['SIN_PROGRAMAR', 'DESCANSO']))]
                        if not df_acts_proyecto.empty:
                            fechas_activas_gantt = set()
                            for _, row_act in df_acts_proyecto.iterrows():
                                f_i = pd.to_datetime(row_act['fecha_inicio']).date()
                                f_f = pd.to_datetime(row_act['fecha_fin']).date()
                                inc = 'EXTRAS' in str(row_act.get('comentarios', '')).upper()
                                curr = f_i
                                while curr <= f_f:
                                    if f_i_m <= curr <= f_f_m and curr <= hoy: # Filtro Exacto del Mes y Solo hasta HOY
                                        if inc or (curr.weekday() < 5 and curr.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026):
                                            fechas_activas_gantt.add((curr, row_act.get('especialista'))) 
                                    curr += timedelta(days=1)
                            d_e_t = float(len(fechas_activas_gantt))
                    
                    estado_nv = r_nv['estado']
                    mon = r_nv['moneda']
                    fmt_v = f"{mon} ${r_nv['monto_vendido']:,.0f}".replace(",", ".") if mon == 'CLP' else f"{mon} ${r_nv['monto_vendido']:,.2f}"
                    fmt_g_clp = f"CLP ${df_g_agg.loc[df_g_agg['id_nv'] == r_nv['id_nv'], 'monto_gasto'].values[0] if not df_g_agg.loc[df_g_agg['id_nv'] == r_nv['id_nv']].empty else 0:,.0f}".replace(",", ".")
                    
                    st.markdown(f"**Estado del Proyecto:** `{'🟢 ABIERTA' if estado_nv == 'Abierta' else '🔴 CERRADA'}`")
                    
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    col_m1.metric("Presupuesto de Venta", fmt_v)
                    col_m2.metric("Total Gastos Operativos (CLP)", fmt_g_clp)
                    col_m3.metric("Avance Físico Total", f"{r_nv['Avance_%']:.1f}%")
                    col_m4.metric(f"Tiempos del Mes ({m_sel})", f"{d_e_t:.1f} Reales / {d_p_m:.1f} Plan", f"{(d_p_m - d_e_t):.1f} Días Restantes", delta_color="inverse" if (d_p_m - d_e_t) < 0 else "normal")

                    st.markdown("---")
                    
                    st.markdown("### 👨‍🔧 Equipo Técnico Participante")
                    if asig_all_raw:
                        df_equipo = pd.DataFrame(asig_all_raw)
                        df_equipo = df_equipo[(df_equipo['id_nv'] == r_nv['id_nv']) & (df_equipo['actividad_ssee'] != 'PROYECCION_GLOBAL') & (df_equipo['especialista'] != 'Sin Asignar')]
                        if not df_equipo.empty:
                            st.markdown("".join([f"<span class='especialista-pill'>{esp}</span>" for esp in df_equipo['especialista'].unique().tolist()]), unsafe_allow_html=True)
                        else: st.info("Aún no se han asignado especialistas reales a las actividades de este proyecto.")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    cg1, cg2 = st.columns([1, 1.5])
                    with cg1:
                        fig_b = go.Figure()
                        fig_b.add_trace(go.Bar(name='Planificado (Matriz)', x=['Tiempos del Proyecto'], y=[d_p_m], marker_color='#3498DB', text=[f"{d_p_m} Días Planificados" if d_p_m > 0 else ""], textposition='auto', textfont=dict(weight='bold')))
                        color_real = "#E74C3C" if d_e_t > d_p_m else "#2ECC71"
                        fig_b.add_trace(go.Bar(name='Real (Gantt)', x=['Tiempos del Proyecto'], y=[d_e_t], marker_color=color_real, text=[f"{d_e_t} Días Reales" if d_e_t > 0 else ""], textposition='auto', textfont=dict(weight='bold')))
                        fig_b.update_layout(
                            barmode='group', 
                            title=f"Balance Mensual: Planificado vs Real - {m_sel} {a_sel}", 
                            yaxis_title="Cantidad de Días-Hombre", 
                            plot_bgcolor='white', 
                            height=400, 
                            margin=dict(l=20, r=20, t=60, b=80), 
                            legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5)
                        )
                        fig_b.update_yaxes(range=[0, max([d_p_m, d_e_t, 2]) * 1.2])
                        st.plotly_chart(fig_b, use_container_width=True)

                        st.markdown("**📝 Comentarios y Detalles de Ejecución**")
                        if not df_acts_proyecto.empty:
                            df_comentarios = df_acts_proyecto.copy()
                            df_comentarios['actividad_ssee'] = df_comentarios['actividad_ssee'].fillna("Labor en Terreno")
                            comentarios_unicos = df_comentarios.groupby(['actividad_ssee', 'comentarios', 'justificacion']).agg({'progreso':'max', 'dias_extras':'max'}).reset_index()
                            for _, row_c in comentarios_unicos.iterrows():
                                act_name = row_c['actividad_ssee']
                                com_text = row_c['comentarios'].replace('_', ' ')
                                just = str(row_c['justificacion']).replace("[PAUSADA] ", "").replace("[PAUSADA]", "").strip()
                                
                                if "[PAUSADA]" in str(row_c['justificacion']).upper():
                                    st.info(f"**{act_name} ({int(row_c['progreso'])}%):** ⏸️ **PAUSADA** - Motivo: {just}")
                                elif row_c['dias_extras'] > 0:
                                    st.info(f"**{act_name} ({int(row_c['progreso'])}%):** Estado: {com_text} | ⚠️ **+{int(row_c['dias_extras'])} días extra** (Motivo: {just})")
                                else:
                                    st.info(f"**{act_name} ({int(row_c['progreso'])}%):** Estado: {com_text}")
                        else: st.write("No hay labores registradas.")

                    with cg2:
                        st.markdown("**Auditoría Detallada de Gastos Operativos**")
                        g_raw_nv = supabase.table("control_gastos").select("*").eq("id_nv", r_nv['id_nv']).execute().data
                        if g_raw_nv:
                            df_det = pd.DataFrame(g_raw_nv)[['fecha_gasto', 'tipo_gasto', 'monto_gasto']]
                            df_det.rename(columns={'fecha_gasto': 'Fecha', 'tipo_gasto': 'Ítem', 'monto_gasto': 'Monto (CLP)'}, inplace=True)
                            if mon == 'USD': df_det['Equivalente (USD)'] = df_det['Monto (CLP)'].apply(lambda x: f"USD ${(x / tasa_cambio):,.2f}")
                            df_det['Monto (CLP)'] = df_det['Monto (CLP)'].apply(lambda x: f"CLP ${x:,.0f}".replace(",", "."))
                            st.dataframe(df_det, use_container_width=True, hide_index=True)
                        else: st.info("Sin gastos registrados.")

            with t_o:
                st.subheader(f"👥 Ocupación de Personal - {m_sel} {a_sel}")
                st.info("Esta herramienta calcula la ocupación sobre el total de días calendario del mes. Para turnos 7x7 o 4x3, el período completo se considera ocupado ya que equivale al 100% de su productividad semanal.")
                f_oc = st.radio("Filtrar Análisis por Área:", ["🌐 Global (Total)", "⚡ SSEE", "👷 SE Terreno", "🏢 Oficina / Interno"], horizontal=True)
                dias_m = [f_i_m + timedelta(days=i) for i in range((f_f_m - f_i_m).days + 1)]
                tot_d_m = len(dias_m)
                mapa_ts = {n['id_nv']: n['tipo_servicio'] for n in nvs_all} if nvs_all else {}
                mapa_ts.update({'INTERNO': 'INTERNO', 'AUSENCIA': 'AUSENCIA'})
                
                dat_oc = []
                for esp in ESPECIALISTAS:
                    ds, dt, di, da = set(), set(), set(), set()
                    dias_turno = set()
                    for a in [x for x in asig_all_raw if x.get('especialista')==esp and x.get('comentarios')!='SIN_PROGRAMAR'] if asig_all_raw else []:
                        try: fi, ff = pd.to_datetime(a['fecha_inicio']).date(), pd.to_datetime(a['fecha_fin']).date()
                        except: continue
                        ts = mapa_ts.get(a.get('id_nv'))
                        inc = 'EXTRAS' in str(a.get('comentarios','')).upper()
                        es_desc = a.get('comentarios') == 'DESCANSO'
                        curr, end_curr = max(fi, f_i_m), min(ff, f_f_m)
                        while curr <= end_curr:
                            if inc or es_desc:
                                dias_turno.add(curr)
                            if inc or es_desc or (curr.weekday() < 5 and curr.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026):
                                if ts == 'AUSENCIA': da.add(curr)
                                elif ts == 'INTERNO': di.add(curr)
                                elif ts == 'SSEE': ds.add(curr)
                                elif ts == 'SE TERRENO': dt.add(curr)
                            curr += timedelta(days=1)
                            
                    ds, dt, di = ds - da, dt - da, di - da
                    d_graf = len(ds) if f_oc=="⚡ SSEE" else (len(dt) if f_oc=="👷 SE Terreno" else (len(di) if f_oc=="🏢 Oficina / Interno" else len(ds|dt|di)))
                    
                    base_personal = 0
                    for d in dias_m:
                        if d in dias_turno:
                            base_personal += 1
                        elif d.weekday() < 5 and d.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026:
                            base_personal += 1
                    
                    dat_oc.append({
                        "Especialista": esp, "Trabajados": d_graf, "Días SSEE": len(ds), "Días SE Terreno": len(dt), 
                        "Días Oficina": len(di), "Días Ausente": len(da), "Disponibles": max(0, base_personal - d_graf), 
                        "%": round((d_graf/base_personal*100) if base_personal>0 else 0, 1)
                    })
                
                df_oc = pd.DataFrame(dat_oc).sort_values("%", ascending=False)
                fig_oc = px.bar(df_oc, x="Especialista", y=["Trabajados", "Disponibles"], title=f"Distribución de Tiempos por Técnico - {m_sel} {a_sel} ({f_oc})", color_discrete_map={"Trabajados": "#3498DB", "Disponibles": "#2ECC71"})
                fig_oc.update_layout(yaxis_title="Cantidad de Días (Base Personalizada)", plot_bgcolor='white', barmode='stack', legend_title_text="Estado")
                st.plotly_chart(fig_oc, use_container_width=True)
                
                st.markdown("**Tabla General Detallada (Todas las Métricas)**")
                df_oc['% Ocupación Real'] = df_oc['%'].apply(lambda x: f"{x:.1f}%")
                st.dataframe(df_oc.drop(columns=['Trabajados', '%']), use_container_width=True, hide_index=True)

            with t_h:
                st.subheader("📅 Historial de Ejecución y Trazabilidad")
                nv_h = st.selectbox("Proyecto Historial:", df_k['Proyecto_Label'].tolist())
                if nv_h and asig_all_raw:
                    df_h_r = pd.DataFrame([a for a in asig_all_raw if a['id_nv'] == df_k[df_k['Proyecto_Label']==nv_h].iloc[0]['id_nv'] and a['actividad_ssee']!='PROYECCION_GLOBAL' and a['comentarios'] != 'SIN_PROGRAMAR'])
                    if not df_h_r.empty:
                        df_h_r['hd'] = pd.to_numeric(df_h_r['horas_diarias'], errors='coerce').fillna(9.0)
                        df_h_r['hd'] = df_h_r['hd'].apply(lambda x: 9.0 if x <= 0 else x)
                        df_h_r['dh'] = pd.to_numeric(df_h_r['hh_asignadas'], errors='coerce').fillna(0) / df_h_r['hd']
                        grp = df_h_r.groupby(['actividad_ssee', 'fecha_inicio', 'fecha_fin', 'justificacion', 'progreso']).agg({'especialista': lambda x: ", ".join(set(x)), 'dh': 'sum'}).reset_index()
                        grp['Estado'] = grp.apply(lambda r: "⏸️ PAUSADA" if "[PAUSADA]" in str(r['justificacion']).upper() else ("✅ COMPLETADO" if r['progreso']>=100 else "▶️ EJECUTADO"), axis=1)
                        grp['dh'] = grp['dh'].apply(lambda x: f"{x:.1f} Días")
                        grp.rename(columns={'actividad_ssee': 'Labor / Actividad', 'fecha_inicio': 'Fecha Inicio', 'fecha_fin': 'Fecha Fin', 'progreso': 'Avance (%)', 'justificacion': 'Comentario', 'especialista': 'Personal', 'dh': 'Días'}, inplace=True)
                        st.dataframe(grp[['Labor / Actividad', 'Fecha Inicio', 'Fecha Fin', 'Estado', 'Avance (%)', 'Días', 'Personal', 'Comentario']].sort_values(by=['Labor / Actividad', 'Fecha Inicio']), use_container_width=True, hide_index=True)
                    else: st.write("No hay historial real registrado para este proyecto.")

            with t_t:
                st.markdown(f"### 💸 Pronóstico de Facturación Activa para {m_sel} {a_sel}")
                df_hm = df_h[(df_h['mes']==m_num) & (df_h['anio']==a_sel)].copy()
                if not df_hm.empty: df_hm = df_hm.merge(df_k[['id_nv', 'cliente', 'tipo_servicio', 'moneda', 'monto_pendiente']], on='id_nv', how='left')
                else: df_hm = pd.DataFrame(columns=['id', 'id_nv', 'cliente', 'tipo_servicio', 'moneda', 'porcentaje', 'monto', 'estado'])
                
                n_filas = []
                if not df_all_valid.empty:
                    df_mf = df_all_valid.groupby('id_nv')['fecha_fin'].max().reset_index()
                    df_mf['fecha_fin'] = pd.to_datetime(df_mf['fecha_fin']).dt.date
                    for _, r in df_k.merge(df_mf, on='id_nv', how='inner').iterrows():
                        if pd.to_datetime(r['fecha_fin']).month == m_num and pd.to_datetime(r['fecha_fin']).year == a_sel and r['monto_pendiente'] > 0 and r['estado_facturacion'] != 'Facturada' and df_h[df_h['id_nv']==r['id_nv']].empty:
                            n_filas.append({'id': 'Auto', 'id_nv': r['id_nv'], 'cliente': r['cliente'], 'tipo_servicio': r['tipo_servicio'], 'moneda': r['moneda'], 'porcentaje': 100, 'monto': r['monto_pendiente'], 'estado': 'Pronóstico Automático'})
                
                df_hm = pd.concat([df_hm, pd.DataFrame(n_filas)], ignore_index=True) if n_filas else df_hm
                if not df_hm.empty:
                    df_hm['usd'] = df_hm.apply(lambda r: r['monto'] if r['moneda']=='USD' else r['monto']/tasa_cambio, axis=1)
                    tot_usd = df_hm['usd'].sum()
                    
                    st.markdown("#### 🌟 Resumen Global del Mes")
                    c_met1, c_met2 = st.columns(2)
                    c_met1.metric("Total Pronosticado Global (USD)", f"USD ${tot_usd:,.2f}")
                    c_met2.metric("Total Pronosticado Global (CLP)", f"CLP ${(tot_usd * tasa_cambio):,.0f}".replace(",", "."))
                    st.divider()
                    
                    def show_table_serv(df_sub, tit):
                        if df_sub.empty: return
                        st.markdown(f"#### {tit}")
                        s_usd = df_sub['usd'].sum()
                        df_show = df_sub[['id', 'id_nv', 'cliente', 'moneda', 'porcentaje', 'monto', 'estado']].copy()
                        df_show['porcentaje'] = df_show['porcentaje'].apply(lambda x: f"{x:.1f}%")
                        df_show = pd.concat([df_show, pd.DataFrame([{'id': '', 'id_nv': 'TOTALES', 'cliente': '', 'moneda': 'USD / CLP', 'porcentaje': '', 'monto': f"USD ${s_usd:,.2f} / CLP ${(s_usd*tasa_cambio):,.0f}".replace(",", "."), 'estado': ''}])], ignore_index=True)
                        df_show['monto'] = df_show.apply(lambda x: x['monto'] if isinstance(x['monto'], str) else (f"USD ${x['monto']:,.2f}" if x['moneda']=='USD' else f"CLP ${x['monto']:,.0f}".replace(",", ".")), axis=1)
                        df_show.rename(columns={'id_nv':'NV', 'cliente':'Cliente', 'moneda':'Moneda', 'porcentaje':'% Calculado', 'monto':'Monto Parcial', 'estado':'Estado Factura'}, inplace=True)
                        st.dataframe(df_show.drop(columns=['id']).style.apply(lambda r: ['background-color: #003366; color: white; font-weight: bold']*len(r) if r['NV']=='TOTALES' else (['background-color: #E8F8F5; font-style: italic']*len(r) if 'Auto' in str(r['Estado Factura']) else ['']*len(r)), axis=1), use_container_width=True, hide_index=True)

                    show_table_serv(df_hm[df_hm['tipo_servicio'] == 'SSEE'], "🔹 Facturación SSEE (Salas Eléctricas)")
                    show_table_serv(df_hm[df_hm['tipo_servicio'] == 'SE TERRENO'], "🔸 Facturación SE TERRENO (Faenas)")
                    
                    with st.expander("🔄 Actualizar Estado de Factura"):
                        h_real = df_hm[df_hm['id'].astype(str).str.isnumeric()]
                        if not h_real.empty:
                            c_up1, c_up2 = st.columns([2, 1])
                            
                            hitos_dict = {}
                            for _, r in h_real.iterrows():
                                mon = r.get('moneda', 'CLP')
                                mto = float(r.get('monto', 0))
                                try: pct = float(str(r.get('porcentaje', 0)).replace('%', ''))
                                except: pct = 0.0
                                
                                monto_fmt = f"{mon} ${mto:,.0f}".replace(",", ".") if mon == 'CLP' else f"{mon} ${mto:,.2f}"
                                lbl = f"NV: {r['id_nv']} | Cobro: {pct:.1f}% | {monto_fmt}"
                                hitos_dict[lbl] = {"id": r['id'], "id_nv": r['id_nv']}
                            
                            sel_hito_lbl = c_up1.selectbox("Seleccione la Parcialidad (Hito) a Actualizar:", list(hitos_dict.keys()))
                            nuevo_est_h = c_up2.selectbox("Nuevo Estado:", ["Pendiente", "Facturada", "Postergada"])
                            
                            if st.button("Actualizar Hito y Proyecto", use_container_width=True):
                                hito_selec = hitos_dict[sel_hito_lbl]
                                h_id = hito_selec["id"]
                                h_nv = hito_selec["id_nv"]
                                
                                supabase.table("hitos_facturacion").update({"estado": nuevo_est_h}).eq("id", h_id).execute()
                                
                                if nuevo_est_h == "Facturada":
                                    supabase.table("notas_venta").update({"estado": "Cerrada", "estado_facturacion": "Facturada"}).eq("id_nv", h_nv).execute()
                                    st.success(f"✅ Factura actualizada. La Nota de Venta '{h_nv}' se ha cerrado automáticamente.")
                                else:
                                    st.success("✅ Estado del hito actualizado.")
                                st.rerun()
                        else: st.info("Los pronósticos automáticos se volverán facturas reales cuando crees sus hitos manualmente abajo.")
                else: st.write("No hay parcialidades de facturación programadas para este mes.")
                
                st.divider()
                st.markdown("### ⚙️ Administrar Parcialidades por Proyecto")
                nv_h_sel = st.selectbox("Proyecto a planificar:", df_k['Proyecto_Label'].tolist())
                if nv_h_sel:
                    r_ph = df_k[df_k['Proyecto_Label']==nv_h_sel].iloc[0]
                    rest = r_ph['monto_vendido'] - df_h[df_h['id_nv']==r_ph['id_nv']]['monto'].sum()
                    st.write(f"**Total Proyecto:** {r_ph['moneda']} ${r_ph['monto_vendido']:,.0f} | **Restante:** {r_ph['moneda']} ${rest:,.0f}")
                    
                    df_hnv = df_h[df_h['id_nv'] == r_ph['id_nv']]
                    if not df_hnv.empty:
                        df_s = df_hnv[['id', 'mes', 'anio', 'porcentaje', 'monto', 'estado']].copy()
                        df_s['mes'] = df_s['mes'].apply(lambda x: MESES_ES.get(x, x))
                        df_s['porcentaje'] = df_s['porcentaje'].apply(lambda x: f"{x:.1f}%")
                        df_s['monto'] = df_s['monto'].apply(lambda x: f"USD ${x:,.2f}" if r_ph['moneda']=='USD' else f"CLP ${x:,.0f}".replace(",", "."))
                        st.dataframe(df_s, use_container_width=True, hide_index=True)
                        
                        cd1, cd2 = st.columns(2)
                        with cd1:
                            with st.form("fd"):
                                if st.form_submit_button("🗑️ Eliminar Solo Este Hito"):
                                    supabase.table("hitos_facturacion").delete().eq("id", st.selectbox("ID a eliminar", df_s['id'].tolist())).execute()
                                    st.success("Eliminado."); st.rerun()
                        with cd2:
                            st.write(""); st.write("")
                            if st.button("🗑️ Borrar TODOS los hitos", type="secondary", use_container_width=True):
                                supabase.table("hitos_facturacion").delete().eq("id_nv", r_ph['id_nv']).execute(); st.rerun()

                    if rest > 0:
                        st.divider()
                        st.markdown("**Añadir nueva parcialidad:**")
                        modo = st.radio("Definir por:", ["Porcentaje del Saldo (%)", "Monto Exacto"], horizontal=True)
                        with st.form("form_add_hito"):
                            c_hm, c_ha, c_hp = st.columns(3)
                            h_mes = c_hm.selectbox("Mes", list(MESES_ES.values()))
                            h_anio = c_ha.selectbox("Año", lista_anios, index=lista_anios.index(año_act))
                            h_val = c_hp.number_input("Porcentaje (%)" if modo=="Porcentaje del Saldo (%)" else "Monto", min_value=0.1, value=100.0 if modo=="Porcentaje del Saldo (%)" else float(rest))
                            
                            if st.form_submit_button("Agregar Hito de Cobro", use_container_width=True):
                                m_c = (h_val/100.0)*rest if modo=="Porcentaje del Saldo (%)" else float(h_val)
                                if round(m_c, 2) > round(rest, 2): st.error("❌ Monto supera el saldo restante.")
                                elif m_c <= 0: st.error("❌ Monto debe ser mayor a 0.")
                                else:
                                    supabase.table("hitos_facturacion").insert({"id_nv": r_ph['id_nv'], "mes": list(MESES_ES.keys())[list(MESES_ES.values()).index(h_mes)], "anio": h_anio, "porcentaje": (m_c/r_ph['monto_vendido'])*100, "monto": m_c, "estado": "Pendiente"}).execute()
                                    st.success("✅ Agregado"); st.rerun()

            with t_pa:
                st.subheader("Servicios Pendientes (Backlog de Facturación)")
                df_pe = df_k[df_k['monto_pendiente'] > 0].copy()
                if not df_pe.empty:
                    df_pe['usd'] = df_pe.apply(lambda r: r['monto_pendiente'] if r['moneda']=='USD' else r['monto_pendiente']/tasa_cambio, axis=1)
                    
                    def show_b_log(df_sub, tit):
                        if df_sub.empty: return
                        st.markdown(f"#### {tit}")
                        tot_usd = df_sub['usd'].sum()
                        c1, c2 = st.columns(2)
                        c1.metric("Total Pendiente (USD)", f"USD ${tot_usd:,.2f}")
                        c2.metric("Total Pendiente (CLP)", f"CLP ${(tot_usd * tasa_cambio):,.0f}".replace(",", "."))
                        
                        df_s = df_sub[['id_nv', 'cliente', 'moneda', 'monto_vendido', 'monto_pendiente', 'estado_facturacion']].copy()
                        df_s = pd.concat([df_s, pd.DataFrame([{'id_nv': 'TOTALES', 'monto_pendiente': f"USD ${tot_usd:,.2f} / CLP ${(tot_usd*tasa_cambio):,.0f}".replace(",", ".") }])], ignore_index=True)
                        df_s['monto_vendido'] = df_s.apply(lambda x: "" if pd.isna(x['monto_vendido']) else (f"USD ${x['monto_vendido']:,.2f}" if x['moneda']=='USD' else f"CLP ${x['monto_vendido']:,.0f}".replace(",", ".")), axis=1)
                        df_s['monto_pendiente'] = df_s.apply(lambda x: x['monto_pendiente'] if isinstance(x['monto_pendiente'], str) else (f"USD ${x['monto_pendiente']:,.2f}" if x['moneda']=='USD' else f"CLP ${x['monto_pendiente']:,.0f}".replace(",", ".")), axis=1)
                        df_s.rename(columns={'id_nv':'NV', 'cliente':'Cliente', 'moneda':'Moneda', 'monto_vendido':'Ofertado Original', 'monto_pendiente':'Saldo Pendiente', 'estado_facturacion':'Estado'}, inplace=True)
                        st.dataframe(df_s.style.apply(lambda r: ['background-color: #003366; color: white; font-weight: bold']*len(r) if r['NV']=='TOTALES' else ['']*len(r), axis=1), use_container_width=True, hide_index=True)
                    
                    st.markdown("---")
                    show_b_log(df_pe, "🌟 Resumen Global (Todo el Backlog)")
                    st.divider()
                    show_b_log(df_pe[df_pe['tipo_servicio'] == 'SSEE'], "🔹 Backlog SSEE (Salas Eléctricas)")
                    show_b_log(df_pe[df_pe['tipo_servicio'] == 'SE TERRENO'], "🔸 Backlog SE TERRENO (Faenas)")
                else: st.success("✨ No hay servicios pendientes en el Backlog.")

            with t_p:
                st.subheader("📈 Proyección de Facturación Anual")
                hc = df_h.copy()
                if not hc.empty: hc = hc.merge(df_k[['id_nv', 'moneda']], on='id_nv', how='left')
                hc['clp'] = hc.apply(lambda r: r['monto'] if r['moneda']=='CLP' else r['monto']*tasa_cambio, axis=1) if not hc.empty else 0
                hc['Tipo'] = hc['estado'].apply(lambda x: 'Facturación Finalizada a la Fecha' if x=='Facturada' else 'Proyectado (Tentativo)') if not hc.empty else ''
                
                ar = []
                if not df_all_valid.empty:
                    mf = df_all_valid.groupby('id_nv')['fecha_fin'].max().reset_index()
                    for _, r in df_k.merge(mf, on='id_nv', how='inner').iterrows():
                        if r['monto_pendiente'] > 0 and r['estado_facturacion'] != 'Facturada' and df_h[df_h['id_nv']==r['id_nv']].empty:
                            ar.append({'mes': pd.to_datetime(r['fecha_fin']).month, 'anio': pd.to_datetime(r['fecha_fin']).year, 'clp': r['monto_pendiente'] if r['moneda']=='CLP' else r['monto_pendiente']*tasa_cambio, 'Tipo': 'Proyectado (Tentativo)'})
                
                cf = pd.concat([hc[['mes', 'anio', 'clp', 'Tipo']], pd.DataFrame(ar)], ignore_index=True) if ar else hc
                if not cf.empty:
                    cf['ord'] = cf.apply(lambda r: f"{int(r['anio'])}-{int(r['mes']):02d}", axis=1)
                    cf['ma'] = cf.apply(lambda r: f"{MESES_ES[int(r['mes'])]} {int(r['anio'])}", axis=1)
                    grp_c = cf.groupby(['ord', 'ma', 'Tipo'])['clp'].sum().reset_index().sort_values('ord')
                    
                    fig_p = px.bar(grp_c, x='ma', y='clp', color='Tipo', text='clp', color_discrete_map={'Facturación Finalizada a la Fecha': '#2ECC71', 'Proyectado (Tentativo)': '#3498DB'})
                    fig_p.add_hline(y=110000000, line_dash="dash", line_color="#FF6600", line_width=3, annotation_text="Meta Mensual ($110M CLP)", annotation_position="top left", annotation_font_size=16, annotation_font_color="#FF6600")
                    fig_p.update_traces(texttemplate='$%{text:,.0f}', textposition='inside', insidetextfont=dict(color='white', size=14, weight='bold'))
                    fig_p.update_layout(barmode='stack', yaxis_title="Monto (CLP)", xaxis_title="", plot_bgcolor='white', legend_title_text='Estado')
                    fig_p.update_xaxes(categoryorder='array', categoryarray=grp_c['ma'].unique())
                    st.plotly_chart(fig_p, use_container_width=True)
                    
                    df_pivot = grp_c.groupby(['ord', 'ma'])['clp'].sum().reset_index()
                    df_pivot['Monto Estimado (USD)'] = df_pivot['clp'].apply(lambda x: f"USD ${(x / tasa_cambio):,.2f}")
                    df_pivot['Monto Total (CLP)'] = df_pivot['clp'].apply(lambda x: f"CLP ${x:,.0f}".replace(",", "."))
                    st.dataframe(df_pivot[['ma', 'Monto Total (CLP)', 'Monto Estimado (USD)']].rename(columns={'ma':'Mes/Año'}), use_container_width=True, hide_index=True)

            with t_f:
                st.subheader("✅ Historial de Servicios Facturados")
                hf = df_h[df_h['estado']=='Facturada'].copy()
                if not hf.empty: 
                    hf = hf.merge(df_k[['id_nv', 'cliente', 'tipo_servicio', 'moneda']], on='id_nv', how='left').sort_values(by=['anio', 'mes'], ascending=[False, False])
                    hf['Periodo'] = hf['mes'].apply(lambda x: MESES_ES.get(int(x), str(x))) + " " + hf['anio'].astype(str)
                    
                    for p in hf['Periodo'].unique():
                        st.markdown(f"#### 📅 {p}")
                        df_per = hf[hf['Periodo'] == p].copy()
                        df_per['usd'] = df_per.apply(lambda r: r['monto'] if r['moneda']=='USD' else r['monto']/tasa_cambio, axis=1)
                        tot_usd = df_per['usd'].sum()
                        
                        c1, c2 = st.columns(2)
                        c1.metric(f"Total Facturado en {p} (USD)", f"USD ${tot_usd:,.2f}")
                        c2.metric(f"Total Facturado en {p} (CLP)", f"CLP ${(tot_usd * tasa_cambio):,.0f}".replace(",", "."))
                        
                        df_s = df_per[['id_nv', 'cliente', 'tipo_servicio', 'moneda', 'porcentaje', 'monto']].copy()
                        df_s['monto'] = df_s.apply(lambda x: f"USD ${x['monto']:,.2f}" if x['moneda']=='USD' else f"CLP ${x['monto']:,.0f}".replace(",", "."), axis=1)
                        df_s['porcentaje'] = df_s['porcentaje'].apply(lambda x: f"{x:.1f}%")
                        df_s.rename(columns={'id_nv':'NV', 'cliente':'Cliente', 'tipo_servicio':'Tipo', 'moneda':'Moneda', 'porcentaje':'% Cobrado', 'monto':'Monto Facturado'}, inplace=True)
                        st.dataframe(df_s, use_container_width=True, hide_index=True)
                        st.markdown("<hr style='margin: 10px 0; opacity: 0.3;'>", unsafe_allow_html=True)
                else: st.success("Aún no hay servicios marcados como facturados.")

    # === MÓDULO 5: CIERRE Y PDF ANALÍTICO ===
    with tab5:
        st.header("Cierre Técnico y Reporte")
        if 'pdf_bytes' not in st.session_state: st.session_state.pdf_bytes = None
        if 'nv_cerrada' not in st.session_state: st.session_state.nv_cerrada = None

        nvs_abiertas = obtener_nvs("Abierta")
        if nvs_abiertas:
            nv_c_label = st.selectbox("Proyecto para Cerrar", [f"{n['id_nv']} - {n['cliente']}" for n in nvs_abiertas])
            nv_c_id = nv_c_label.split(" - ")[0]

            if st.button("🔴 CERRAR Y GENERAR REPORTE PDF"):
                try:
                    info_nv = next(n for n in nvs_abiertas if n['id_nv'] == nv_c_id)
                    asig_list_raw = supabase.table("asignaciones_personal").select("*").eq("id_nv", nv_c_id).execute().data
                    
                    asig_list_prog = [a for a in asig_list_raw if a.get('actividad_ssee') != 'PROYECCION_GLOBAL'] if asig_list_raw else []
                    asig_list_hh = [a for a in asig_list_raw if a.get('actividad_ssee') != 'PROYECCION_GLOBAL' and a.get('comentarios') not in ['SIN_PROGRAMAR', 'DESCANSO']] if asig_list_raw else []
                    
                    gastos_list = supabase.table("control_gastos").select("*").eq("id_nv", nv_c_id).execute().data
                    
                    sum_hh = sum(a['hh_asignadas'] for a in asig_list_hh) if asig_list_hh else 0
                    dias_ejecutados = sum_hh / 9.0
                    sum_gas_bruto = sum(g['monto_gasto'] for g in gastos_list) if gastos_list else 0
                    
                    if asig_list_prog:
                        df_avances = pd.DataFrame(asig_list_prog)
                        avg_prog = df_avances.groupby('actividad_ssee')['progreso'].max().mean()
                    else:
                        avg_prog = 0
                        
                    moneda = info_nv.get('moneda', 'CLP')
                    dias_ofertados = info_nv.get('hh_vendidas', 0)
                    sum_gas_real = sum_gas_bruto / tasa_cambio if moneda == 'USD' else sum_gas_bruto

                    df_pdf = pd.DataFrame({"Concepto": ["Presupuesto", "Gasto Real"], "Monto": [info_nv['monto_vendido'], sum_gas_real]})
                    fig_pdf = px.bar(df_pdf, x="Concepto", y="Monto", color="Concepto", color_discrete_map={"Presupuesto": "#003366", "Gasto Real": "#FF6600"})
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                        fig_pdf.write_image(tmp.name, engine="kaleido")
                        path_img = tmp.name

                    # --- GENERACIÓN DEL PDF CON FPDF ---
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", 'B', 20)
                    pdf.set_text_color(0, 51, 102)
                    pdf.cell(0, 15, "REPORTE EJECUTIVO DE CIERRE - COORDINACION FPS", ln=True, align='C')
                    pdf.ln(5)
                    
                    fmt_v_pdf = f"{info_nv['monto_vendido']:,.0f}".replace(",", ".") if moneda == 'CLP' else f"{info_nv['monto_vendido']:,.2f}"
                    fmt_g_pdf = f"{sum_gas_real:,.0f}".replace(",", ".") if moneda == 'CLP' else f"{sum_gas_real:,.2f}"
                    
                    pdf.set_font("Arial", '', 12)
                    pdf.set_text_color(0, 0, 0)
                    pdf.cell(0, 10, f"Proyecto: {nv_c_id} | Cliente: {info_nv['cliente']}", ln=True)
                    pdf.cell(0, 10, f"Lugar: {info_nv['lugar']} | Avance Final: {avg_prog:.1f}%", ln=True)
                    pdf.cell(0, 10, f"Dias Ofertados: {dias_ofertados} | Dias Ejecutados (Aprox): {dias_ejecutados:.1f}", ln=True)
                    pdf.cell(0, 10, f"Finanzas: {moneda} ${fmt_v_pdf} Ofertado | {moneda} ${fmt_g_pdf} Gastado", ln=True)
                    
                    if moneda == 'USD':
                        pdf.set_font("Arial", 'I', 9)
                        pdf.cell(0, 5, f"(Nota: Gastos convertidos usando tasa de cambio de {tasa_cambio} CLP/USD)", ln=True)
                    
                    pdf.image(path_img, x=25, y=pdf.get_y()+5, w=160)
                    
                    pdf.add_page()
                    pdf.set_font("Arial", 'B', 14)
                    pdf.cell(0, 10, "DETALLE DE OPERACIONES EJECUTADAS", ln=True)
                    pdf.set_font("Arial", '', 10)
                    
                    if asig_list_prog:
                        for act, group in df_avances.groupby('actividad_ssee'):
                            prog = group['progreso'].max()
                            esp_list = ", ".join([e for e in group['especialista'].unique() if e != "Sin Asignar"])
                            if not esp_list: esp_list = "Sin Asignar"
                            linea = f"> {act} ({prog}%) | Tecnicos: {esp_list}"
                            # Reemplazar caracteres especiales conflictivos
                            linea = linea.encode('latin-1', 'replace').decode('latin-1')
                            pdf.cell(0, 8, linea, ln=True)
                    else:
                        pdf.cell(0, 8, "No se registraron labores operativas en terreno.", ln=True)
                    
                    st.session_state.pdf_bytes = pdf.output(dest='S').encode('latin-1', 'replace')
                    st.session_state.nv_cerrada = nv_c_id
                    os.remove(path_img)
                    
                    supabase.table("notas_venta").update({"estado":"Cerrada", "estado_facturacion":"Facturada"}).eq("id_nv", nv_c_id).execute()
                    st.success("✅ Proyecto cerrado exitosamente y marcado para facturación final.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Ocurrió un error procesando el cierre: {e}")

        if st.session_state.pdf_bytes:
            st.download_button(
                label=f"⬇️ Descargar Reporte {st.session_state.nv_cerrada}", 
                data=st.session_state.pdf_bytes, 
                file_name=f"Reporte_Cierre_{st.session_state.nv_cerrada}.pdf", 
                mime="application/pdf"
            )

# --- CONTROLADOR DE VISTAS ---
if not st.session_state.authenticated: 
    login_screen()
else: 
    main_app()
