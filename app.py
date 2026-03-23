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

# --- FUNCIONES AUXILIARES CORREGIDAS ---
def calcular_fecha_fin_dinamica(f_ini, dias_totales, incluye_finde):
    if dias_totales <= 0:
        return f_ini
        
    dias_contados = 0
    fecha_actual = f_ini
    
    while dias_contados < dias_totales:
        es_feriado = fecha_actual.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
        es_finde = fecha_actual.weekday() >= 5
        
        if not incluye_finde:
            if not es_finde and not es_feriado:
                dias_contados += 1
        else:
            dias_contados += 1
            
        if dias_contados < dias_totales:
            fecha_actual += timedelta(days=1)
            
    return fecha_actual

def calcular_hh_ssee(f_ini, f_fin, incluye_finde=False, horas_diarias=None):
    hh = 0
    if f_fin < f_ini: 
        return 0
        
    dias_tot = (f_fin - f_ini).days + 1
    
    for i in range(dias_tot):
        fecha_actual = f_ini + timedelta(days=i)
        dia_semana = fecha_actual.weekday()
        str_fecha = fecha_actual.strftime("%d-%m-%Y")
        
        es_feriado = str_fecha in FERIADOS_CHILE_2026
        es_finde = dia_semana >= 5
        
        if not incluye_finde and (es_finde or es_feriado):
            continue 
            
        if horas_diarias is not None and horas_diarias > 0:
            hh += horas_diarias
        else:
            if dia_semana < 4: 
                hh += 9.5
            elif dia_semana == 4: 
                hh += 8.5
            else: 
                hh += 9.5 
            
    return hh

def obtener_nvs(estado_filter=None):
    # Excluir explícitamente AUSENCIA e INTERNO para análisis y Gantt
    query = supabase.table("notas_venta").select("*").neq("id_nv", "AUSENCIA").neq("id_nv", "INTERNO")
    if estado_filter: query = query.eq("estado", estado_filter)
    return query.execute().data

# --- CONTROL DE SESIÓN ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'user_email' not in st.session_state:
    st.session_state.user_email = ""
if 'form_key_comercial' not in st.session_state:
    st.session_state.form_key_comercial = 0

def logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    st.session_state.authenticated = False
    st.session_state.user_email = ""

