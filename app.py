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
    /* Fondo claro original profesional */
    .stApp { background-color: #F4F6F9; color: #31333F; }
    
    /* Títulos en Azul Corporativo */
    h1, h2, h3 { color: #003366 !important; font-weight: 700 !important; }
    
    /* Botones en Naranja Original */
    .stButton>button { 
        background-color: #FF6600; 
        color: white; 
        border-radius: 5px; 
        border: none; 
        font-weight: bold; 
        height: 3em; 
        width: 100%;
        transition: 0.3s;
    }
    .stButton>button:hover { background-color: #CC5200; color: white; }
    
    /* Estilo de pestañas (Tabs) */
    .stTabs [aria-selected="true"] { 
        background-color: #003366 !important; 
        color: white !important; 
    }
    
    /* Píldoras para los nombres de especialistas */
    .especialista-pill {
        display: inline-block;
        background-color: #D5F5E3;
        color: #196F3D;
        padding: 5px 15px;
        border-radius: 20px;
        margin-right: 10px;
        margin-bottom: 10px;
        font-weight: 600;
        font-size: 0.9em;
        border: 1px solid #A9DFBF;
    }
    
    /* Login Box */
    .login-container {
        max-width: 400px;
        margin: 50px auto;
        padding: 30px;
        background-color: white;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        border-top: 5px solid #E6007E;
    }
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
    # Proyecto Ausencias
    aus_nv = supabase.table("notas_venta").select("id_nv").eq("id_nv", "AUSENCIA").execute()
    if not aus_nv.data:
        supabase.table("notas_venta").insert({
            "id_nv": "AUSENCIA", "cliente": "Gestión Interna (RRHH)", "tipo_servicio": "SE TERRENO", 
            "lugar": "Oficina/Casa", "moneda": "CLP", "monto_vendido": 0.0, 
            "hh_vendidas": 0.0, "estado": "Abierta"
        }).execute()
        
    # Proyecto Administrativo/Interno
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
    # Excluir explícitamente AUSENCIA e INTERNO
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
                        st.text_input("ID Nota de Venta (No editable)", value=nv_data['id_nv'], disabled=True, help="El ID es el identificador principal y no se puede modificar. Si necesita cambiarlo, elimine el registro y créelo nuevamente.")
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
        
        nvs_activas = obtener_nvs("Abierta")
        if nvs_activas:
            dict_nvs_label = {f"{n['id_nv']} - {n['cliente']}": n for n in nvs_activas}
            
            col_exp1, col_exp2 = st.columns(2)
            
            with col_exp1:
                with st.expander("➕ Asignar Proyección a Proyecto", expanded=False):
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
                        dias_proy = c_f2.number_input("Días totales", min_value=1.0, value=dias_defecto if dias_defecto > 0 else 5.0, key="proy_dias")
                        
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

            with col_exp2:
                with st.expander("🌴 Registrar Ausencia (Vacaciones, Permisos, Faltas)", expanded=False):
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
                f_i = pd.to_datetime(a['fecha_inicio']).date()
                f_f = pd.to_datetime(a['fecha_fin']).date()
                
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
        
        if nvs_activas:
            dict_nvs_label = {f"{n['id_nv']} - {n['cliente']}": n for n in nvs_activas}
            
            c_asig, c_prog = st.columns([1, 1.5])
            
            with c_asig:
                st.subheader("1. Alcance del Proyecto")
                st.info("Defina qué labores componen este proyecto. Estas actividades entrarán a la bolsa de 'Ajustes Vivos' para ser programadas posteriormente.")
                nv_label_sel = st.selectbox("Proyecto (NV - Cliente)", list(dict_nvs_label.keys()))
                nv_data_sel = dict_nvs_label[nv_label_sel]
                nv_id_sel = nv_data_sel['id_nv']
                
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
                            df_act = df_temp[df_temp['key_grupo'] == act]
                            curr_prog = int(df_act['progreso'].max())
                            
                            existing_dias_extras = int(df_act['dias_extras'].max()) if 'dias_extras' in df_act.columns and pd.notna(df_act['dias_extras'].max()) else 0
                            
                            # --- LÓGICA DE PAUSA ---
                            just_series = df_act['justificacion'].dropna() if 'justificacion' in df_act.columns else pd.Series()
                            existing_just_raw = str(just_series.iloc[0]) if not just_series.empty else ""
                            is_paused = "[PAUSADA]" in existing_just_raw.upper()
                            existing_just_display = existing_just_raw.replace("[PAUSADA] ", "").replace("[PAUSADA]", "").strip()
                            
                            esps_reales = [e for e in df_act['especialista'].unique() if e != 'Sin Asignar']
                            estado_programacion = df_act['comentarios'].iloc[0] if not df_act.empty else ""
                            
                            is_atrasada = False
                            
                            if estado_programacion == "SIN_PROGRAMAR":
                                curr_f_ini = hoy
                                curr_f_fin = hoy
                                dias_estimados = 3
                                is_extras = False
                                estado_badge = "⚪ Sin Fecha"
                            else:
                                curr_f_ini = pd.to_datetime(df_act['fecha_inicio'].min()).date()
                                curr_f_fin = pd.to_datetime(df_act['fecha_fin'].max()).date()
                                dias_estimados = max(1, (curr_f_fin - curr_f_ini).days + 1)
                                is_extras = 'EXTRAS' in df_act['comentarios'].values
                                
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
                                    
                                with st.form(key=f"form_update_{nv_id_sel}_{act}"):
                                    
                                    pausar_tarea = st.checkbox("⏸️ Pausar esta actividad (Para no generar alertas de atraso mientras está detenida)", value=is_paused)
                                    
                                    if is_atrasada and not is_paused:
                                        st.error(f"⚠️ El tiempo límite programado ({curr_f_fin.strftime('%d/%m/%Y')}) ya se cumplió. Es obligatorio ingresar una justificación.")
                                        just_val = st.text_input("Justificación del Atraso (Requerido):", value=existing_just_display)
                                    else:
                                        just_val = st.text_input("Justificación o Comentario (Requerido si se pausa):", value=existing_just_display)
                                        
                                    col_p, col_f = st.columns([1, 1.5])
                                    nuevo_p = col_p.slider("Avance Específico %", 0, 100, curr_prog)
                                    f_ini = col_f.date_input("Fecha Inicio", value=curr_f_ini, format="DD/MM/YYYY")
                                    
                                    col_d, col_e = st.columns(2)
                                    dias_trabajo = col_d.number_input("Días de duración total", min_value=1, value=dias_estimados)
                                    
                                    dias_extra_manual = col_d.number_input("Días Extra (Atrasos)", min_value=0, value=existing_dias_extras, help="Corrija a 0 si el sistema sumó días por error en pruebas anteriores.")
                                    extras = col_d.radio("Fines de semana y Feriados", ["Libres (Descanso)", "Extras (Sáb/Dom/Feriado)"], index=1 if is_extras else 0)
                                    
                                    if nv_data_sel.get('tipo_servicio') == 'SE TERRENO':
                                        st.markdown("#### 🕒 Horarios Especiales de Terreno")
                                        c_th1, c_th2, c_th3 = st.columns(3)
                                        
                                        existing_hi = df_act['hora_inicio_t'].iloc[0] if 'hora_inicio_t' in df_act.columns and pd.notna(df_act['hora_inicio_t'].iloc[0]) and df_act['hora_inicio_t'].iloc[0] != "" else '08:00'
                                        existing_hf = df_act['hora_fin_t'].iloc[0] if 'hora_fin_t' in df_act.columns and pd.notna(df_act['hora_fin_t'].iloc[0]) and df_act['hora_fin_t'].iloc[0] != "" else '17:30'
                                        existing_hd = float(df_act['horas_diarias'].iloc[0]) if 'horas_diarias' in df_act.columns and pd.notna(df_act['horas_diarias'].iloc[0]) and float(df_act['horas_diarias'].iloc[0]) > 0 else 9.5
                            
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
                                    
                                    modalidad_turno = col_e.radio("Modalidad de Trabajo", ["Simultáneo (Todos a la vez)", "Contra Turno (Rotativo, ej: 7x7)"], help="En Contra Turno, las horas reales se dividirán equitativamente entre los especialistas seleccionados.")
                                    
                                    if st.form_submit_button("Guardar Programación / Avance", use_container_width=True):
                                        if (is_atrasada or pausar_tarea) and not just_val.strip():
                                            st.error("❌ OBLIGATORIO: Debe ingresar una justificación si la actividad se atrasa o se pone en pausa.")
                                        elif is_atrasada and not pausar_tarea and dias_trabajo <= dias_estimados and nuevo_p < 100:
                                            st.error("❌ OBLIGATORIO: Para quitar el estado de atraso debe aumentar la cantidad de 'Días de duración total' o marcar el avance al 100%.")
                                        else:
                                            try:
                                                supabase.table("asignaciones_personal").delete().eq("id_nv", nv_id_sel).eq("actividad_ssee", act).execute()
                                                
                                                incluye_finde = True if "Extras" in extras else False
                                                f_f = calcular_fecha_fin_dinamica(f_ini, dias_trabajo, incluye_finde)
                                                hh_base = calcular_hh_ssee(f_ini, f_f, incluye_finde, horas_diarias=h_diarias_val)
                                                
                                                if modalidad_turno == "Contra Turno (Rotativo, ej: 7x7)" and len(nuevos_esps) > 1:
                                                    hh_por_persona = hh_base / len(nuevos_esps)
                                                else:
                                                    hh_por_persona = hh_base
                                                    
                                                final_justificacion_db = f"[PAUSADA] {just_val}" if pausar_tarea else just_val
                                                
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
                                                        "dias_extras": dias_extra_manual, 
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
                                                            "dias_extras": dias_extra_manual, 
                                                            "justificacion": final_justificacion_db,
                                                            "hora_inicio_t": h_inicio_val.strftime('%H:%M') if h_inicio_val else '08:00',
                                                            "hora_fin_t": h_fin_val.strftime('%H:%M') if h_fin_val else '17:30',
                                                            "horas_diarias": h_diarias_val if h_diarias_val else 0
                                                        }
                                                        safe_insert_asignacion(payload)
                                                        
                                                st.success("✅ Actividad actualizada exitosamente.")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"❌ Error al procesar la actualización: {e}")
                    else:
                        st.info("Utilice el panel de la izquierda para definir las actividades del alcance de este proyecto.")

        st.divider()
        st.subheader("3. Asignación de Trabajos Internos (Taller / Oficina / Cursos)")
        st.info("Utilice este panel para asignar labores que no pertenecen a un proyecto comercial.")
        
        c_int1, c_int2 = st.columns(2)
        with c_int1:
            with st.expander("🏢 Asignar Nueva Labor Interna", expanded=False):
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
                                st.success("✅ Labor interna registrada. Aparecerá en la Matriz y el Gantt.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error al registrar labor: {e}")
                        else:
                            st.error("⚠️ Seleccione especialistas y asegúrese de que las fechas sean correctas.")
                            
        with c_int2:
            with st.expander("🗑️ Gestionar Labores Internas activas", expanded=False):
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
                            id_int = opciones_int_borrar[int_seleccionada]
                            supabase.table("asignaciones_personal").delete().eq("id", id_int).execute()
                            st.success("✅ Labor eliminada exitosamente.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al eliminar: {e}")
                else:
                    st.write("No hay labores internas registradas en el sistema.")

        st.divider()
        st.subheader("4. Cronograma Operativo (Gantt)")
        
        c_v1, c_v2 = st.columns(2)
        vista_gantt = c_v1.radio("Filtro de Vista:", ["🌍 General (Todos)", "🔍 Por Proyecto Seleccionado"], horizontal=True)
        filtro_tipo = c_v2.radio("Tipo de Servicio (Filtra la vista General):", ["Todos", "SSEE", "SE TERRENO", "Internos (RRHH / Taller)"], horizontal=True)
        
        c_v3, c_v4 = st.columns(2)
        finestra_temps = c_v3.radio("⏳ Ventana de Tiempo:", ["Todo el Proyecto", "1 Semana", "15 Días", "1 Mes"], horizontal=True, index=2)
        data_inici_gantt = c_v4.date_input("📅 Fecha de inicio", value=datetime.today().date())

        asig_gantt_raw = supabase.table("asignaciones_personal").select("*").execute().data
        if asig_gantt_raw:
            df_g = pd.DataFrame(asig_gantt_raw)
            df_g = df_g[df_g['actividad_ssee'] != 'PROYECCION_GLOBAL']
            
            nvs_gantt_todas = obtener_nvs()
            nvs_info = {n['id_nv']: n['cliente'] for n in nvs_gantt_todas} if nvs_gantt_todas else {}
            nvs_tipo = {n['id_nv']: n['tipo_servicio'] for n in nvs_gantt_todas} if nvs_gantt_todas else {}
            
            nvs_info['AUSENCIA'] = 'Gestión Interna (RRHH)'
            nvs_tipo['AUSENCIA'] = 'Internos (RRHH / Taller)'
            nvs_info['INTERNO'] = 'Gestión Interna (Operaciones)'
            nvs_tipo['INTERNO'] = 'Internos (RRHH / Taller)'
            
            if vista_gantt == "🔍 Por Proyecto Seleccionado":
                df_g = df_g[df_g['id_nv'] == nv_id_sel]
            else:
                if filtro_tipo != "Todos":
                    df_g['tipo_temp'] = df_g['id_nv'].map(nvs_tipo)
                    df_g = df_g[df_g['tipo_temp'] == filtro_tipo]
            
            if not df_g.empty:
                df_g['cliente'] = df_g['id_nv'].map(nvs_info)
                df_g['Labor'] = df_g['actividad_ssee'].fillna('Servicio Terreno')
                
                if 'hora_inicio_t' in df_g.columns:
                    df_g['hora_i_str'] = df_g['hora_inicio_t'].fillna('08:00').replace('', '08:00')
                    df_g['hora_f_str'] = df_g['hora_fin_t'].fillna('17:30').replace('', '17:30')
                else:
                    df_g['hora_i_str'] = '08:00'
                    df_g['hora_f_str'] = '17:30'

                df_g['start_ts'] = pd.to_datetime(df_g['fecha_inicio'].astype(str) + ' ' + df_g['hora_i_str'])
                df_g['end_ts'] = pd.to_datetime(df_g['fecha_fin'].astype(str) + ' ' + df_g['hora_f_str'])
                
                fechas_validas = df_g[df_g['comentarios'] != 'SIN_PROGRAMAR']['start_ts']
                fecha_base_gantt = fechas_validas.min() if not fechas_validas.empty else (pd.to_datetime(datetime.today().date()) + pd.Timedelta(hours=8))
                
                # --- AGREGAR JUSTIFICACIÓN PARA LEER LA PAUSA EN EL GANTT ---
                df_grouped = df_g.groupby(['id_nv', 'cliente', 'Labor', 'start_ts', 'end_ts', 'progreso', 'comentarios']).agg({
                    'especialista': lambda x: ", ".join(set(x)),
                    'justificacion': 'first'
                }).reset_index()
                
                df_grouped = df_grouped.sort_values(by=['id_nv', 'start_ts'], ascending=[True, True])
                
                df_grouped['Eje_Y'] = df_grouped['id_nv'] + " | " + df_grouped['Labor']
                
                expanded_rows = []
                for _, row in df_grouped.iterrows():
                    start = row['start_ts']
                    end = row['end_ts']
                    
                    is_task_paused = False
                    if pd.notna(row.get('justificacion')):
                        is_task_paused = "[PAUSADA]" in str(row['justificacion']).upper()
                        
                    base_label = f"{row['Labor']} ({row['progreso']}%)"
                    if is_task_paused:
                        row['Etiqueta_Barra'] = f"<b>⏸️ {base_label} (PAUSADA)</b>"
                    else:
                        row['Etiqueta_Barra'] = f"<b>{base_label}</b>"
                    
                    if row['comentarios'] == 'SIN_PROGRAMAR':
                        new_row = row.copy()
                        new_row['start_ts'] = fecha_base_gantt
                        new_row['end_ts'] = fecha_base_gantt + pd.Timedelta(minutes=30)
                        new_row['Inicio'] = "Por definir"
                        new_row['Fin'] = "Por definir"
                        new_row['Etiqueta_Barra'] = "<b>⚠️ SIN FECHA</b>"
                        expanded_rows.append(new_row)
                    elif row['comentarios'] == 'LIBRES' or row['id_nv'] == 'INTERNO':
                        current_chunk_start = start
                        current_day = start.date()
                        end_day = end.date()
                        
                        while current_day <= end_day:
                            es_feriado = current_day.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
                            es_finde = current_day.weekday() >= 5
                            
                            if es_finde or es_feriado:
                                prev_day = current_day - pd.Timedelta(days=1)
                                chunk_end = pd.Timestamp.combine(prev_day, end.time())
                                
                                if current_chunk_start <= chunk_end:
                                    new_row = row.copy()
                                    new_row['start_ts'] = current_chunk_start
                                    new_row['end_ts'] = chunk_end
                                    new_row['Inicio'] = current_chunk_start.strftime('%d/%m/%Y %H:%M')
                                    new_row['Fin'] = chunk_end.strftime('%d/%m/%Y %H:%M')
                                    expanded_rows.append(new_row)
                                
                                next_day = current_day + pd.Timedelta(days=1)
                                current_chunk_start = pd.Timestamp.combine(next_day, start.time())
                            elif current_day == end_day:
                                if current_chunk_start <= end:
                                    new_row = row.copy()
                                    new_row['start_ts'] = current_chunk_start
                                    new_row['end_ts'] = end
                                    new_row['Inicio'] = current_chunk_start.strftime('%d/%m/%Y %H:%M')
                                    new_row['Fin'] = end.strftime('%d/%m/%Y %H:%M')
                                    expanded_rows.append(new_row)
                            
                            current_day += pd.Timedelta(days=1)
                    else:
                        row['Inicio'] = start.strftime('%d/%m/%Y %H:%M')
                        row['Fin'] = end.strftime('%d/%m/%Y %H:%M')
                        expanded_rows.append(row)
                        
                df_plot = pd.DataFrame(expanded_rows)

                ts_inici = pd.to_datetime(data_inici_gantt)
                if finestra_temps == "1 Semana":
                    ts_fi = ts_inici + pd.Timedelta(days=7)
                elif finestra_temps == "15 Días":
                    ts_fi = ts_inici + pd.Timedelta(days=15)
                elif finestra_temps == "1 Mes":
                    ts_fi = ts_inici + pd.Timedelta(days=30)
                else: 
                    min_ts = df_plot['start_ts'].min() if not df_plot.empty else ts_inici
                    max_ts = df_plot['end_ts'].max() if not df_plot.empty else ts_inici + pd.Timedelta(days=30)
                    ts_inici = min_ts
                    ts_fi = max_ts

                # --- MEJORA: FILTRAR LIMPIAMENTE Y RECALCULAR EJE Y ---
                if not df_plot.empty:
                    df_plot = df_plot[(df_plot['end_ts'] >= ts_inici) & (df_plot['start_ts'] <= ts_fi)]

                if df_plot.empty:
                    st.info("No hay actividades programadas en la ventana de tiempo seleccionada.")
                else:
                    orden_eje_y = df_plot['Eje_Y'].unique()
                    
                    colores_globo = ['#3498DB', '#E67E22', '#2ECC71', '#E74C3C', '#9B59B6', '#1ABC9C', '#F1C40F', '#7F8C8D']

                    fig = px.timeline(
                        df_plot, 
                        x_start="start_ts", 
                        x_end="end_ts", 
                        y="Eje_Y", 
                        color="Labor",
                        text="Etiqueta_Barra",
                        hover_data={"especialista": True, "progreso": True, "Inicio": True, "Fin": True, "start_ts": False, "end_ts": False},
                        color_discrete_sequence=colores_globo
                    )

                    fig.update_traces(
                        textposition='inside', 
                        insidetextanchor='middle', 
                        marker_line_width=0, 
                        opacity=0.95, 
                        width=0.85, 
                        textfont_size=22, 
                        textfont_color='#000000',
                        insidetextfont=dict(size=22, color='#000000', family="Arial Black"),
                        constraintext='none' 
                    )
                    
                    fig.update_yaxes(
                        autorange="reversed", 
                        title="", 
                        type="category",        
                        tickmode="linear", 
                        tickfont=dict(size=14, color='#333', family="Arial"), 
                        gridcolor='rgba(0,0,0,0.05)', 
                        categoryorder='array', 
                        categoryarray=orden_eje_y,
                        automargin=True
                    )
                    
                    curr = ts_inici.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_limit = ts_fi.replace(hour=0, minute=0, second=0, microsecond=0)
                    
                    if (end_limit - curr).days > 90:
                        end_limit = curr + pd.Timedelta(days=90)
                        st.warning("⚠️ El rango del proyecto es muy amplio. Se muestran máximo 90 días en pantalla para evitar bloqueos. Use los filtros de '1 Mes' o '15 Días' para explorar con mayor detalle.")
                    
                    while curr <= end_limit + pd.Timedelta(days=1):
                        str_curr = curr.strftime("%d-%m-%Y")
                        es_feriado = str_curr in FERIADOS_CHILE_2026
                        es_finde = curr.weekday() >= 5
                        
                        if es_finde or es_feriado:
                            label_txt = "FERIADO" if es_feriado else "SÁB / DOM"
                            color_fill = "#D5D8DC" if es_feriado else "#FADBD8"
                            color_line = "#ABB2B9" if es_feriado else "#E6B0AA"
                            color_font = "#566573" if es_feriado else "#C0392B"
                            
                            fig.add_vrect(
                                x0=curr.strftime("%Y-%m-%d 08:00:00"), 
                                x1=(curr + timedelta(days=1)).strftime("%Y-%m-%d 17:30:00"),
                                fillcolor=color_fill, opacity=0.4, 
                                annotation_text=f"{label_txt} (DESCANSO)", annotation_position="top left",
                                annotation_font_color=color_font, annotation_font_size=10,
                                layer="below", line_width=1.5, line_dash="dot", line_color=color_line
                            )
                        curr += timedelta(days=1)
                    
                    fig.update_xaxes(
                        range=[ts_inici.strftime("%Y-%m-%d 00:00:00"), ts_fi.strftime("%Y-%m-%d 23:59:59")],
                        tickformat="%d/%m/%Y", 
                        title="Fecha Operativa", 
                        tickfont=dict(size=12, color='#666'), 
                        gridcolor='rgba(0,0,0,0.05)', 
                        showline=True, linewidth=1, linecolor='rgba(0,0,0,0.2)',
                        automargin=True
                    )
                    
                    altura_dinamica = max(250, len(orden_eje_y) * 85)
                    fig.update_layout(
                        height=altura_dinamica, 
                        margin=dict(l=250, r=30, t=60, b=80), 
                        plot_bgcolor='white', 
                        paper_bgcolor='white', 
                        legend_title_text='', 
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), 
                        hoverlabel=dict(bgcolor="white", font_size=13, font_family="Arial")
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                    html_string = fig.to_html(include_plotlyjs='cdn')
                    b64 = base64.b64encode(html_string.encode('utf-8')).decode()
                    href = f'<a href="data:text/html;base64,{b64}" download="Cronograma_Gantt_FPS.html" style="display: inline-block; padding: 0.5em 1em; background-color: #003366; color: white; text-decoration: none; border-radius: 5px; font-weight: margin-top: 10px;">📥 Descargar Gantt Interactivo (HTML)</a>'
                    st.markdown(href, unsafe_allow_html=True)

            else:
                st.info("Aún no hay actividades agregadas al alcance para la vista seleccionada.")

    # ==========================================
    # MÓDULO 4: GASTOS Y KPIs (FACTURACIÓN POR HITOS Y BACKLOG)
    # ==========================================
    with tab4:
        st.header("Análisis de Datos y Control Financiero")
        
        nvs_all = obtener_nvs()
        if not nvs_all:
            st.warning("No hay notas de venta registradas para analizar.")
        else:
            try:
                hitos_raw = supabase.table("hitos_facturacion").select("*").execute().data
                df_hitos = pd.DataFrame(hitos_raw) if hitos_raw else pd.DataFrame(columns=["id", "id_nv", "mes", "anio", "porcentaje", "monto", "estado"])
            except Exception:
                df_hitos = pd.DataFrame(columns=["id", "id_nv", "mes", "anio", "porcentaje", "monto", "estado"])

            nvs_activas = obtener_nvs("Abierta")
            if nvs_activas:
                with st.expander("➕ REGISTRAR GASTO OPERATIVO (Siempre en CLP)"):
                    st.info(f"💡 Los gastos se ingresan en Pesos Chilenos (CLP). Si la NV es en dólares, el sistema lo convertirá usando la tasa actual (1 USD = ${tasa_cambio} CLP).")
                    with st.form("form_gastos"):
                        c_g1, c_g2, c_g3, c_g4 = st.columns(4)
                        nv_g_label = c_g1.selectbox("Proyecto Asociado", [f"{n['id_nv']} - {n['cliente']}" for n in nvs_activas])
                        t_g = c_g2.selectbox("Ítem", ["Rendigastos", "Viático", "Hospedaje", "Pasajes", "Insumos"])
                        
                        m_g_str = c_g3.text_input("Monto del Gasto (CLP)", value="", placeholder="Ej: 1.500.000")
                        f_gasto = c_g4.date_input("Fecha Gasto", format="DD/MM/YYYY")
                        
                        if st.form_submit_button("Guardar Gasto"):
                            m_g_clean = str(m_g_str).replace(".", "").replace(",", "").strip()
                            m_g = float(m_g_clean) if m_g_clean.isdigit() else 0.0
                            
                            try:
                                supabase.table("control_gastos").insert({
                                    "id_nv": nv_g_label.split(" - ")[0], 
                                    "tipo_gasto": t_g, 
                                    "monto_gasto": m_g, 
                                    "fecha_gasto": str(f_gasto)
                                }).execute()
                                st.success("✅ Gasto registrado en la base de datos.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error al guardar el gasto: {e}")

            df_nv = pd.DataFrame(nvs_all)
            gastos_raw = supabase.table("control_gastos").select("*").execute().data
            df_gastos_full = pd.DataFrame(gastos_raw) if gastos_raw else pd.DataFrame(columns=['id_nv', 'monto_gasto', 'tipo_gasto', 'fecha_gasto'])
            df_gas_agg = df_gastos_full.groupby('id_nv')['monto_gasto'].sum().reset_index() if not df_gastos_full.empty else pd.DataFrame(columns=['id_nv', 'monto_gasto'])
            asig_all_raw = supabase.table("asignaciones_personal").select("*").execute().data
            
            df_ausencias = pd.DataFrame()
            df_hh_raw = pd.DataFrame()
            
            if asig_all_raw:
                df_all = pd.DataFrame(asig_all_raw)
                df_ausencias = df_all[df_all['id_nv'] == 'AUSENCIA']
                df_hh_raw = df_all[(df_all['id_nv'] != 'AUSENCIA') & (df_all['id_nv'] != 'INTERNO') & (df_all['actividad_ssee'] != 'PROYECCION_GLOBAL') & (df_all['comentarios'] != 'SIN_PROGRAMAR')]
                
                if not df_hh_raw.empty:
                    df_hh_raw['horas_diarias_calc'] = pd.to_numeric(df_hh_raw['horas_diarias'], errors='coerce').fillna(9.0).apply(lambda x: float(x) if float(x) > 0 else 9.0)
                    df_hh_raw['dias_reales_calc'] = df_hh_raw['hh_asignadas'] / df_hh_raw['horas_diarias_calc']
                    
                    df_hh_agg = df_hh_raw.groupby('id_nv')[['hh_asignadas', 'dias_reales_calc']].sum().reset_index()
                    df_hh_agg.rename(columns={'dias_reales_calc': 'dias_ejecutados'}, inplace=True)
                    
                    df_prog_nv = df_hh_raw.groupby(['id_nv', 'actividad_ssee'])['progreso'].max().reset_index()
                    df_prog_sum = df_prog_nv.groupby('id_nv')['progreso'].sum().reset_index()
                    df_prog_sum = df_prog_sum.merge(df_nv[['id_nv', 'tipo_servicio']], on='id_nv', how='left')
                    
                    def calc_avance(row):
                        if row['tipo_servicio'] == 'SSEE':
                            return row['progreso'] / len(ABREVIATURAS)
                        else:
                            count_acts = df_prog_nv[df_prog_nv['id_nv'] == row['id_nv']]['actividad_ssee'].nunique()
                            return row['progreso'] / count_acts if count_acts > 0 else 0
                            
                    df_prog_sum['Avance_%'] = df_prog_sum.apply(calc_avance, axis=1)
                    df_prog_avg = df_prog_sum[['id_nv', 'Avance_%']]
                    df_hh_agg = df_hh_agg.merge(df_prog_avg, on='id_nv', how='left')
                else:
                    df_hh_agg = pd.DataFrame(columns=['id_nv', 'hh_asignadas', 'dias_ejecutados', 'Avance_%'])
            else:
                df_hh_agg = pd.DataFrame(columns=['id_nv', 'hh_asignadas', 'dias_ejecutados', 'Avance_%'])
                
            df_kpi = df_nv.merge(df_gas_agg, on='id_nv', how='left').merge(df_hh_agg, on='id_nv', how='left').fillna(0)
            df_kpi.rename(columns={'hh_vendidas': 'dias_proyectados'}, inplace=True)
            df_kpi['id_nv_str'] = df_kpi['id_nv'].astype(str)
            df_kpi['Proyecto_Label'] = df_kpi['id_nv_str'] + " (" + df_kpi['cliente'] + ")"
            
            if 'estado_facturacion' not in df_kpi.columns:
                df_kpi['estado_facturacion'] = 'Pendiente'
            else:
                df_kpi['estado_facturacion'] = df_kpi['estado_facturacion'].fillna('Pendiente')
                
            if not df_hitos.empty:
                hitos_facturados = df_hitos[df_hitos['estado'] == 'Facturada'].groupby('id_nv')['monto'].sum().reset_index()
                hitos_facturados.rename(columns={'monto': 'monto_facturado_hitos'}, inplace=True)
                df_kpi = df_kpi.merge(hitos_facturados, on='id_nv', how='left')
                df_kpi['monto_facturado_hitos'] = df_kpi['monto_facturado_hitos'].fillna(0)
            else:
                df_kpi['monto_facturado_hitos'] = 0.0

            def calc_monto_pendiente(row):
                if row['estado_facturacion'] == 'Facturada':
                    return 0.0
                if row['monto_facturado_hitos'] > 0:
                    return max(0.0, float(row['monto_vendido']) - float(row['monto_facturado_hitos']))
                return float(row['monto_vendido'])

            df_kpi['monto_pendiente'] = df_kpi.apply(calc_monto_pendiente, axis=1)
            
            if 'created_at' in df_kpi.columns:
                df_kpi['fecha_creacion'] = pd.to_datetime(df_kpi['created_at'], errors='coerce').dt.date
                df_kpi['fecha_creacion'] = df_kpi['fecha_creacion'].fillna(datetime.today().date())
            else:
                df_kpi['fecha_creacion'] = datetime.today().date()
            
            df_kpi['monto_gasto_ajustado'] = df_kpi.apply(lambda row: row['monto_gasto'] / tasa_cambio if row['moneda'] == 'USD' else row['monto_gasto'], axis=1)
            df_kpi['Margen'] = df_kpi['monto_vendido'] - df_kpi['monto_gasto_ajustado']

            tab_global, tab_individual, tab_ocupacion, tab_tabla, tab_pendientes = st.tabs([
                "🌍 Global Mensual", 
                "🔍 Análisis Individual", 
                "👥 Ocupación Personal",
                "📋 Tabla y Facturación", 
                "⏳ Pendientes (Backlog)"
            ])

            with tab_global:
                st.subheader("Visión Operativa Mensual (Consolidada en Días-Hombre)")
                
                c_filt1, c_filt2 = st.columns(2)
                año_actual = datetime.today().year
                mes_actual = datetime.today().month
                lista_anios = list(range(año_actual - 2, año_actual + 2))
                
                mes_sel = c_filt1.selectbox("Seleccione el Mes:", list(MESES_ES.values()), index=mes_actual-1)
                anio_sel = c_filt2.selectbox("Seleccione el Año:", lista_anios, index=lista_anios.index(año_actual))
                
                mes_num = list(MESES_ES.keys())[list(MESES_ES.values()).index(mes_sel)]
                _, ultimo_dia = calendar.monthrange(anio_sel, mes_num)
                fecha_inicio_mes = datetime(anio_sel, mes_num, 1).date()
                fecha_fin_mes = datetime(anio_sel, mes_num, ultimo_dia).date()
                
                dias_habiles_mes = 0
                curr_d = fecha_inicio_mes
                while curr_d <= fecha_fin_mes:
                    if curr_d.weekday() < 5 and curr_d.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026:
                        dias_habiles_mes += 1
                    curr_d += timedelta(days=1)
                
                capacidad_total_teorica = dias_habiles_mes * len(ESPECIALISTAS)
                
                dias_ausencia_mes = 0
                if not df_ausencias.empty:
                    for _, row_aus in df_ausencias.iterrows():
                        d_ini = pd.to_datetime(row_aus['fecha_inicio']).date()
                        d_fin = pd.to_datetime(row_aus['fecha_fin']).date()
                        
                        c_date = max(d_ini, fecha_inicio_mes)
                        e_date = min(d_fin, fecha_fin_mes)
                        while c_date <= e_date:
                            if c_date.weekday() < 5 and c_date.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026:
                                dias_ausencia_mes += 1
                            c_date += timedelta(days=1)
                
                capacidad_neta_mes = int(capacidad_total_teorica - dias_ausencia_mes)
                
                total_dias_proyectados = 0.0
                total_dias_ejecutados = 0.0
                
                if asig_all_raw:
                    for a in asig_all_raw:
                        if a.get('id_nv') == 'AUSENCIA' or a.get('id_nv') == 'INTERNO' or a.get('comentarios') == 'SIN_PROGRAMAR':
                            continue
                            
                        try:
                            f_i_a = pd.to_datetime(a['fecha_inicio']).date()
                            f_f_a = pd.to_datetime(a['fecha_fin']).date()
                        except:
                            continue
                        
                        overlap_start = max(f_i_a, fecha_inicio_mes)
                        overlap_end = min(f_f_a, fecha_fin_mes)
                        
                        if overlap_start <= overlap_end:
                            incluye_f = (a.get('comentarios') == 'EXTRAS' or 'Extras' in str(a.get('comentarios','')))
                            
                            dias_overlap = 0
                            curr = overlap_start
                            while curr <= overlap_end:
                                es_feriado = curr.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
                                es_finde = curr.weekday() >= 5
                                if incluye_f or (not es_finde and not es_feriado):
                                    dias_overlap += 1
                                curr += timedelta(days=1)
                                
                            if a.get('actividad_ssee') == 'PROYECCION_GLOBAL':
                                total_dias_proyectados += dias_overlap
                            else:
                                dias_totales_tarea = 0
                                curr_tot = f_i_a
                                while curr_tot <= f_f_a:
                                    es_feriado = curr_tot.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
                                    es_finde = curr_tot.weekday() >= 5
                                    if incluye_f or (not es_finde and not es_feriado):
                                        dias_totales_tarea += 1
                                    curr_tot += timedelta(days=1)
                                    
                                ratio = dias_overlap / dias_totales_tarea if dias_totales_tarea > 0 else 0
                                hh_asignadas_total = float(a.get('hh_asignadas', 0))
                                hh_en_mes = hh_asignadas_total * ratio
                                
                                horas_diarias_asig = float(a.get('horas_diarias', 0))
                                if horas_diarias_asig <= 0: horas_diarias_asig = 9.0
                                
                                total_dias_ejecutados += (hh_en_mes / horas_diarias_asig)

                total_dias_proyectados = int(round(total_dias_proyectados))
                total_dias_ejecutados = int(round(total_dias_ejecutados))
                
                df_kpi_mes = df_kpi[(df_kpi['fecha_creacion'] >= fecha_inicio_mes) & (df_kpi['fecha_creacion'] <= fecha_fin_mes)].copy()
                
                if df_kpi_mes.empty and total_dias_ejecutados == 0 and total_dias_proyectados == 0:
                    st.info(f"No hay proyectos comerciales operando durante {mes_sel} de {anio_sel}.")
                else:
                    df_kpi_mes['venta_usd'] = df_kpi_mes.apply(lambda row: row['monto_vendido'] if row['moneda'] == 'USD' else row['monto_vendido'] / tasa_cambio, axis=1)
                    total_venta_usd = df_kpi_mes['venta_usd'].sum()
                    
                    total_gasto_clp = df_kpi_mes['monto_gasto'].sum()
                    total_gasto_usd = total_gasto_clp / tasa_cambio
                    
                    fmt_tot = f"USD ${total_venta_usd:,.2f}"
                    fmt_gas_usd = f"USD ${total_gasto_usd:,.2f}"
                    gasto_clp_fmt = f"{total_gasto_clp:,.0f}".replace(",", ".")
                    
                    col1, col2 = st.columns(2)
                    col1.metric(f"Cartera Ofertada Consolidada en {mes_sel}", fmt_tot)
                    col2.metric("Ejecución de Gasto Acumulado (USD)", fmt_gas_usd, help=f"Tus rendiciones originales suman CLP ${gasto_clp_fmt} convertidas a la tasa actual.")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    c_graf1, c_graf2 = st.columns(2)
                    
                    with c_graf1:
                        df_tiempos = pd.DataFrame({
                            "Concepto": [f"Capacidad Neta Mes ({dias_habiles_mes} hábiles)", "Días Planificados (Vendidos)", "Días Consumidos (Reales)", "Días Ausencia RRHH (Desc.)"],
                            "Cantidad": [capacidad_neta_mes, total_dias_proyectados, total_dias_ejecutados, int(dias_ausencia_mes)]
                        })
                        fig_tiempos = px.bar(
                            df_tiempos, x="Concepto", y="Cantidad", color="Concepto", text="Cantidad",
                            color_discrete_map={
                                f"Capacidad Neta Mes ({dias_habiles_mes} hábiles)": "#95A5A6", 
                                "Días Planificados (Vendidos)": "#3498DB", 
                                "Días Consumidos (Reales)": "#F39C12",
                                "Días Ausencia RRHH (Desc.)": "#E74C3C" 
                            },
                            title=f"Balance de Tiempos Operativos y Capacidad de {mes_sel} {anio_sel}"
                        )
                        fig_tiempos.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                        fig_tiempos.update_layout(yaxis_title="Cantidad de Días-Hombre", showlegend=False, plot_bgcolor='white')
                        
                        max_y = max([capacidad_neta_mes, total_dias_proyectados, total_dias_ejecutados, int(dias_ausencia_mes)] + [1])
                        fig_tiempos.update_yaxes(range=[0, max_y * 1.2])
                        st.plotly_chart(fig_tiempos, use_container_width=True)
                    
                    with c_graf2:
                        df_kpi_mes_sorted = df_kpi_mes.sort_values('Avance_%', ascending=True)
                        fig_ranking = px.bar(
                            df_kpi_mes_sorted, 
                            y="Proyecto_Label", 
                            x="Avance_%", 
                            color="Avance_%",
                            color_continuous_scale=[[0, 'red'], [0.5, 'yellow'], [1, 'green']],
                            title=f"Ranking de Avance Operativo por Proyecto (%) - {mes_sel}",
                            text="Avance_%"
                        )
                        fig_ranking.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                        fig_ranking.update_layout(xaxis_title="Avance Físico (%)", yaxis_title="Proyectos Activos", coloraxis_showscale=False, plot_bgcolor='white')
                        st.plotly_chart(fig_ranking, use_container_width=True)

            with tab_individual:
                st.subheader("Buscador Analítico de Proyectos")
                nv_seleccionada = st.selectbox("Escriba o Seleccione la Nota de Venta / Cliente:", df_kpi['Proyecto_Label'].tolist())
                
                if nv_seleccionada:
                    row_nv = df_kpi[df_kpi['Proyecto_Label'] == nv_seleccionada].iloc[0]
                    mon = row_nv['moneda']
                    m_v = row_nv['monto_vendido']
                    m_g_usd_ajustado = row_nv['monto_gasto_ajustado']
                    
                    gasto_clp_real = df_gas_agg.loc[df_gas_agg['id_nv'] == row_nv['id_nv'], 'monto_gasto'].values
                    m_g_clp = gasto_clp_real[0] if len(gasto_clp_real) > 0 else 0.0

                    m_m = row_nv['Margen']
                    a_p = row_nv['Avance_%']
                    d_p = row_nv['dias_proyectados']
                    d_e = row_nv['dias_ejecutados']
                    estado_nv = row_nv['estado']
                    
                    fmt_v = f"{mon} ${m_v:,.0f}".replace(",", ".") if mon == 'CLP' else f"{mon} ${m_v:,.2f}"
                    fmt_g_clp = f"CLP ${m_g_clp:,.0f}".replace(",", ".")
                    fmt_m = f"{mon} ${m_m:,.0f}".replace(",", ".") if mon == 'CLP' else f"{mon} ${m_m:,.2f}"
                    
                    st.markdown(f"**Estado del Proyecto:** `{'🟢 ABIERTA' if estado_nv == 'Abierta' else '🔴 CERRADA'}`")
                    if mon == 'USD':
                        st.caption(f"*Nota: El Margen Neto se calcula convirtiendo los gastos operativos a USD usando la tasa de $ {tasa_cambio} CLP/USD.*")
                    
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    col_m1.metric("Presupuesto de Venta", fmt_v)
                    col_m2.metric("Total Gastos Operativos (CLP)", fmt_g_clp)
                    col_m3.metric(
                        "Avance Físico Total", 
                        f"{a_p:.1f}%", 
                        help="Para proyectos SSEE, se calcula sumando el avance de cada tarea y dividiendo por las 7 actividades estándar obligatorias. Para Servicios en Terreno, promedia las labores ejecutadas."
                    )
                    
                    holgura_dias = d_p - d_e
                    col_m4.metric(
                        "Ejecución de Tiempos (Días)", 
                        f"{d_e:.1f} Reales / {d_p:.1f} Plan", 
                        f"{holgura_dias:.1f} Días Restantes", 
                        delta_color="inverse" if holgura_dias < 0 else "normal"
                    )

                    st.markdown("---")
                    
                    has_extras = 'dias_extras' in df_hh_raw.columns
                    if has_extras and not df_hh_raw.empty:
                        df_tot_extras = df_hh_raw[df_hh_raw['id_nv'] == row_nv['id_nv']]
                        total_dias_retraso = int(pd.to_numeric(df_tot_extras.groupby('actividad_ssee')['dias_extras'].max(), errors='coerce').sum())
                        if total_dias_retraso > 0:
                            st.warning(f"🚨 **Atención:** Las actividades de este proyecto acumulan un total de **{total_dias_retraso} días extras** sobre lo planificado debido a atrasos.")
                    
                    st.markdown("### 👨‍🔧 Equipo Técnico Participante")
                    if asig_all_raw:
                        df_equipo = pd.DataFrame(asig_all_raw)
                        df_equipo = df_equipo[(df_equipo['id_nv'] == row_nv['id_nv']) & (df_equipo['actividad_ssee'] != 'PROYECCION_GLOBAL') & (df_equipo['especialista'] != 'Sin Asignar')]
                        
                        if not df_equipo.empty:
                            especialistas_unicos = df_equipo['especialista'].unique().tolist()
                            html_pills = "".join([f"<span class='especialista-pill'>{esp}</span>" for esp in especialistas_unicos])
                            st.markdown(html_pills, unsafe_allow_html=True)
                        else:
                            st.info("Aún no se han asignado especialistas reales a las actividades de este proyecto.")
                    else:
                        st.info("Base de datos de técnicos vacía.")

                    st.markdown("<br>", unsafe_allow_html=True)
                    cg1, cg2 = st.columns([1, 1.5])
                    
                    with cg1:
                        df_dias_comp = pd.DataFrame({
                            "Concepto": ["Días Vendidos (Plan)", "Días Reales (Ejecutadas)"],
                            "Días": [d_p, d_e]
                        })
                        color_real = "#E74C3C" if d_e > d_p else "#2ECC71"
                        fig_bar_d = px.bar(
                            df_dias_comp, x="Concepto", y="Días", color="Concepto", text="Días",
                            color_discrete_map={"Días Vendidos (Plan)": "#3498DB", "Días Reales (Ejecutadas)": color_real},
                            title="Balance de Días (Vendidos vs Reales)"
                        )
                        fig_bar_d.update_traces(texttemplate='%{text:.1f} Días', textposition='outside')
                        fig_bar_d.update_layout(yaxis_title="Cantidad de Días-Hombre", showlegend=False, plot_bgcolor='white', height=350, margin=dict(l=20, r=20, t=50, b=20))
                        max_d = max(d_p, d_e)
                        fig_bar_d.update_yaxes(range=[0, max_d * 1.2])
                        st.plotly_chart(fig_bar_d, use_container_width=True)

                        st.markdown("**📝 Comentarios y Detalles de Ejecución**")
                        if asig_all_raw:
                            df_comentarios = pd.DataFrame(asig_all_raw)
                            df_comentarios = df_comentarios[(df_comentarios['id_nv'] == row_nv['id_nv']) & (df_comentarios['actividad_ssee'] != 'PROYECCION_GLOBAL')]
                            if not df_comentarios.empty:
                                df_comentarios['actividad_ssee'] = df_comentarios['actividad_ssee'].fillna("Labor en Terreno")
                                has_extra_cols = 'dias_extras' in df_comentarios.columns
                                if has_extra_cols:
                                    df_comentarios['dias_extras'] = pd.to_numeric(df_comentarios['dias_extras'], errors='coerce').fillna(0)
                                    df_comentarios['justificacion'] = df_comentarios['justificacion'].fillna("")
                                    comentarios_unicos = df_comentarios.groupby(['actividad_ssee', 'comentarios', 'justificacion']).agg({'progreso':'max', 'dias_extras':'max'}).reset_index()
                                else:
                                    comentarios_unicos = df_comentarios.groupby(['actividad_ssee', 'comentarios'])['progreso'].max().reset_index()
                                    
                                for _, row_c in comentarios_unicos.iterrows():
                                    act_name = row_c['actividad_ssee']
                                    com_text = row_c['comentarios'] if pd.notna(row_c['comentarios']) and str(row_c['comentarios']).strip() else "Sin comentarios registrados."
                                    prog_val = int(row_c['progreso'])
                                    
                                    if com_text in ["LIBRES", "EXTRAS", "SIN_PROGRAMAR"]:
                                        if com_text == "SIN_PROGRAMAR":
                                            com_text = "Estado operativo: SIN INICIAR"
                                        else:
                                            com_text = f"Estado operativo: {com_text.replace('_', ' ')}"
                                            
                                    is_task_paused = "[PAUSADA]" in str(row_c.get('justificacion', '')).upper()
                                    just_display = str(row_c.get('justificacion', '')).replace("[PAUSADA] ", "").replace("[PAUSADA]", "").strip()
                                    
                                    if is_task_paused:
                                        com_text = f"⏸️ **PAUSADA** - Motivo: {just_display}"
                                    elif has_extra_cols and row_c['dias_extras'] > 0:
                                        com_text += f" | ⚠️ **+{int(row_c['dias_extras'])} días extra** (Motivo: {just_display})"
                                        
                                    st.info(f"**{act_name} ({prog_val}%):** {com_text}")
                            else:
                                st.write("No hay labores registradas para mostrar comentarios.")
                        else:
                            st.write("Base de datos vacía.")

                    with cg2:
                        st.markdown("**Auditoría Detallada de Gastos Operativos**")
                        df_detalles = df_gastos_full[df_gastos_full['id_nv'] == row_nv['id_nv']]
                        if not df_detalles.empty:
                            df_det_display = df_detalles[['fecha_gasto', 'tipo_gasto', 'monto_gasto']].copy()
                            df_det_display.rename(columns={'fecha_gasto': 'Fecha', 'tipo_gasto': 'Ítem', 'monto_gasto': 'Monto (CLP)'}, inplace=True)
                            if mon == 'USD':
                                df_det_display['Equivalente (USD)'] = df_det_display['Monto (CLP)'] / tasa_cambio
                                df_det_display['Equivalente (USD)'] = df_det_display['Equivalente (USD)'].apply(lambda x: f"USD ${x:,.2f}")
                            df_det_display['Monto (CLP)'] = df_det_display['Monto (CLP)'].apply(lambda x: f"CLP ${x:,.0f}".replace(",", "."))
                            st.dataframe(df_det_display, use_container_width=True, hide_index=True)
                        else:
                            st.info("Sin gastos registrados.")

            # --- NUEVA PESTAÑA: OCUPACIÓN DE PERSONAL ---
            with tab_ocupacion:
                st.subheader("👥 Ocupación de Personal por Mes")
                st.info("Esta herramienta calcula qué porcentaje del mes cada técnico estuvo ocupado en terreno, descontando sus días de ausencia/vacaciones.")
                
                c_oc1, c_oc2 = st.columns(2)
                mes_sel_oc = c_oc1.selectbox("Mes:", list(MESES_ES.values()), index=mes_actual-1, key="mes_oc")
                anio_sel_oc = c_oc2.selectbox("Año:", lista_anios, index=lista_anios.index(año_actual), key="anio_oc")
                mes_num_oc = list(MESES_ES.keys())[list(MESES_ES.values()).index(mes_sel_oc)]
                
                _, ultimo_dia_oc = calendar.monthrange(anio_sel_oc, mes_num_oc)
                fecha_inicio_oc = datetime(anio_sel_oc, mes_num_oc, 1).date()
                fecha_fin_oc = datetime(anio_sel_oc, mes_num_oc, ultimo_dia_oc).date()
                
                dias_del_mes = [fecha_inicio_oc + timedelta(days=i) for i in range((fecha_fin_oc - fecha_inicio_oc).days + 1)]
                dias_habiles_totales = sum(1 for d in dias_del_mes if d.weekday() < 5 and d.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026)
                
                data_ocupacion = []
                
                for esp in ESPECIALISTAS:
                    dias_ocupados = 0
                    dias_ausente = 0
                    
                    asigs_esp = [a for a in asig_all_raw if a.get('especialista') == esp] if asig_all_raw else []
                    
                    for d in dias_del_mes:
                        es_feriado = d.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
                        es_finde = d.weekday() >= 5
                        
                        estado_dia = "Disponible" if not (es_finde or es_feriado) else "Libre"
                        
                        for a in asigs_esp:
                            try:
                                f_i = pd.to_datetime(a['fecha_inicio']).date()
                                f_f = pd.to_datetime(a['fecha_fin']).date()
                            except:
                                continue
                                
                            if f_i <= d <= f_f:
                                incluye_f = (a.get('comentarios') == 'EXTRAS' or 'Extras' in str(a.get('comentarios','')))
                                if not incluye_f and (es_finde or es_feriado):
                                    continue
                                
                                if a.get('id_nv') == 'AUSENCIA':
                                    estado_dia = "Ausente"
                                    break 
                                elif a.get('comentarios') != 'SIN_PROGRAMAR':
                                    estado_dia = "Ocupado"
                        
                        if estado_dia == "Ocupado":
                            dias_ocupados += 1
                        elif estado_dia == "Ausente":
                            dias_ausente += 1
                            
                    dias_libres_habiles = 0
                    for d in dias_del_mes:
                        es_feriado = d.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
                        es_finde = d.weekday() >= 5
                        if not (es_finde or es_feriado):
                            ocupado_o_ausente = False
                            for a in asigs_esp:
                                try:
                                    f_i = pd.to_datetime(a['fecha_inicio']).date()
                                    f_f = pd.to_datetime(a['fecha_fin']).date()
                                except:
                                    continue
                                if f_i <= d <= f_f:
                                    incluye_f = (a.get('comentarios') == 'EXTRAS' or 'Extras' in str(a.get('comentarios','')))
                                    if a.get('comentarios') != 'SIN_PROGRAMAR':
                                        ocupado_o_ausente = True
                                        break
                            if not ocupado_o_ausente:
                                dias_libres_habiles += 1

                    pct_ocupacion = (dias_ocupados / dias_habiles_totales * 100) if dias_habiles_totales > 0 else 0
                    
                    data_ocupacion.append({
                        "Especialista": esp,
                        "Días Ocupado": dias_ocupados,
                        "Días Ausente": dias_ausente,
                        "Días Disponibles (Hábiles)": dias_libres_habiles,
                        "% Ocupación Real": round(pct_ocupacion, 1)
                    })
                
                df_oc = pd.DataFrame(data_ocupacion)
                df_oc_sorted = df_oc.sort_values(by="% Ocupación Real", ascending=False)
                
                fig_oc = px.bar(
                    df_oc_sorted, 
                    x="Especialista", 
                    y=["Días Ocupado", "Días Ausente", "Días Disponibles (Hábiles)"],
                    title=f"Distribución de Tiempos por Técnico - {mes_sel_oc} {anio_sel_oc}",
                    color_discrete_map={
                        "Días Ocupado": "#3498DB", 
                        "Días Ausente": "#E74C3C", 
                        "Días Disponibles (Hábiles)": "#2ECC71"
                    }
                )
                fig_oc.update_layout(yaxis_title="Cantidad de Días en el Mes", plot_bgcolor='white', barmode='stack', legend_title_text="Estado")
                st.plotly_chart(fig_oc, use_container_width=True)
                
                st.markdown("**Tabla Detallada de Ocupación**")
                
                df_oc_sorted['% Ocupación Real'] = df_oc_sorted['% Ocupación Real'].apply(lambda x: f"{x:.1f}%")
                st.dataframe(df_oc_sorted, use_container_width=True, hide_index=True)

            # --- NUEVA PESTAÑA: TABLA GENERAL Y FACTURACIÓN POR PARCIALIDADES (HITOS) ---
            with tab_tabla:
                st.subheader("Tabla General y Control de Facturación Mensual")
                
                c_tbl1, c_tbl2 = st.columns(2)
                mes_sel_t = c_tbl1.selectbox("Filtrar por Mes:", list(MESES_ES.values()), index=mes_actual-1, key="mes_tbl")
                anio_sel_t = c_tbl2.selectbox("Filtrar por Año:", lista_anios, index=lista_anios.index(año_actual), key="anio_tbl")
                mes_num_t = list(MESES_ES.keys())[list(MESES_ES.values()).index(mes_sel_t)]
                
                st.markdown(f"### 💸 1. Pronóstico de Facturación para {mes_sel_t} {anio_sel_t}")
                st.info("Visualiza las parcialidades (hitos) programadas, y las ejecuciones automáticas de este mes.")
                
                df_hitos_mes = pd.DataFrame()
                if not df_hitos.empty:
                    df_hitos_mes = df_hitos[(df_hitos['mes'] == mes_num_t) & (df_hitos['anio'] == anio_sel_t)].copy()
                    if not df_hitos_mes.empty:
                        df_hitos_mes = df_hitos_mes.merge(df_kpi[['id_nv', 'cliente', 'tipo_servicio', 'moneda', 'monto_vendido', 'monto_pendiente']], on='id_nv', how='left')
                        df_hitos_mes['monto_usd'] = df_hitos_mes.apply(lambda r: r['monto'] if r['moneda'] == 'USD' else r['monto'] / tasa_cambio, axis=1)
                
                if df_hitos_mes.empty:
                    df_hitos_mes = pd.DataFrame(columns=['id', 'id_nv', 'cliente', 'tipo_servicio', 'moneda', 'porcentaje', 'monto', 'estado', 'monto_usd'])

                # --- PRONÓSTICO AUTOMÁTICO DE EJECUCIÓN ---
                df_all_valid_asig = pd.DataFrame()
                if asig_all_raw:
                    df_temp_asig = pd.DataFrame(asig_all_raw)
                    # Incluimos PROYECCION_GLOBAL para detectar fechas recién creadas en Comercial
                    df_all_valid_asig = df_temp_asig[(df_temp_asig['id_nv'] != 'AUSENCIA') & (df_temp_asig['comentarios'] != 'SIN_PROGRAMAR')]

                if not df_all_valid_asig.empty:
                    df_max_fin = df_all_valid_asig.groupby('id_nv')['fecha_fin'].max().reset_index()
                    df_max_fin['fecha_fin'] = pd.to_datetime(df_max_fin['fecha_fin']).dt.date
                    df_kpi_auto = df_kpi.merge(df_max_fin, on='id_nv', how='inner')
                    
                    mask_auto = (pd.to_datetime(df_kpi_auto['fecha_fin']).dt.month == mes_num_t) & (pd.to_datetime(df_kpi_auto['fecha_fin']).dt.year == anio_sel_t)
                    nvs_auto = df_kpi_auto[mask_auto]
                    
                    nuevas_filas = []
                    for _, r_auto in nvs_auto.iterrows():
                        has_hitos_ever = not df_hitos[df_hitos['id_nv'] == r_auto['id_nv']].empty
                        if not has_hitos_ever and r_auto['estado_facturacion'] != 'Facturada':
                            monto_pend = r_auto['monto_pendiente']
                            if monto_pend > 0:
                                m_usd = monto_pend if r_auto['moneda'] == 'USD' else monto_pend / tasa_cambio
                                nuevas_filas.append({
                                    'id': 'Auto',
                                    'id_nv': r_auto['id_nv'],
                                    'cliente': r_auto['cliente'],
                                    'tipo_servicio': r_auto['tipo_servicio'],
                                    'moneda': r_auto['moneda'],
                                    'porcentaje': 100.0,
                                    'monto': monto_pend,
                                    'estado': 'Pronóstico Automático (Ejec. este mes)',
                                    'monto_usd': m_usd
                                })
                    if nuevas_filas:
                        df_hitos_mes = pd.concat([df_hitos_mes, pd.DataFrame(nuevas_filas)], ignore_index=True)

                if not df_hitos_mes.empty:
                    tot_fact_est_usd = df_hitos_mes['monto_usd'].sum()
                    tot_fact_est_clp = tot_fact_est_usd * tasa_cambio
                    
                    str_tot_usd = f"USD ${tot_fact_est_usd:,.2f}"
                    str_tot_clp = f"CLP ${tot_fact_est_clp:,.0f}".replace(",", ".")
                    
                    st.markdown("#### 🌟 Resumen Global del Mes")
                    c_met1, c_met2 = st.columns(2)
                    c_met1.metric("Total Pronosticado Global (USD)", str_tot_usd)
                    c_met2.metric("Total Pronosticado Global (CLP)", str_tot_clp)
                    st.divider()
                    
                    def mostrar_tabla_servicio(df_sub, titulo):
                        if df_sub.empty:
                            return
                        st.markdown(f"#### {titulo}")
                        
                        sub_tot_usd = df_sub['monto_usd'].sum()
                        sub_tot_clp = sub_tot_usd * tasa_cambio
                        s_tot_usd = f"USD ${sub_tot_usd:,.2f}"
                        s_tot_clp = f"CLP ${sub_tot_clp:,.0f}".replace(",", ".")
                        
                        df_show = df_sub[['id', 'id_nv', 'cliente', 'moneda', 'porcentaje', 'monto', 'estado']].copy()
                        df_show['porcentaje'] = df_show['porcentaje'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) and isinstance(x, (int, float)) else x)
                        
                        texto_total = f"{s_tot_usd}   /   {s_tot_clp}"
                        total_row = pd.DataFrame([{
                            'id': '', 'id_nv': 'TOTALES', 'cliente': '', 'moneda': 'USD / CLP', 
                            'porcentaje': '', 'monto': texto_total, 'estado': ''
                        }])
                        df_show = pd.concat([df_show, total_row], ignore_index=True)
                        
                        def format_monto(val, mon, id_val):
                            if pd.isna(val) or val == '': return ''
                            if isinstance(val, str) and ('/' in val or 'USD' in val or 'CLP' in val): 
                                return val 
                            try:
                                v = float(val)
                            except Exception:
                                return val
                            if mon == 'USD': return f"USD ${v:,.2f}"
                            return f"CLP ${v:,.0f}".replace(",", ".")
                            
                        df_show['Monto Parcial'] = df_show.apply(lambda x: format_monto(x['monto'], x['moneda'], x['id']), axis=1)
                        df_show.drop(columns=['monto'], inplace=True)
                        df_show.rename(columns={'id_nv':'NV', 'cliente':'Cliente', 'moneda':'Moneda', 'porcentaje':'% Calculado', 'estado':'Estado Factura'}, inplace=True)
                        
                        def style_total_row(row):
                            if row['NV'] == 'TOTALES':
                                return ['background-color: #003366; color: white; font-weight: bold'] * len(row)
                            elif 'Auto' in str(row['Estado Factura']):
                                return ['background-color: #E8F8F5; font-style: italic'] * len(row)
                            return [''] * len(row)
                            
                        st.dataframe(df_show.style.apply(style_total_row, axis=1), use_container_width=True, hide_index=True)

                    df_ssee = df_hitos_mes[df_hitos_mes['tipo_servicio'] == 'SSEE']
                    df_terreno = df_hitos_mes[df_hitos_mes['tipo_servicio'] == 'SE TERRENO']
                    
                    mostrar_tabla_servicio(df_ssee, "🔹 Facturación SSEE (Subestaciones)")
                    mostrar_tabla_servicio(df_terreno, "🔸 Facturación SE TERRENO (Faenas)")
                    
                    with st.expander("🔄 Actualizar Estado de una Factura del mes"):
                        hitos_reales = df_hitos_mes[df_hitos_mes['id'].astype(str).str.isnumeric()]
                        if not hitos_reales.empty:
                            c_up1, c_up2 = st.columns(2)
                            id_h_up = c_up1.selectbox("Seleccione el ID de la Parcialidad:", hitos_reales['id'].tolist())
                            nuevo_est_h = c_up2.selectbox("Nuevo Estado:", ["Pendiente", "Facturada", "Postergada"])
                            if st.button("Actualizar Hito", use_container_width=True):
                                try:
                                    supabase.table("hitos_facturacion").update({"estado": nuevo_est_h}).eq("id", id_h_up).execute()
                                    st.success(f"Hito {id_h_up} actualizado a {nuevo_est_h}.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al actualizar: {e}")
                        else:
                            st.info("Los pronósticos automáticos se volverán facturas reales cuando crees sus hitos manualmente abajo.")
                else:
                    st.write("No hay parcialidades de facturación programadas para este mes ni ejecuciones automáticas detectadas.")
                
                st.divider()
                st.markdown("### ⚙️ 2. Administrar Parcialidades por Proyecto")
                with st.expander("Crear y revisar hitos de cobro de una NV específica", expanded=True):
                    nv_hitos_sel = st.selectbox("Seleccione Proyecto para planificar:", df_kpi['Proyecto_Label'].tolist())
                    if nv_hitos_sel:
                        row_h = df_kpi[df_kpi['Proyecto_Label'] == nv_hitos_sel].iloc[0]
                        id_nv_h = row_h['id_nv']
                        monto_tot_h = float(row_h['monto_vendido'])
                        moneda_h = row_h['moneda']
                        
                        df_hitos_nv = df_hitos[df_hitos['id_nv'] == id_nv_h]
                        
                        monto_planeado = float(df_hitos_nv['monto'].sum()) if not df_hitos_nv.empty else 0.0
                        monto_restante = monto_tot_h - monto_planeado
                        
                        pct_planeado_real = (monto_planeado / monto_tot_h * 100) if monto_tot_h > 0 else 0.0
                        pct_restante_real = 100.0 - pct_planeado_real
                        
                        m_tot_str = f"{moneda_h} ${monto_tot_h:,.0f}".replace(",", ".") if moneda_h == 'CLP' else f"{moneda_h} ${monto_tot_h:,.2f}"
                        m_res_str = f"{moneda_h} ${monto_restante:,.0f}".replace(",", ".") if moneda_h == 'CLP' else f"{moneda_h} ${monto_restante:,.2f}"
                        
                        st.write(f"**Monto Total Proyecto:** {m_tot_str} | **Monto Restante:** {m_res_str}")
                        st.write(f"**Planificado:** {pct_planeado_real:.1f}% | **Por Planificar:** {pct_restante_real:.1f}%")
                        
                        if not df_hitos_nv.empty:
                            df_hnv_show = df_hitos_nv[['id', 'mes', 'anio', 'porcentaje', 'monto', 'estado']].copy()
                            df_hnv_show['mes'] = df_hnv_show['mes'].apply(lambda x: MESES_ES.get(x, x))
                            df_hnv_show['porcentaje'] = df_hnv_show['porcentaje'].apply(lambda x: f"{x:.1f}% del Total")
                            
                            if moneda_h == 'CLP':
                                df_hnv_show['monto'] = df_hnv_show['monto'].apply(lambda x: f"CLP ${x:,.0f}".replace(",", "."))
                            else:
                                df_hnv_show['monto'] = df_hnv_show['monto'].apply(lambda x: f"USD ${x:,.2f}")
                                
                            df_hnv_show.rename(columns={'id':'ID', 'mes':'Mes', 'anio':'Año', 'porcentaje':'% Calculado', 'monto':'Monto Parcial', 'estado':'Estado Factura'}, inplace=True)
                            
                            st.dataframe(df_hnv_show, use_container_width=True, hide_index=True)
                            
                            st.markdown("**Opciones de Edición de Hitos:**")
                            c_del1, c_del2 = st.columns(2)
                            
                            with c_del1:
                                with st.form("form_del_individual"):
                                    id_del = st.selectbox("Seleccione ID de Parcialidad a eliminar", df_hnv_show['ID'].tolist())
                                    submit_del = st.form_submit_button("🗑️ Eliminar Solo Este Hito")
                                    if submit_del:
                                        try:
                                            supabase.table("hitos_facturacion").delete().eq("id", id_del).execute()
                                            st.success(f"Hito {id_del} eliminado correctamente.")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error al eliminar: {e}")
                                            
                            with c_del2:
                                st.write("") 
                                st.write("") 
                                if st.button("🗑️ Borrar TODOS los hitos de esta NV", type="secondary", use_container_width=True):
                                    try:
                                        supabase.table("hitos_facturacion").delete().eq("id_nv", id_nv_h).execute()
                                        st.success("Todos los hitos eliminados. Puede volver a planificar.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error("Error al eliminar hitos.")
                            
                        if round(monto_restante, 2) > 0:
                            st.divider()
                            st.markdown(f"**Añadir nueva parcialidad sobre el saldo restante ({m_res_str}):**")
                            
                            modo_ingreso = st.radio("Definir la parcialidad por:", ["Porcentaje del Saldo (%)", "Monto Exacto"], horizontal=True)
                            
                            with st.form("form_add_hito"):
                                c_hm, c_ha, c_hp = st.columns(3)
                                h_mes = c_hm.selectbox("Mes de Facturación", list(MESES_ES.values()))
                                h_anio = c_ha.selectbox("Año", lista_anios, index=lista_anios.index(año_actual))
                                
                                if modo_ingreso == "Porcentaje del Saldo (%)":
                                    h_val = c_hp.number_input("Porcentaje (%) a cobrar", min_value=0.1, max_value=100.0, step=1.0, value=100.0)
                                else:
                                    if moneda_h == 'CLP':
                                        h_val = c_hp.text_input("Monto a cobrar (CLP)", value=f"{int(monto_restante)}", help="Puede usar puntos para miles.")
                                    else:
                                        h_val = c_hp.number_input("Monto a cobrar (USD)", min_value=0.01, max_value=float(monto_restante), step=100.0, value=float(monto_restante))
                                
                                if st.form_submit_button("Agregar Hito de Cobro", use_container_width=True):
                                    mes_n = list(MESES_ES.keys())[list(MESES_ES.values()).index(h_mes)]
                                    
                                    monto_calc = 0.0
                                    if modo_ingreso == "Porcentaje del Saldo (%)":
                                        monto_calc = (h_val / 100.0) * monto_restante
                                    else:
                                        if moneda_h == 'CLP':
                                            m_clean = str(h_val).replace(".", "").replace(",", "").strip()
                                            monto_calc = float(m_clean) if m_clean.isdigit() else 0.0
                                        else:
                                            monto_calc = float(h_val)
                                    
                                    if round(monto_calc, 2) > round(monto_restante, 2):
                                        st.error(f"❌ El monto calculado ({monto_calc:,.2f}) supera el saldo restante permitido ({monto_restante:,.2f}).")
                                    elif monto_calc <= 0:
                                        st.error("❌ El monto debe ser mayor a 0.")
                                    else:
                                        pct_sobre_total = (monto_calc / monto_tot_h) * 100 if monto_tot_h > 0 else 0
                                        
                                        try:
                                            supabase.table("hitos_facturacion").insert({
                                                "id_nv": id_nv_h,
                                                "mes": mes_n,
                                                "anio": h_anio,
                                                "porcentaje": pct_sobre_total,
                                                "monto": monto_calc,
                                                "estado": "Pendiente"
                                            }).execute()
                                            st.success("Hito de facturación agregado exitosamente.")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"❌ Error de BD: {e}")
                        else:
                            st.success("✅ El 100% de este proyecto ya ha sido planificado en hitos.")

            with tab_pendientes:
                st.subheader("Servicios Pendientes (Backlog de Facturación y Ejecución)")
                st.info("Aquí se listan todos los proyectos que tienen un saldo pendiente por facturar, descontando automáticamente las parcialidades ya facturadas.")
                
                df_pendientes = df_kpi[df_kpi['monto_pendiente'] > 0].copy()
                
                if not df_pendientes.empty:
                    df_pendientes['monto_usd_est'] = df_pendientes.apply(lambda row: row['monto_pendiente'] if row['moneda'] == 'USD' else row['monto_pendiente'] / tasa_cambio, axis=1)
                    total_pendiente_usd = df_pendientes['monto_usd_est'].sum()
                    
                    st.metric("Total Cartera Pendiente (Equivalente USD)", f"USD ${total_pendiente_usd:,.2f}")
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    cols_pend = ['id_nv', 'cliente', 'tipo_servicio', 'moneda', 'monto_vendido', 'monto_pendiente', 'estado_facturacion']
                    df_pend_display = df_pendientes[cols_pend].rename(columns={
                        'id_nv': 'NV', 'cliente': 'Cliente', 'tipo_servicio': 'Tipo', 
                        'moneda': 'Moneda', 'monto_vendido': 'Monto Ofertado Original',
                        'monto_pendiente': 'Saldo Pendiente', 'estado_facturacion': 'Estado General'
                    })
                    
                    def format_currency_backlog(val, mon):
                        try:
                            v = float(val)
                        except Exception:
                            return val
                        if mon == 'USD':
                            return f"USD ${v:,.2f}"
                        return f"CLP ${v:,.0f}".replace(",", ".")
                        
                    df_pend_display['Monto Ofertado Original'] = df_pend_display.apply(lambda x: format_currency_backlog(x['Monto Ofertado Original'], x['Moneda']), axis=1)
                    df_pend_display['Saldo Pendiente'] = df_pend_display.apply(lambda x: format_currency_backlog(x['Saldo Pendiente'], x['Moneda']), axis=1)

                    st.dataframe(df_pend_display, use_container_width=True, hide_index=True)
                else:
                    st.success("✨ ¡Excelente! No hay servicios con saldo pendiente en tu Backlog.")

    # ==========================================
    # MÓDULO 5: CIERRE Y PDF ANALÍTICO
    # ==========================================
    with tab5:
        st.header("Cierre Técnico y Reporte")
        if 'pdf_bytes' not in st.session_state: st.session_state.pdf_bytes = None
        if 'nv_cerrada' not in st.session_state: st.session_state.nv_cerrada = None

        if nvs_activas:
            nv_c_label = st.selectbox("Proyecto para Cerrar", [f"{n['id_nv']} - {n['cliente']}" for n in nvs_activas])
            nv_c_id = nv_c_label.split(" - ")[0]

            if st.button("🔴 CERRAR Y GENERAR REPORTE PDF"):
                try:
                    info_nv = next(n for n in nvs_activas if n['id_nv'] == nv_c_id)
                    asig_list_raw = supabase.table("asignaciones_personal").select("*").eq("id_nv", nv_c_id).execute().data
                    
                    asig_list = [a for a in asig_list_raw if a.get('actividad_ssee') != 'PROYECCION_GLOBAL'] if asig_list_raw else []
                    
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

                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", 'B', 20)
                    pdf.set_text_color(0, 51, 102)
                    pdf.cell(0, 15, "REPORTE EJECUTIVO DE CIERRE - COORDINACIÓN FPS", ln=True, align='C')
                    pdf.ln(5)
                    
                    # Formateo correcto en PDF (puntos para CLP)
                    fmt_v_pdf = f"{info_nv['monto_vendido']:,.0f}".replace(",", ".") if moneda == 'CLP' else f"{info_nv['monto_vendido']:,.2f}"
                    fmt_g_pdf = f"{sum_gas_real:,.0f}".replace(",", ".") if moneda == 'CLP' else f"{sum_gas_real:,.2f}"
                    
                    pdf.set_font("Arial", '', 12)
                    pdf.set_text_color(0, 0, 0)
                    pdf.cell(0, 10, f"Proyecto: {nv_c_id} | Cliente: {info_nv['cliente']}", ln=True)
                    pdf.cell(0, 10, f"Lugar: {info_nv['lugar']} | Avance Final: {avg_prog:.1f}%", ln=True)
                    pdf.cell(0, 10, f"Días Ofertados: {dias_ofertados} | Días Ejecutados (Aprox): {dias_ejecutados:.1f}", ln=True)
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
                            linea = f"> {act} ({prog}%) | Técnicos: {esp_list}"
                            pdf.cell(0, 8, linea.encode('latin-1', 'replace').decode('latin-1'), ln=True)
                    
                    st.session_state.pdf_bytes = pdf.output(dest='S').encode('latin-1', 'replace')
                    st.session_state.nv_cerrada = nv_c_id
                    os.remove(path_img)
                    
                    supabase.table("notas_venta").update({"estado":"Cerrada"}).eq("id_nv", nv_c_id).execute()
                    st.success("✅ Proyecto cerrado exitosamente.")
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