def login_screen():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.markdown("<div class='login-container'>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align: center; color: #E6007E;'>🔐 Acceso Coordinación FPS</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: gray;'>Por favor ingrese sus credenciales autorizadas.</p>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            email = st.text_input("Correo Electrónico", placeholder="usuario@empresa.com")
            password = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button("Ingresar al Sistema", use_container_width=True)
            
            if submit:
                if email and password:
                    try:
                        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                        if response.session:
                            st.session_state.authenticated = True
                            st.session_state.user_email = email
                            st.rerun()
                    except Exception as e:
                        st.error("Credenciales inválidas o usuario no registrado.")
                else:
                    st.warning("Debe completar todos los campos.")
        st.markdown("</div>", unsafe_allow_html=True)

# --- APLICACIÓN PRINCIPAL ---
def main_app():
    # --- BARRA LATERAL ---
    st.sidebar.markdown("""
        <div style='text-align: center; padding: 15px 0; background-color: white; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-left: 6px solid #E6007E;'>
            <h2 style='margin: 0; font-size: 1.4em; font-family: "Arial Black", sans-serif; font-weight: 900; letter-spacing: 1px; line-height: 1.1;'>
                <span style='color: #E6007E;'>COORDINACIÓN</span><br>
                <span style='color: #00AEEF;'>FPS</span>
            </h2>
        </div>
    """, unsafe_allow_html=True)
    
    st.sidebar.markdown(f"<p style='text-align:center; font-size:0.9em;'>👤 <b>Usuario:</b> {st.session_state.user_email}</p>", unsafe_allow_html=True)
    st.sidebar.button("🚪 Cerrar Sesión", on_click=logout, use_container_width=True)
    st.sidebar.divider()
    st.sidebar.header("⚙️ Configuración Global")
    st.sidebar.info("Ajuste los parámetros económicos para el análisis de datos.")
    tasa_cambio = st.sidebar.number_input("Valor del Dólar (CLP)", min_value=1.0, value=950.0, step=1.0, help="Tasa de cambio usada para convertir los gastos en CLP a proyectos facturados en USD.")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📝 1. Comercial", 
        "🗓️ 2. Matriz Semanal", 
        "⚙️ 3. Ejecución y Gantt", 
        "💰 4. Gastos y KPIs",
        "📄 5. Cierre y Reporte PDF"
    ])

    # ==========================================
    # MÓDULO 1: COMERCIAL
    # ==========================================
    with tab1:
        st.header("Gestión Comercial (Presupuesto)")
        
        col_form, col_admin = st.columns([2, 1])
        
        with col_form:
            if 'nv_pending' not in st.session_state:
                st.session_state.nv_pending = None
            if 'nv_conflicts' not in st.session_state:
                st.session_state.nv_conflicts = []

            if st.session_state.nv_pending is not None:
                st.warning("⚠️ **Cruces de Fechas Detectados**")
                st.write("Se encontraron las siguientes asignaciones previas que chocan con las fechas seleccionadas para la nueva Nota de Venta:")
                for conf in st.session_state.nv_conflicts:
                    st.write(f"- 👨‍🔧 **{conf['especialista']}** ya está asignado a **{conf['id_nv']}** ({conf['actividad_ssee']}) del {conf['fecha_inicio']} al {conf['fecha_fin']}.")
                    
                decision = st.radio("¿Cómo desea proceder con los especialistas en conflicto?", 
                                    ["Mantener en ambos servicios (Permitir solapamiento de fechas)", 
                                     "Quitar de los servicios anteriores (Dejar asignado solo en esta nueva NV)"])
                                     
                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    if st.button("✅ Confirmar y Guardar Nota de Venta", use_container_width=True):
                        try:
                            payload = st.session_state.nv_pending
                            
                            supabase.table("notas_venta").insert({
                                "id_nv": payload["id_nv"], "cliente": payload["cliente"], "tipo_servicio": payload["tipo_servicio"], 
                                "lugar": payload["lugar"], "moneda": payload["moneda"], "monto_vendido": payload["monto_vendido"], 
                                "hh_vendidas": payload["hh_vendidas"], "estado": "Abierta"
                            }).execute()
                            
                            if "Quitar" in decision:
                                for conf in st.session_state.nv_conflicts:
                                    supabase.table("asignaciones_personal").delete().eq("id", conf['id']).execute()
                            
                            for esp in payload["especialistas_sel"]:
                                p_asig = {
                                    "id_nv": payload["id_nv"], 
                                    "especialista": esp, 
                                    "fecha_inicio": str(payload["f_ini"]), 
                                    "fecha_fin": str(payload["f_f"]), 
                                    "hh_asignadas": 0, 
                                    "actividad_ssee": "PROYECCION_GLOBAL", 
                                    "comentarios": "EXTRAS" if payload["es_continuo"] else "LIBRES", 
                                    "progreso": 0,
                                    "hora_inicio_t": payload["h_inicio_val"],
                                    "hora_fin_t": payload["h_fin_val"],
                                    "horas_diarias": payload["h_diarias_val"]
                                }
                                safe_insert_asignacion(p_asig)
                                
                            st.session_state.nv_pending = None
                            st.session_state.nv_conflicts = []
                            st.session_state.form_key_comercial += 1
                            st.success(f"✅ NV {payload['id_nv']} guardada y Matriz Semanal actualizada.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ocurrió un error al guardar: {e}")
                            
                with c_btn2:
                    if st.button("❌ Cancelar Creación", type="secondary", use_container_width=True):
                        st.session_state.nv_pending = None
                        st.session_state.nv_conflicts = []
                        st.rerun()
                        
            else:
                col_t1, col_t2 = st.columns([3, 1])
                with col_t1:
                    st.subheader("Crear Nueva Nota de Venta")
                with col_t2:
                    if st.button("🔄 Nueva / Limpiar", use_container_width=True):
                        st.session_state.form_key_comercial += 1
                        st.rerun()

                with st.form(key=f"form_comercial_{st.session_state.form_key_comercial}"):
                    c1, c2, c3 = st.columns(3)
                    
                    id_nv_base = c1.text_input("ID Nota de Venta base")
                    item_nv = c1.text_input("Ítem / Fase (Opcional)", help="Para separar una misma NV en entregables/facturas distintas. Ej: 'Item 1'. El sistema guardará el registro como 'NV - Item'.")
                    
                    cliente = c2.text_input("Cliente")
                    tipo = c2.selectbox("Tipo de Servicio", ["SSEE", "SE TERRENO"])
                    
                    lugar = c3.text_input("Lugar / Faena")
                    col_mon, col_mnt = c3.columns([1, 2])
                    moneda = col_mon.selectbox("Moneda", ["CLP", "USD"])
                    
                    if moneda == "CLP":
                        monto_str = col_mnt.text_input("Monto Ofertado (De este ítem)", value="", placeholder="Ej: 14.538.342")
                    else:
                        monto_usd = col_mnt.number_input("Monto Ofertado (De este ítem)", min_value=0.0, step=0.01, format="%.2f")
                    
                    st.divider()
                    st.markdown("### Proyección en Matriz Semanal (Opcional)")
                    st.info("Ingresa los días de duración del servicio. Si ya conoces la fecha de inicio y cuadrilla, puedes establecerla ahora para enviarla a la Matriz Semanal y cruzar los datos.")
                    
                    if tipo == "SE TERRENO":
                        st.markdown("#### 🕒 Horarios Especiales de Terreno")
                        c_th1, c_th2, c_th3 = st.columns(3)
                        h_inicio_val = c_th1.time_input("Hora de Inicio", value=datetime.strptime('08:00', '%H:%M').time())
                        h_fin_val = c_th2.time_input("Hora de Fin", value=datetime.strptime('17:30', '%H:%M').time())
                        h_diarias_val = c_th3.number_input("Horas a imputar por día", value=9.5, step=0.5)
                    else:
                        h_inicio_val = None
                        h_fin_val = None
                        h_diarias_val = None
                    
                    c4, c5, c6 = st.columns(3)
                    dias_v = c4.number_input("Días Vendidos (Duración)", min_value=0.0, step=1.0)
                    f_ini = c5.date_input("Fecha de Inicio (Dejar vacío si no aplica)", format="DD/MM/YYYY", value=None)
                    especialistas_sel = c6.multiselect("Especialistas Reservados", ESPECIALISTAS)
                    incluye_finde = st.radio("¿Considerar fines de semana en esta proyección?", ["No (Saltar Sáb/Dom)", "Sí (Días continuos)"], horizontal=True)

                    if st.form_submit_button("Guardar Nota de Venta", use_container_width=True):
                        id_nv = f"{id_nv_base.strip()} - {item_nv.strip()}" if item_nv.strip() else id_nv_base.strip()
                        
                        if moneda == "CLP":
                            m_clean = str(monto_str).replace(".", "").replace(",", "").strip()
                            monto = float(m_clean) if m_clean.isdigit() else 0.0
                        else:
                            monto = monto_usd
                        
                        if id_nv and cliente:
                            try:
                                verificacion = supabase.table("notas_venta").select("id_nv").eq("id_nv", id_nv).execute()
                                if len(verificacion.data) > 0:
                                    st.warning(f"⚠️ El registro '{id_nv}' ya se encuentra en el sistema. Cambie el número de Ítem.")
                                else:
                                    if especialistas_sel and dias_v > 0 and f_ini is not None:
                                        es_continuo = incluye_finde == "Sí (Días continuos)"
                                        f_f = calcular_fecha_fin_dinamica(f_ini, dias_v, es_continuo)
                                        
                                        asig_existentes = supabase.table("asignaciones_personal").select("*").in_("especialista", especialistas_sel).execute().data
                                        conflictos = []
                                        for a in asig_existentes:
                                            a_ini = pd.to_datetime(a['fecha_inicio']).date()
                                            a_fin = pd.to_datetime(a['fecha_fin']).date()
                                            if f_ini <= a_fin and f_f >= a_ini:
                                                conflictos.append(a)
                                                
                                        if conflictos:
                                            st.session_state.nv_pending = {
                                                "id_nv": id_nv, "cliente": cliente, "tipo_servicio": tipo, 
                                                "lugar": lugar, "moneda": moneda, "monto_vendido": monto, 
                                                "hh_vendidas": dias_v, "estado": "Abierta",
                                                "especialistas_sel": especialistas_sel, "f_ini": f_ini, "f_f": f_f,
                                                "es_continuo": es_continuo,
                                                "h_inicio_val": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00',
                                                "h_fin_val": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30',
                                                "h_diarias_val": h_diarias_val if h_diarias_val else 0
                                            }
                                            st.session_state.nv_conflicts = conflictos
                                            st.rerun()
                                        else:
                                            supabase.table("notas_venta").insert({
                                                "id_nv": id_nv, "cliente": cliente, "tipo_servicio": tipo, 
                                                "lugar": lugar, "moneda": moneda, "monto_vendido": monto, 
                                                "hh_vendidas": dias_v, "estado": "Abierta"
                                            }).execute()
                                            
                                            for esp in especialistas_sel:
                                                p_asig = {
                                                    "id_nv": id_nv, 
                                                    "especialista": esp, 
                                                    "fecha_inicio": str(f_ini), 
                                                    "fecha_fin": str(f_f), 
                                                    "hh_asignadas": 0, 
                                                    "actividad_ssee": "PROYECCION_GLOBAL", 
                                                    "comentarios": "EXTRAS" if es_continuo else "LIBRES", 
                                                    "progreso": 0,
                                                    "hora_inicio_t": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00',
                                                    "hora_fin_t": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30',
                                                    "horas_diarias": h_diarias_val if h_diarias_val else 0
                                                }
                                                safe_insert_asignacion(p_asig)
                                                
                                            st.success(f"✅ Registro {id_nv} guardado exitosamente.")
                                            st.session_state.form_key_comercial += 1
                                            st.rerun()
                                    else:
                                        supabase.table("notas_venta").insert({
                                            "id_nv": id_nv, "cliente": cliente, "tipo_servicio": tipo, 
                                            "lugar": lugar, "moneda": moneda, "monto_vendido": monto, 
                                            "hh_vendidas": dias_v, "estado": "Abierta"
                                        }).execute()
                                        st.success(f"✅ Registro {id_nv} guardado exitosamente.")
                                        st.session_state.form_key_comercial += 1
                                        st.rerun()
                            except Exception as e:
                                st.error(f"❌ Ocurrió un error al guardar en la base de datos: {e}")
                        else:
                            st.warning("⚠️ Debe ingresar un ID y Cliente válidos.")
        
        with col_admin:
            st.subheader("Administración y Edición")
            
            nvs_admin = obtener_nvs()
            if nvs_admin:
                opciones_admin = {f"{n['id_nv']} - {n['cliente']}": n for n in nvs_admin}
                
                tab_edit, tab_del = st.tabs(["✏️ Editar", "🗑️ Eliminar"])
                
                with tab_edit:
                    st.info("Modifique los datos de un proyecto existente.")
                    nv_a_editar_label = st.selectbox("Seleccione Proyecto a Editar", list(opciones_admin.keys()), key="sel_edit_nv")
                    nv_data = opciones_admin[nv_a_editar_label]
                    
                    with st.form("form_edit_nv"):
                        st.text_input("ID Nota de Venta (No editable)", value=nv_data['id_nv'], disabled=True)
                        new_cliente = st.text_input("Cliente", value=nv_data['cliente'])
                        new_tipo = st.selectbox("Tipo de Servicio", ["SSEE", "SE TERRENO"], index=0 if nv_data['tipo_servicio'] == 'SSEE' else 1)
                        new_lugar = st.text_input("Lugar / Faena", value=nv_data.get('lugar', ''))
                        
                        c_mon_e, c_mnt_e = st.columns([1, 2])
                        new_moneda = c_mon_e.selectbox("Moneda", ["CLP", "USD"], index=0 if nv_data.get('moneda', 'CLP') == 'CLP' else 1)
                        
                        if new_moneda == "CLP":
                            monto_actual_str = f"{int(nv_data.get('monto_vendido', 0))}" 
                            new_monto_str = c_mnt_e.text_input("Monto Ofertado", value=monto_actual_str, help="Puede usar puntos para miles.")
                        else:
                            monto_actual_flt = float(nv_data.get('monto_vendido', 0.0))
                            new_monto_usd = c_mnt_e.number_input("Monto Ofertado", min_value=0.0, step=0.01, value=monto_actual_flt, format="%.2f")

                        if st.form_submit_button("Actualizar Proyecto", use_container_width=True):
                            if new_moneda == "CLP":
                                m_clean = str(new_monto_str).replace(".", "").replace(",", "").strip()
                                final_monto = float(m_clean) if m_clean.isdigit() else 0.0
                            else:
                                final_monto = new_monto_usd
                                
                            try:
                                supabase.table("notas_venta").update({
                                    "cliente": new_cliente,
                                    "tipo_servicio": new_tipo,
                                    "lugar": new_lugar,
                                    "moneda": new_moneda,
                                    "monto_vendido": final_monto
                                }).eq("id_nv", nv_data['id_nv']).execute()
                                st.success(f"✅ Proyecto {nv_data['id_nv']} actualizado exitosamente.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al actualizar: {e}")
                                
                with tab_del:
                    st.info("Elimine irreversiblemente un proyecto y todos sus datos asociados.")
                    nv_a_borrar_label = st.selectbox("Seleccione Proyecto a Eliminar", list(opciones_admin.keys()), key="sel_del_nv")
                    id_a_borrar = opciones_admin[nv_a_borrar_label]['id_nv']
                    
                    confirmacion_borrado = st.checkbox(f"Estoy seguro que deseo eliminar {nv_a_borrar_label}")
                    
                    if st.button("🗑️ Eliminar Proyecto Definitivamente", type="secondary"):
                        if confirmacion_borrado:
                            try:
                                supabase.table("notas_venta").delete().eq("id_nv", id_a_borrar).execute()
                                st.success(f"✅ Proyecto {id_a_borrar} eliminado del sistema.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al intentar eliminar el proyecto: {e}")
                        else:
                            st.warning("Debe confirmar marcando la casilla antes de eliminar.")
            else:
                st.write("No hay proyectos registrados.")

    # ==========================================
    # MÓDULO 2: MATRIZ DE PROYECCIÓN
    # ==========================================
    with tab2:
        st.header("Matriz de Recursos (Proyección Global)")
        
        nvs_activas_comercial = [n for n in obtener_nvs("Abierta") if n['id_nv'] != "INTERNO"]
        if nvs_activas_comercial:
            dict_nvs_label = {f"{n['id_nv']} - {n['cliente']}": n for n in nvs_activas_comercial}
            
            st.markdown("### ⚙️ Panel de Asignación y Disponibilidad")
            col_exp1, col_exp2, col_exp3 = st.columns(3)
            
            with col_exp1:
                with st.expander("💼 Proyección Comercial", expanded=False):
                    tab_proy1, tab_proy2 = st.tabs(["Asignar Proyección", "Eliminar Proyección"])
                    
                    with tab_proy1:
                        with st.form("form_proyeccion"):
                            nv_label_sel = st.selectbox("Proyecto (NV - Cliente)", list(dict_nvs_label.keys()), key="proy_nv")
                            nv_data_sel = dict_nvs_label[nv_label_sel]
                            
                            dias_defecto = float(nv_data_sel.get('hh_vendidas', 5.0))
                            especialistas_sel = st.multiselect("Especialistas Reservados", ESPECIALISTAS, key="proy_esp")
                            
                            if nv_data_sel.get('tipo_servicio') == 'SE TERRENO':
                                st.markdown("#### 🕒 Horarios Especiales de Terreno")
                                c_t1, c_t2, c_t3 = st.columns(3)
                                h_inicio_val = c_t1.time_input("Hora de Inicio", value=datetime.strptime('08:00', '%H:%M').time())
                                h_fin_val = c_t2.time_input("Hora de Fin", value=datetime.strptime('17:30', '%H:%M').time())
                                h_diarias_val = c_t3.number_input("Horas a imputar por día", value=9.5, step=0.5)
                            else:
                                h_inicio_val = None
                                h_fin_val = None
                                h_diarias_val = None
                            
                            c_f1, c_f2 = st.columns(2)
                            f_ini = c_f1.date_input("Fecha de Inicio", format="DD/MM/YYYY", key="proy_ini")
                            
                            val_dias_db = float(nv_data_sel.get('hh_vendidas', 5.0))
                            val_min_seguro = val_dias_db if val_dias_db >= 1.0 else 1.0
                            
                            dias_proy = c_f2.number_input("Días totales", min_value=1.0, value=val_min_seguro, key="proy_dias")
                            
                            incluye_finde = st.radio("¿Considerar fin de semana?", ["No (Saltar Sáb/Dom)", "Sí (Días continuos)"], index=0, key="proy_finde")
                            
                            if st.form_submit_button("Guardar Proyección", use_container_width=True):
                                try:
                                    supabase.table("asignaciones_personal").delete().eq("id_nv", nv_data_sel['id_nv']).eq("actividad_ssee", "PROYECCION_GLOBAL").execute()
                                    es_continuo = incluye_finde == "Sí (Días continuos)"
                                    f_f = calcular_fecha_fin_dinamica(f_ini, dias_proy, es_continuo)
                                    for esp in especialistas_sel:
                                        p_asig = {
                                            "id_nv": nv_data_sel['id_nv'], 
                                            "especialista": esp, 
                                            "fecha_inicio": str(f_ini), 
                                            "fecha_fin": str(f_f), 
                                            "hh_asignadas": 0, 
                                            "actividad_ssee": "PROYECCION_GLOBAL", 
                                            "comentarios": "EXTRAS" if es_continuo else "LIBRES", 
                                            "progreso": 0,
                                            "hora_inicio_t": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00',
                                            "hora_fin_t": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30',
                                            "horas_diarias": h_diarias_val if h_diarias_val else 0
                                        }
                                        safe_insert_asignacion(p_asig)
                                    st.success("✅ Proyección actualizada en la Matriz correctamente.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Error al guardar proyección: {e}")
                                    
                    with tab_proy2:
                        proy_raw = supabase.table("asignaciones_personal").select("*").eq("actividad_ssee", "PROYECCION_GLOBAL").execute().data
                        if proy_raw:
                            df_proy_borrar = pd.DataFrame(proy_raw)
                            opciones_proy_borrar = {}
                            for _, row in df_proy_borrar.iterrows():
                                etiqueta = f"{row['especialista']} | {row['id_nv']} | {row['fecha_inicio']} a {row['fecha_fin']}"
                                opciones_proy_borrar[etiqueta] = row['id']
                                
                            proy_seleccionada = st.selectbox("Seleccione proyección a eliminar", list(opciones_proy_borrar.keys()))
                            if st.button("🗑️ Eliminar Proyección"):
                                try:
                                    id_proy = opciones_proy_borrar[proy_seleccionada]
                                    supabase.table("asignaciones_personal").delete().eq("id", id_proy).execute()
                                    st.success("✅ Proyección eliminada exitosamente. Se ha liberado al especialista en la Matriz.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al eliminar la proyección: {e}")
                        else:
                            st.write("No hay proyecciones comerciales asignadas actualmente.")

            with col_exp2:
                with st.expander("🏢 Labores Internas (Taller/Oficina)", expanded=False):
                    tab_int1, tab_int2 = st.tabs(["Asignar Labor", "Gestionar Activas"])
                    
                    with tab_int1:
                        with st.form("form_internas"):
                            esp_int = st.multiselect("Especialista(s)", ESPECIALISTAS, key="int_esp")
                            tipo_int = st.selectbox("Tipo de Labor", [
                                "Informe de Visita Técnica",
                                "Trabajos en Nave FPS (Taller)",
                                "Carga de Cilindros",
                                "Cursos y Capacitación",
                                "Trabajo Administrativo",
                                "Otro"
                            ])
                            desc_int = st.text_input("Descripción adicional (Opcional)")
                            
                            c_d1, c_d2 = st.columns(2)
                            f_ini_int = c_d1.date_input("Fecha Inicio", format="DD/MM/YYYY", key="int_ini")
                            f_fin_int = c_d2.date_input("Fecha Fin", format="DD/MM/YYYY", key="int_fin")
                            
                            if st.form_submit_button("Guardar Labor Interna", use_container_width=True):
                                if esp_int and f_ini_int <= f_fin_int:
                                    try:
                                        act_nombre = f"{tipo_int}" + (f" - {desc_int}" if desc_int else "")
                                        hh_final = calcular_hh_ssee(f_ini_int, f_fin_int, incluye_finde=False)
                                        for esp in esp_int:
                                            p_asig = {
                                                "id_nv": "INTERNO", 
                                                "especialista": esp, 
                                                "fecha_inicio": str(f_ini_int), 
                                                "fecha_fin": str(f_fin_int), 
                                                "hh_asignadas": hh_final, 
                                                "actividad_ssee": act_nombre, 
                                                "comentarios": "LIBRES", 
                                                "progreso": 100,
                                                "hora_inicio_t": "08:00",
                                                "hora_fin_t": "17:30",
                                                "horas_diarias": 9.5
                                            }
                                            safe_insert_asignacion(p_asig)
                                        st.success("✅ Labor interna registrada. Aparecerá en la Matriz.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"❌ Error al registrar labor: {e}")
                                else:
                                    st.error("⚠️ Seleccione especialistas y asegúrese de que las fechas sean correctas.")
                    
                    with tab_int2:
                        internas_raw = supabase.table("asignaciones_personal").select("*").eq("id_nv", "INTERNO").execute().data
                        if internas_raw:
                            df_int_borrar = pd.DataFrame(internas_raw)
                            opciones_int_borrar = {}
                            for _, row in df_int_borrar.iterrows():
                                etiqueta = f"{row['especialista']} | {row['actividad_ssee']} | {row['fecha_inicio']}"
                                opciones_int_borrar[etiqueta] = row['id']
                                
                            int_seleccionada = st.selectbox("Seleccione labor a eliminar", list(opciones_int_borrar.keys()))
                            if st.button("🗑️ Eliminar Labor Interna"):
                                try:
                                    id_ausencia = opciones_int_borrar[int_seleccionada]
                                    supabase.table("asignaciones_personal").delete().eq("id", id_ausencia).execute()
                                    st.success("✅ Labor eliminada exitosamente.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al eliminar: {e}")
                        else:
                            st.write("No hay labores internas registradas en el sistema.")

            with col_exp3:
                with st.expander("🌴 Ausencias (Vacaciones/Faltas)", expanded=False):
                    tab_rrhh1, tab_rrhh2 = st.tabs(["Ingresar Ausencia", "Cancelar Ausencia"])
                    
                    with tab_rrhh1:
                        with st.form("form_ausencia"):
                            esp_ausencia = st.multiselect("Especialista(s)", ESPECIALISTAS, key="aus_esp")
                            tipo_ausencia = st.selectbox("Tipo de Ausencia", ["Vacaciones", "Permiso Administrativo", "Licencia Médica", "Falta Injustificada"])
                            
                            c_a1, c_a2 = st.columns(2)
                            f_ini_aus = c_a1.date_input("Fecha Inicio", format="DD/MM/YYYY", key="aus_ini")
                            f_fin_aus = c_a2.date_input("Fecha Fin", format="DD/MM/YYYY", key="aus_fin")
                            
                            comentario_aus = st.text_input("Detalle / Motivo (Opcional)")
                            
                            if st.form_submit_button("Registrar Ausencia en RRHH", use_container_width=True):
                                if esp_ausencia and f_ini_aus <= f_fin_aus:
                                    try:
                                        hh_final = calcular_hh_ssee(f_ini_aus, f_fin_aus, incluye_finde=False)
                                        for esp in esp_ausencia:
                                            p_asig = {
                                                "id_nv": "AUSENCIA", 
                                                "especialista": esp, 
                                                "fecha_inicio": str(f_ini_aus), 
                                                "fecha_fin": str(f_fin_aus), 
                                                "hh_asignadas": hh_final, 
                                                "actividad_ssee": f"{tipo_ausencia}" + (f" - {comentario_aus}" if comentario_aus else ""), 
                                                "comentarios": "LIBRES", 
                                                "progreso": 100 
                                            }
                                            safe_insert_asignacion(p_asig)
                                        st.success("✅ Ausencia registrada. Se descontará de la capacidad neta del mes.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"❌ Error al registrar ausencia: {e}")
                                else:
                                    st.error("⚠️ Verifique los especialistas y que la fecha de inicio no sea mayor a la final.")
                    
                    with tab_rrhh2:
                        ausencias_raw = supabase.table("asignaciones_personal").select("*").eq("id_nv", "AUSENCIA").execute().data
                        if ausencias_raw:
                            df_aus_borrar = pd.DataFrame(ausencias_raw)
                            opciones_aus_borrar = {}
                            for _, row in df_aus_borrar.iterrows():
                                etiqueta = f"{row['especialista']} | {row['actividad_ssee']} | {row['fecha_inicio']} a {row['fecha_fin']}"
                                opciones_aus_borrar[etiqueta] = row['id']
                                
                            ausencia_seleccionada = st.selectbox("Seleccione el registro a eliminar", list(opciones_aus_borrar.keys()))
                            if st.button("🗑️ Eliminar Ausencia Seleccionada"):
                                try:
                                    id_ausencia = opciones_aus_borrar[ausencia_seleccionada]
                                    supabase.table("asignaciones_personal").delete().eq("id", id_ausencia).execute()
                                    st.success("✅ Ausencia eliminada. Se ha restaurado la capacidad operativa.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al eliminar la ausencia: {e}")
                        else:
                            st.write("No hay ausencias registradas actualmente.")
                        
        st.divider()
        
        col_start, col_days = st.columns(2)
        fecha_base_matriz = col_start.date_input("📅 Fecha de inicio de la matriz (Puedes elegir fechas pasadas)", value=datetime.today().date(), key="inicio_matriz")
        dias_a_mostrar = col_days.slider("Días a visualizar hacia adelante", 1, 60, 14) 
        
        fechas_rango = [fecha_base_matriz + timedelta(days=i) for i in range(dias_a_mostrar)]
        nombres_columnas_internos = [d.strftime("%d-%m-%Y") for d in fechas_rango]
        nombres_columnas_display = [f"{DIAS_ES[d.weekday()]} {d.strftime('%d/%m')}" for d in fechas_rango]
        
        matriz_final = pd.DataFrame(index=ESPECIALISTAS, columns=nombres_columnas_internos)
        
        for col in nombres_columnas_internos:
            fecha_obj = datetime.strptime(col, "%d-%m-%Y").date()
            matriz_final[col] = "⌛ No Hábil" if (fecha_obj.weekday() >= 5 or col in FERIADOS_CHILE_2026) else "🟢 Disponible"
            
        asig_raw = supabase.table("asignaciones_personal").select("*").execute().data
        
        nvs_todas = obtener_nvs()
        mapa_clientes = {n['id_nv']: n['cliente'] for n in nvs_todas} if nvs_todas else {}

        if asig_raw:
            for a in asig_raw:
                try: 
                    f_i = pd.to_datetime(a['fecha_inicio']).date()
                    f_f = pd.to_datetime(a['fecha_fin']).date()
                except: continue
                
                if a['id_nv'] == 'AUSENCIA':
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        if d in fechas_rango:
                            col = d.strftime("%d-%m-%Y")
                            etiqueta = f"🌴 {a['actividad_ssee']}"
                            matriz_final.at[a['especialista'], col] = etiqueta
                
                elif a['id_nv'] == 'INTERNO':
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        es_feriado = d.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
                        es_finde = d.weekday() >= 5
                        if not (es_finde or es_feriado):
                            if d in fechas_rango:
                                col = d.strftime("%d-%m-%Y")
                                valor_actual = str(matriz_final.at[a['especialista'], col])
                                if '🌴' not in valor_actual:
                                    etiqueta = f"🏢 {a['actividad_ssee']}"
                                    if valor_actual in ["🟢 Disponible", "⌛ No Hábil"]: 
                                        matriz_final.at[a['especialista'], col] = etiqueta
                                    elif etiqueta not in valor_actual: 
                                        matriz_final.at[a['especialista'], col] += f" + {etiqueta}"
                
                elif a.get('actividad_ssee') == 'PROYECCION_GLOBAL':
                    trabajo_continuo = (a.get('comentarios') == 'EXTRAS')
                    cliente_nombre = mapa_clientes.get(a['id_nv'], 'Proyectado')
                    
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        es_feriado = d.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
                        es_finde = d.weekday() >= 5
                        
                        if not trabajo_continuo and (es_finde or es_feriado):
                            continue
                            
                        if d in fechas_rango:
                            col = d.strftime("%d-%m-%Y")
                            valor_actual = str(matriz_final.at[a['especialista'], col])
                            
                            if '🌴' not in valor_actual:
                                etiqueta = f"{a['id_nv']} [{cliente_nombre}]"
                                if valor_actual in ["🟢 Disponible", "⌛ No Hábil"]: 
                                    matriz_final.at[a['especialista'], col] = etiqueta
                                elif etiqueta not in valor_actual: 
                                    matriz_final.at[a['especialista'], col] += f" + {etiqueta}"
        
        matriz_final.columns = nombres_columnas_display
        
        def style_matrix(x):
            texto = str(x)
            if 'No Hábil' in texto: return 'background-color: #F0F0F0; color: #A0A0A0'
            if '🌴' in texto: return 'background-color: #FADBD8; color: #C0392B; font-weight: bold'
            if '🏢' in texto: return 'background-color: #D6EAF8; color: #21618C; font-weight: bold'
            if 'Disponible' in texto: return 'background-color: #E6F2FF; color: #003366'
            return 'background-color: #D5F5E3; color: #196F3D; font-weight: bold'
            
        st.dataframe(matriz_final.style.map(style_matrix), use_container_width=True, height=550)

    # ==========================================
    # MÓDULO 3: EJECUCIÓN Y CRONOGRAMA GRUPAL
    # ==========================================
    with tab3:
        st.header("Ejecución: Alcance, Programación Viva y Gantt")
        nvs_activas = obtener_nvs("Abierta")
        nv_id_sel = None
        
        if nvs_activas:
            dict_nvs_label = {f"{n['id_nv']} - {n['cliente']}": n for n in nvs_activas}
            
            c_asig, c_prog = st.columns([1, 1.5])
            
            with c_asig:
                st.subheader("1. Alcance del Proyecto")
                st.info("Gestione las labores que componen este proyecto. Puede agregar nuevas o eliminar las existentes.")
                nv_label_sel = st.selectbox("Proyecto (NV - Cliente)", list(dict_nvs_label.keys()))
                nv_data_sel = dict_nvs_label[nv_label_sel]
                nv_id_sel = nv_data_sel['id_nv']
                
                tab_alc_add, tab_alc_del = st.tabs(["➕ Añadir Labor", "🗑️ Eliminar Labor"])
                
                with tab_alc_add:
                    with st.form("form_alcance"):
                        if nv_data_sel['tipo_servicio'] == "SSEE":
                            actividades_sel = st.multiselect("Agregar Actividades al Alcance", list(ABREVIATURAS.keys()))
                        else:
                            act_custom = st.text_input("Nombre de la Actividad en Terreno")
                            actividades_sel = [act_custom] if act_custom else []
                        
                        if st.form_submit_button("Añadir al Alcance"):
                            if actividades_sel:
                                try:
                                    existing = supabase.table("asignaciones_personal").select("actividad_ssee").eq("id_nv", nv_id_sel).execute().data
                                    existing_acts = [e['actividad_ssee'] for e in existing if e['actividad_ssee'] != 'PROYECCION_GLOBAL']
                                    
                                    agregadas = 0
                                    for act in actividades_sel:
                                        if act not in existing_acts:
                                            p_asig = {
                                                "id_nv": nv_id_sel, 
                                                "especialista": "Sin Asignar", 
                                                "fecha_inicio": str(datetime.today().date()), 
                                                "fecha_fin": str(datetime.today().date()), 
                                                "hh_asignadas": 0, 
                                                "actividad_ssee": act, 
                                                "comentarios": "SIN_PROGRAMAR", 
                                                "progreso": 0,
                                                "hora_inicio_t": '08:00',
                                                "hora_fin_t": '17:30',
                                                "horas_diarias": 0
                                            }
                                            safe_insert_asignacion(p_asig)
                                            agregadas += 1
                                    
                                    if agregadas > 0:
                                        st.success(f"✅ {agregadas} actividades añadidas a la bolsa de ajuste.")
                                        st.rerun()
                                    else:
                                        st.warning("⚠️ Las actividades seleccionadas ya existen en el alcance.")
                                except Exception as e:
                                    st.error(f"❌ Error al añadir labores: {e}")
                                    
                with tab_alc_del:
                    existing_for_del = supabase.table("asignaciones_personal").select("actividad_ssee").eq("id_nv", nv_id_sel).neq("actividad_ssee", "PROYECCION_GLOBAL").execute().data
                    if existing_for_del:
                        unique_acts = list(set([e['actividad_ssee'] for e in existing_for_del]))
                        with st.form("form_del_alcance"):
                            act_to_delete = st.selectbox("Seleccione la Labor a Eliminar", unique_acts)
                            st.warning("⚠️ Cuidado: Esto borrará todo el historial, tiempos y avance de esta labor de la base de datos.")
                            if st.form_submit_button("🗑️ Eliminar Labor Definitivamente"):
                                try:
                                    supabase.table("asignaciones_personal").delete().eq("id_nv", nv_id_sel).eq("actividad_ssee", act_to_delete).execute()
                                    st.success(f"✅ Labor '{act_to_delete}' eliminada exitosamente.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Error al eliminar labor: {e}")
                    else:
                        st.info("No hay labores asignadas a este proyecto.")

            with c_prog:
                st.subheader("2. Programación Viva y Avances")
                st.write("Ajuste fechas, asigne cuadrillas y modifique el avance en tiempo real.")
                
                asig_all_raw = supabase.table("asignaciones_personal").select("*").eq("id_nv", nv_id_sel).execute().data
                
                especialistas_matriz = []
                if asig_all_raw:
                    especialistas_matriz = list(set([x['especialista'] for x in asig_all_raw if x.get('actividad_ssee') == 'PROYECCION_GLOBAL' and x.get('especialista') != 'Sin Asignar']))
                
                if asig_all_raw:
                    df_temp = pd.DataFrame(asig_all_raw)
                    df_temp = df_temp[df_temp['actividad_ssee'] != 'PROYECCION_GLOBAL']
                    
                    if not df_temp.empty:
                        df_temp['key_grupo'] = df_temp['actividad_ssee'].fillna("General")
                        actividades_unicas = df_temp['key_grupo'].unique()
                        
                        if nv_data_sel['tipo_servicio'] == "SSEE":
                            suma_progreso = df_temp.groupby('key_grupo')['progreso'].max().sum()
                            avance_total = suma_progreso / len(ABREVIATURAS)
                        else:
                            avance_total = df_temp.groupby('key_grupo')['progreso'].max().mean()
                            
                        st.markdown(f"**Avance Total del Proyecto: {avance_total:.1f}%**")
                        st.progress(int(avance_total))
                        st.markdown("---")
                        
                        hoy = datetime.today().date()
                        
                        for act in actividades_unicas:
                            df_act_raw = df_temp[df_temp['key_grupo'] == act].copy()
                            df_act_raw['fecha_inicio_dt'] = pd.to_datetime(df_act_raw['fecha_inicio'])
                            
                            latest_start = df_act_raw['fecha_inicio_dt'].max()
                            df_latest = df_act_raw[df_act_raw['fecha_inicio_dt'] == latest_start]
                            
                            curr_prog = int(df_latest['progreso'].max())
                            
                            just_series = df_latest['justificacion'].dropna()
                            existing_just_raw = str(just_series.iloc[0]) if not just_series.empty else ""
                            is_paused = "[PAUSADA]" in existing_just_raw.upper()
                            existing_just_display = existing_just_raw.replace("[PAUSADA]", "").replace("[PAUSADA] ", "").strip()
                            
                            esps_reales = [e for e in df_latest['especialista'].unique() if e != 'Sin Asignar']
                            estado_programacion = df_latest['comentarios'].iloc[0] if not df_latest.empty else ""
                            
                            is_atrasada = False
                            
                            if estado_programacion == "SIN_PROGRAMAR":
                                curr_f_ini = hoy
                                curr_f_fin = hoy
                                dias_estimados = 3
                                is_extras = False
                                estado_badge = "⚪ Sin Fecha"
                            else:
                                curr_f_ini = latest_start.date()
                                curr_f_fin = pd.to_datetime(df_latest['fecha_fin'].max()).date()
                                dias_estimados = max(1, (curr_f_fin - curr_f_ini).days + 1)
                                is_extras = 'EXTRAS' in df_latest['comentarios'].values
                                
                                if is_paused:
                                    estado_badge = "⏸️ PAUSADA"
                                elif curr_f_fin < hoy and curr_prog < 100:
                                    is_atrasada = True
                                    estado_badge = "⚠️ ATRASADA"
                                else:
                                    estado_badge = "🟢 Programado"
                            
                            with st.expander(f"{estado_badge} | 📌 Labor: {act} - Avance: {curr_prog}% | Esp: {len(esps_reales)}"):
                                if especialistas_matriz:
                                    st.info(f"💡 **Personal base de la Matriz Semanal:** {', '.join(especialistas_matriz)}")
                                    
                                if len(df_act_raw) > len(df_latest):
                                    st.caption("📜 Esta tarea tiene múltiples segmentos de tiempo (ha sido pausada y reanudada previamente).")
                                    
                                with st.form(key=f"form_update_{nv_id_sel}_{act}"):
                                    
                                    opciones_accion = ["Actualizar Avance / Fechas", "⏸️ Pausar Actividad"]
                                    if is_paused:
                                        opciones_accion = ["▶️ Reanudar Actividad", "Actualizar Avance (Estando Pausada)"]
                                        
                                    accion_seleccionada = st.radio("Acción a realizar:", opciones_accion, horizontal=True)
                                    
                                    col_p, col_f = st.columns([1, 1.5])
                                    nuevo_p = col_p.slider("Avance Específico %", 0, 100, curr_prog)
                                    
                                    col_d, col_e = st.columns(2)
                                    
                                    if accion_seleccionada == "⏸️ Pausar Actividad":
                                        st.info("Al pausar, se congelará el bloque de trabajo actual hasta la fecha indicada para no marcar atraso.")
                                        f_ini = curr_f_ini
                                        f_pausa = col_f.date_input("Fecha en que se detuvo el trabajo", value=hoy, format="DD/MM/YYYY")
                                        dias_trabajo = max(1, (f_pausa - curr_f_ini).days + 1)
                                        just_val = st.text_input("Motivo de la Pausa (Requerido):", value=existing_just_display)
                                        
                                    elif accion_seleccionada == "▶️ Reanudar Actividad":
                                        st.info("Se creará un NUEVO bloque de trabajo desde la nueva fecha de inicio. El bloque pausado anterior se conservará en el historial.")
                                        f_ini = col_f.date_input("Nueva Fecha de Inicio (Reanudación)", value=hoy, format="DD/MM/YYYY")
                                        dias_trabajo = col_d.number_input("Días de trabajo restantes para terminar", min_value=1, value=dias_estimados)
                                        just_val = st.text_input("Comentario (Opcional):", value="")
                                        
                                    else: 
                                        if is_atrasada:
                                            st.error(f"⚠️ El tiempo programado ({curr_f_fin.strftime('%d/%m/%Y')}) ya se cumplió. Obligatorio justificar.")
                                        f_ini = col_f.date_input("Fecha Inicio", value=curr_f_ini, format="DD/MM/YYYY")
                                        dias_trabajo = col_d.number_input("Días de duración", min_value=1, value=dias_estimados)
                                        just_val = st.text_input("Justificación / Comentario:", value=existing_just_display)
                                    
                                    val_d_extra = int(df_latest['dias_extras'].max()) if 'dias_extras' in df_latest.columns and pd.notna(df_latest['dias_extras'].max()) else 0
                                    d_extra = col_d.number_input("Días Extra (Atrasos)", min_value=0, value=max(0, val_d_extra))
                                    extras = col_d.radio("Fines de semana y Feriados", ["Libres (Descanso)", "Extras (Sáb/Dom/Feriado)"], index=1 if is_extras else 0)
                                    
                                    if nv_data_sel.get('tipo_servicio') == 'SE TERRENO':
                                        st.markdown("#### 🕒 Horarios Especiales de Terreno")
                                        c_th1, c_th2, c_th3 = st.columns(3)
                                        
                                        existing_hi = df_latest['hora_inicio_t'].iloc[0] if 'hora_inicio_t' in df_latest.columns and pd.notna(df_latest['hora_inicio_t'].iloc[0]) and df_latest['hora_inicio_t'].iloc[0] != "" else '08:00'
                                        existing_hf = df_latest['hora_fin_t'].iloc[0] if 'hora_fin_t' in df_latest.columns and pd.notna(df_latest['hora_fin_t'].iloc[0]) and df_latest['hora_fin_t'].iloc[0] != "" else '17:30'
                                        existing_hd = float(df_latest['horas_diarias'].iloc[0]) if 'horas_diarias' in df_latest.columns and pd.notna(df_latest['horas_diarias'].iloc[0]) and float(df_latest['horas_diarias'].iloc[0]) > 0 else 9.5
                            
                                        h_inicio_val = c_th1.time_input("Hora de Inicio", value=datetime.strptime(existing_hi, '%H:%M').time(), key=f"hi_{act}")
                                        h_fin_val = c_th2.time_input("Hora de Fin", value=datetime.strptime(existing_hf, '%H:%M').time(), key=f"hf_{act}")
                                        h_diarias_val = c_th3.number_input("Horas por día", value=existing_hd, step=0.5, key=f"hd_{act}")
                                    else:
                                        h_inicio_val = None
                                        h_fin_val = None
                                        h_diarias_val = None
                                    
                                    default_esps = esps_reales if esps_reales else especialistas_matriz
                                    default_esps = [e for e in default_esps if e in ESPECIALISTAS] 
                                    
                                    nuevos_esps = col_e.multiselect("Asignar Especialistas", ESPECIALISTAS, default=default_esps)
                                    modalidad_turno = col_e.radio("Modalidad de Trabajo", ["Simultáneo (Todos a la vez)", "Contra Turno (Rotativo, ej: 7x7)"], help="En Contra Turno, las horas reales se dividirán equitativamente.")
                                    
                                    if st.form_submit_button("Guardar Operación", use_container_width=True):
                                        if (is_atrasada or accion_seleccionada == "⏸️ Pausar Actividad") and not just_val.strip():
                                            st.error("❌ OBLIGATORIO: Debe ingresar una justificación.")
                                        elif is_atrasada and accion_seleccionada == "Actualizar Avance / Fechas" and dias_trabajo <= dias_estimados and nuevo_p < 100:
                                            st.error("❌ OBLIGATORIO: Para quitar el estado de atraso debe aumentar la cantidad de días o marcar el avance al 100%.")
                                        else:
                                            try:
                                                ids_latest = df_latest['id'].tolist()
                                                
                                                if accion_seleccionada == "▶️ Reanudar Actividad":
                                                    for rid in ids_latest:
                                                        old_j = str(df_latest[df_latest['id'] == rid]['justificacion'].iloc[0])
                                                        new_j = old_j.replace("[PAUSADA]", "").strip() + " (Finalizada)"
                                                        supabase.table("asignaciones_personal").update({"justificacion": new_j}).eq("id", rid).execute()
                                                else:
                                                    for rid in ids_latest:
                                                        supabase.table("asignaciones_personal").delete().eq("id", rid).execute()
                                                        
                                                supabase.table("asignaciones_personal").update({"progreso": nuevo_p}).eq("id_nv", nv_id_sel).eq("actividad_ssee", act).execute()
                                                
                                                incluye_finde = True if "Extras" in extras else False
                                                f_f = calcular_fecha_fin_dinamica(f_ini, dias_trabajo, incluye_finde)
                                                hh_base = calcular_hh_ssee(f_ini, f_f, incluye_finde, horas_diarias=h_diarias_val)
                                                
                                                if modalidad_turno == "Contra Turno (Rotativo, ej: 7x7)" and len(nuevos_esps) > 1:
                                                    hh_por_persona = hh_base / len(nuevos_esps)
                                                else:
                                                    hh_por_persona = hh_base
                                                    
                                                final_justificacion_db = f"[PAUSADA] {just_val}" if accion_seleccionada == "⏸️ Pausar Actividad" or (accion_seleccionada == "Actualizar Avance (Estando Pausada)") else just_val
                                                
                                                if not nuevos_esps:
                                                    payload = {
                                                        "id_nv": nv_id_sel, 
                                                        "especialista": "Sin Asignar", 
                                                        "fecha_inicio": str(f_ini), 
                                                        "fecha_fin": str(f_f), 
                                                        "hh_asignadas": 0, 
                                                        "actividad_ssee": act, 
                                                        "comentarios": "EXTRAS" if incluye_finde else "LIBRES", 
                                                        "progreso": nuevo_p,
                                                        "dias_extras": d_extra, 
                                                        "justificacion": final_justificacion_db,
                                                        "hora_inicio_t": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00',
                                                        "hora_fin_t": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30',
                                                        "horas_diarias": h_diarias_val if h_diarias_val else 0
                                                    }
                                                    safe_insert_asignacion(payload)
                                                else:
                                                    for esp in nuevos_esps:
                                                        payload = {
                                                            "id_nv": nv_id_sel, 
                                                            "especialista": esp, 
                                                            "fecha_inicio": str(f_ini), 
                                                            "fecha_fin": str(f_f), 
                                                            "hh_asignadas": hh_por_persona, 
                                                            "actividad_ssee": act, 
                                                            "comentarios": "EXTRAS" if incluye_finde else "LIBRES", 
                                                            "progreso": nuevo_p,
                                                            "dias_extras": d_extra, 
                                                            "justificacion": final_justificacion_db,
                                                            "hora_inicio_t": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00',
                                                            "hora_fin_t": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30',
                                                            "horas_diarias": h_diarias_val if h_diarias_val else 0
                                                        }
                                                        safe_insert_asignacion(payload)
                                                        
                                                st.success("✅ Operación guardada y trazada exitosamente.")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"❌ Error al procesar la actualización: {e}")
                    else:
                        st.info("Utilice el panel de la izquierda para definir las actividades del alcance de este proyecto.")

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
                
                # Excluir explícitamente tareas SIN PROGRAMAR del gráfico
                df_g = df_g[df_g['comentarios'] != 'SIN_PROGRAMAR']
                
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
                            textfont=dict(size=14, color='#000000', family="Arial"),
                            constraintext='none'
                        )
                        
                        fig.update_yaxes(autorange="reversed", title="", type="category", tickmode="linear", tickfont=dict(size=14, color='#333', family="Arial"), gridcolor='rgba(0,0,0,0.05)', categoryorder='array', categoryarray=orden_eje_y, automargin=True)
                        
                        curr = t_i.replace(hour=0, minute=0, second=0, microsecond=0)
                        end_limit = t_f.replace(hour=0, minute=0, second=0, microsecond=0)
                        
                        if (end_limit - curr).days > 90:
                            end_limit = curr + pd.Timedelta(days=90)
                            st.warning("⚠️ El rango es muy amplio. Se muestran máximo 90 días en pantalla para evitar bloqueos.")
                        
                        while curr <= end_limit + pd.Timedelta(days=1):
                            str_curr = curr.strftime("%d-%m-%Y")
                            es_feriado = str_curr in FERIADOS_CHILE_2026
                            es_finde = curr.weekday() >= 5
                            
                            if es_finde or es_feriado:
                                label_txt = "FERIADO" if es_feriado else "SÁB / DOM"
                                color_fill = "#D5D8DC" if es_feriado else "#FADBD8"
                                color_line = "#ABB2B9" if es_feriado else "#E6B0AA"
                                color_font = "#566573" if es_feriado else "#C0392B"
                                
                                fig.add_vrect(x0=curr.strftime("%Y-%m-%d 08:00:00"), x1=(curr + timedelta(days=1)).strftime("%Y-%m-%d 17:30:00"), fillcolor=color_fill, opacity=0.4, annotation_text=f"{label_txt} (DESCANSO)", annotation_position="top left", annotation_font_color=color_font, annotation_font_size=10, layer="below", line_width=1.5, line_dash="dot", line_color=color_line)
                            curr += timedelta(days=1)
                        
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
            df_hh_raw = pd.DataFrame([a for a in asig_all_raw if a['id_nv'] not in ['AUSENCIA', 'INTERNO'] and a['comentarios'] != 'SIN_PROGRAMAR']) if asig_all_raw else pd.DataFrame()
            
            if not df_hh_raw.empty:
                df_hh_raw['hd'] = pd.to_numeric(df_hh_raw['horas_diarias'], errors='coerce').fillna(9.0)
                df_hh_raw.loc[df_hh_raw['hd'] <= 0, 'hd'] = 9.0
                df_hh_raw['d_eje'] = pd.to_numeric(df_hh_raw['hh_asignadas'], errors='coerce').fillna(0) / df_hh_raw['hd']
                df_hh_agg = df_hh_raw.groupby('id_nv')['d_eje'].sum().reset_index()
                
                df_p = df_hh_raw.groupby(['id_nv', 'actividad_ssee'])['progreso'].max().reset_index().groupby('id_nv')['progreso'].mean().reset_index()
                df_hh_agg = df_hh_agg.merge(df_p, on='id_nv', how='left').rename(columns={'progreso': 'Avance_%'})
            else: 
                df_hh_agg = pd.DataFrame(columns=['id_nv', 'd_eje', 'Avance_%'])
            
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
                
                tot_p, tot_e, hoy = 0, 0, datetime.today().date()
                if not df_all_valid.empty:
                    for _, a in df_all_valid.iterrows():
                        try:
                            fi, ff = pd.to_datetime(a['fecha_inicio']).date(), pd.to_datetime(a['fecha_fin']).date()
                        except: continue
                        os_d, oe = max(fi, f_i_m), min(ff, f_f_m)
                        if os_d <= oe:
                            inc = 'EXTRAS' in str(a.get('comentarios', '')).upper()
                            if a.get('actividad_ssee') == 'PROYECCION_GLOBAL':
                                tot_p += sum(1 for i in range((oe - os_d).days + 1) if inc or ((os_d+timedelta(days=i)).weekday() < 5 and (os_d+timedelta(days=i)).strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026))
                            else:
                                re = min(oe, hoy)
                                if os_d <= re: tot_e += sum(1 for i in range((re - os_d).days + 1) if inc or ((os_d+timedelta(days=i)).weekday() < 5 and (os_d+timedelta(days=i)).strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026))
                
                c1, c2 = st.columns(2)
                c1.metric("Cartera Ofertada Consolidada", f"USD ${sum(r['monto_vendido'] if r['moneda']=='USD' else r['monto_vendido']/tasa_cambio for _,r in df_k.iterrows()):,.2f}")
                c2.metric("Ejecución de Gasto Acumulado (USD)", f"USD ${sum(r['monto_gasto'] for _,r in df_g_agg.iterrows())/tasa_cambio:,.2f}")
                
                st.markdown("<br>", unsafe_allow_html=True)
                cg1, cg2 = st.columns(2)
                with cg1:
                    fig_t = go.Figure()
                    fig_t.add_trace(go.Bar(name='Planificado (Matriz)', x=['Desempeño Operativo'], y=[tot_p], marker_color='#3498DB', text=[f"{tot_p} Días Planificados" if tot_p > 0 else ""], textposition='auto', textfont=dict(weight='bold')))
                    fig_t.add_trace(go.Bar(name='Ejecutado Real (Gantt)', x=['Desempeño Operativo'], y=[tot_e], marker_color='#2ECC71', text=[f"{tot_e} Días Reales" if tot_e > 0 else ""], textposition='auto', textfont=dict(weight='bold')))
                    fig_t.update_layout(barmode='group', title=f"Planificado vs Real - {m_sel} {a_sel}", yaxis_title="Cantidad de Días-Hombre", plot_bgcolor='white', legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5))
                    fig_t.add_hline(y=c_neta, line_dash="dash", line_color="#95A5A6", annotation_text=f"Capacidad Máx. ({c_neta} Días)", annotation_position="top right", annotation_font_color="#95A5A6", annotation_font_weight="bold")
                    fig_t.update_yaxes(range=[0, max([c_neta, tot_p, tot_e, 5]) * 1.2])
                    st.plotly_chart(fig_t, use_container_width=True)
                with cg2:
                    st.markdown(f"**Ranking de Avance Operativo (%) - {m_sel}**")
                    df_s = df_k[df_k['tipo_servicio'] == 'SSEE'].sort_values('Avance_%', ascending=True)
                    df_t = df_k[df_k['tipo_servicio'] == 'SE TERRENO'].sort_values('Avance_%', ascending=True)
                    if not df_s.empty: 
                        fig_s = px.bar(df_s, y="Proyecto_Label", x="Avance_%", color="Avance_%", color_continuous_scale=[[0, 'red'], [0.5, 'yellow'], [1, 'green']], title="🔹 SSEE (Salas Eléctricas)", text="Avance_%")
                        fig_s.update_traces(texttemplate='%{text:.1f}%', textposition='outside'); fig_s.update_layout(xaxis_title="Avance (%)", yaxis_title="", coloraxis_showscale=False, plot_bgcolor='white', height=max(200, len(df_s)*40))
                        st.plotly_chart(fig_s, use_container_width=True)
                    if not df_t.empty: 
                        fig_t_r = px.bar(df_t, y="Proyecto_Label", x="Avance_%", color="Avance_%", color_continuous_scale=[[0, 'red'], [0.5, 'yellow'], [1, 'green']], title="🔸 SE Terreno", text="Avance_%")
                        fig_t_r.update_traces(texttemplate='%{text:.1f}%', textposition='outside'); fig_t_r.update_layout(xaxis_title="Avance (%)", yaxis_title="", coloraxis_showscale=False, plot_bgcolor='white', height=max(200, len(df_t)*40))
                        st.plotly_chart(fig_t_r, use_container_width=True)

            with t_i:
                st.subheader("Buscador Analítico de Proyectos")
                nv_sel = st.selectbox("Escriba o Seleccione la Nota de Venta / Cliente:", df_k['Proyecto_Label'].tolist())
                if nv_sel:
                    r_nv = df_k[df_k['Proyecto_Label'] == nv_sel].iloc[0]
                    d_p_m, d_e_t, hoy = 0, 0, datetime.today().date()
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
                                    if inc or (curr.weekday() < 5 and curr.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026):
                                        fechas_activas_matriz.add(curr)
                                    curr += timedelta(days=1)
                            d_p_m = float(len(fechas_activas_matriz))

                        df_acts_proyecto = df_all_temp[(df_all_temp['id_nv'] == r_nv['id_nv']) & (df_all_temp['actividad_ssee'] != 'PROYECCION_GLOBAL') & (df_all_temp['comentarios'] != 'SIN_PROGRAMAR')]
                        if not df_acts_proyecto.empty:
                            fechas_activas_gantt = set()
                            for _, row_act in df_acts_proyecto.iterrows():
                                f_i = pd.to_datetime(row_act['fecha_inicio']).date()
                                f_f = pd.to_datetime(row_act['fecha_fin']).date()
                                inc = 'EXTRAS' in str(row_act.get('comentarios', '')).upper()
                                curr = f_i
                                while curr <= f_f and curr <= hoy:
                                    if inc or (curr.weekday() < 5 and curr.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026):
                                        fechas_activas_gantt.add(curr) 
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
                    col_m4.metric("Ejecución de Tiempos (Días)", f"{d_e_t:.1f} Reales / {d_p_m:.1f} Plan", f"{(d_p_m - d_e_t):.1f} Días Restantes", delta_color="inverse" if (d_p_m - d_e_t) < 0 else "normal")

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
                        fig_b.update_layout(barmode='group', title="Balance: Planificado (Matriz) vs Real (Gantt)", yaxis_title="Cantidad de Días-Hombre", plot_bgcolor='white', height=350, margin=dict(l=20, r=20, t=50, b=20), legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5))
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
                    for a in [x for x in asig_all_raw if x.get('especialista')==esp and x.get('comentarios')!='SIN_PROGRAMAR'] if asig_all_raw else []:
                        try: fi, ff = pd.to_datetime(a['fecha_inicio']).date(), pd.to_datetime(a['fecha_fin']).date()
                        except: continue
                        ts = mapa_ts.get(a.get('id_nv'))
                        inc = 'EXTRAS' in str(a.get('comentarios','')).upper()
                        curr, end_curr = max(fi, f_i_m), min(ff, f_f_m)
                        while curr <= end_curr:
                            if inc or (curr.weekday() < 5 and curr.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026):
                                if ts == 'AUSENCIA': da.add(curr)
                                elif ts == 'INTERNO': di.add(curr)
                                elif ts == 'SSEE': ds.add(curr)
                                elif ts == 'SE TERRENO': dt.add(curr)
                            curr += timedelta(days=1)
                            
                    ds, dt, di = ds - da, dt - da, di - da
                    d_graf = len(ds) if f_oc=="⚡ SSEE" else (len(dt) if f_oc=="👷 SE Terreno" else (len(di) if f_oc=="🏢 Oficina / Interno" else len(ds|dt|di)))
                    
                    dat_oc.append({
                        "Especialista": esp, "Trabajados": d_graf, "Días SSEE": len(ds), "Días SE Terreno": len(dt), 
                        "Días Oficina": len(di), "Días Ausente": len(da), "Disponibles": max(0, tot_d_m - d_graf), 
                        "%": round((d_graf/tot_d_m*100) if tot_d_m>0 else 0, 1)
                    })
                
                df_oc = pd.DataFrame(dat_oc).sort_values("%", ascending=False)
                fig_oc = px.bar(df_oc, x="Especialista", y=["Trabajados", "Disponibles"], title=f"Distribución de Tiempos por Técnico - {m_sel} {a_sel} ({f_oc})", color_discrete_map={"Trabajados": "#3498DB", "Disponibles": "#2ECC71"})
                fig_oc.update_layout(yaxis_title=f"Cantidad de Días (Total Mes: {tot_d_m})", plot_bgcolor='white', barmode='stack', legend_title_text="Estado")
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
                            c_up1, c_up2 = st.columns(2)
                            id_h_up = c_up1.selectbox("ID de Parcialidad:", h_real['id'].tolist())
                            nuevo_est_h = c_up2.selectbox("Nuevo Estado:", ["Pendiente", "Facturada", "Postergada"])
                            if st.button("Actualizar Hito", use_container_width=True):
                                supabase.table("hitos_facturacion").update({"estado": nuevo_est_h}).eq("id", id_h_up).execute()
                                st.success("Actualizado."); st.rerun()
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
                    
                    asig_list = [a for a in asig_list_raw if a.get('actividad_ssee') != 'PROYECCION_GLOBAL' and a.get('comentarios') != 'SIN_PROGRAMAR'] if asig_list_raw else []
                    gastos_list = supabase.table("control_gastos").select("*").eq("id_nv", nv_c_id).execute().data
                    
                    sum_hh = sum(a['hh_asignadas'] for a in asig_list) if asig_list else 0
                    dias_ejecutados = sum_hh / 9.0
                    sum_gas_bruto = sum(g['monto_gasto'] for g in gastos_list) if gastos_list else 0
                    
                    if asig_list:
                        df_avances = pd.DataFrame(asig_list)
                        suma_progreso = df_avances.groupby('actividad_ssee')['progreso'].max().sum()
                        if info_nv['tipo_servicio'] == 'SSEE':
                            avg_prog = suma_progreso / len(ABREVIATURAS)
                        else:
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
                    
                    if asig_list:
                        for act, group in df_avances.groupby('actividad_ssee'):
                            prog = group['progreso'].max()
                            esp_list = ", ".join(group['especialista'].unique())
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
