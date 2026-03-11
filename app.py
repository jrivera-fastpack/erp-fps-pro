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
    st.error("Error crítico: No se pudo conectar a la base de datos Supabase.")
    st.stop()

# --- INICIALIZACIÓN DE PROYECTO INTERNO DE RRHH ---
try:
    aus_nv = supabase.table("notas_venta").select("id_nv").eq("id_nv", "AUSENCIA").execute()
    if not aus_nv.data:
        supabase.table("notas_venta").insert({
            "id_nv": "AUSENCIA", "cliente": "Gestión Interna (RRHH)", "tipo_servicio": "SE TERRENO", 
            "lugar": "Oficina/Casa", "moneda": "CLP", "monto_vendido": 0.0, 
            "hh_vendidas": 0.0, "estado": "Abierta"
        }).execute()
except Exception:
    pass

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

# --- FUNCIONES AUXILIARES CORREGIDAS (CÁLCULOS EXACTOS) ---
def calcular_fecha_fin_dinamica(f_ini, dias_totales, incluye_finde):
    if dias_totales <= 0:
        return f_ini
        
    dias_contados = 0
    fecha_actual = f_ini
    
    while dias_contados < dias_totales:
        es_feriado = fecha_actual.strftime("%d-%m-%Y") in FERIADOS_CHILE_2026
        es_finde = fecha_actual.weekday() >= 5
        
        if not incluye_finde:
            # Si el equipo descansa findes/feriados, solo contamos si es un día hábil real
            if not es_finde and not es_feriado:
                dias_contados += 1
        else:
            # Si el equipo trabaja continuo (EXTRAS), cada día calendario cuenta como avance
            dias_contados += 1
            
        if dias_contados < dias_totales:
            fecha_actual += timedelta(days=1)
            
    return fecha_actual

def calcular_hh_ssee(f_ini, f_fin, incluye_finde=False):
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
        
        # Si no están programados para trabajar findes/feriados, ese día suma 0 horas
        if not incluye_finde and (es_finde or es_feriado):
            continue 
            
        # Días contabilizables: Lunes a Jueves (9.5), Viernes (8.5), Extras en Sáb/Dom/Feriado (9.5)
        if dia_semana < 4: 
            hh += 9.5
        elif dia_semana == 4: 
            hh += 8.5
        else: 
            hh += 9.5 
            
    return hh

def obtener_nvs(estado_filter=None):
    query = supabase.table("notas_venta").select("*").neq("id_nv", "AUSENCIA")
    if estado_filter: query = query.eq("estado", estado_filter)
    return query.execute().data

# --- CONTROL DE SESIÓN (AUTENTICACIÓN) ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'user_email' not in st.session_state:
    st.session_state.user_email = ""

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
                        # Autenticación contra el backend de Supabase
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

# --- APLICACIÓN PRINCIPAL (SOLO ACCESIBLE SI ESTÁ AUTENTICADO) ---
def main_app():
    # --- BARRA LATERAL ---
    # Logotipo generado con HTML/CSS usando los colores corporativos de FASTPACK
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
            with st.form("form_comercial"):
                st.subheader("Crear Nueva Nota de Venta")
                c1, c2, c3 = st.columns(3)
                id_nv = c1.text_input("ID Nota de Venta")
                cliente = c1.text_input("Cliente")
                tipo = c2.selectbox("Tipo de Servicio", ["SSEE", "SE TERRENO"])
                lugar = c2.text_input("Lugar / Faena")
                col_mon, col_mnt = c3.columns([1, 2])
                moneda = col_mon.selectbox("Moneda", ["CLP", "USD"])
                monto = col_mnt.number_input("Monto Ofertado", min_value=0.0, step=0.001, format="%.3f")
                
                st.divider()
                st.markdown("### Proyección en Matriz Semanal (Opcional)")
                st.info("Ingresa los días de duración del servicio. Si ya conoces la fecha de inicio y cuadrilla, puedes establecerla ahora para enviarla a la Matriz Semanal.")
                
                c4, c5, c6 = st.columns(3)
                dias_v = c4.number_input("Días Vendidos (Duración)", min_value=0.0, step=1.0)
                f_ini = c5.date_input("Fecha de Inicio (Dejar vacío si no aplica)", format="DD/MM/YYYY", value=None)
                especialistas_sel = c6.multiselect("Especialistas Reservados", ESPECIALISTAS)
                incluye_finde = st.radio("¿Considerar fines de semana en esta proyección?", ["No (Saltar Sáb/Dom)", "Sí (Días continuos)"], horizontal=True)

                if st.form_submit_button("Guardar Nota de Venta", use_container_width=True):
                    if id_nv and cliente:
                        try:
                            # BLINDAJE 1: Verificamos si el ID ya existe antes de insertar
                            verificacion = supabase.table("notas_venta").select("id_nv").eq("id_nv", id_nv).execute()
                            if len(verificacion.data) > 0:
                                st.warning(f"⚠️ La Nota de Venta '{id_nv}' ya se encuentra registrada en el sistema.")
                            else:
                                supabase.table("notas_venta").insert({
                                    "id_nv": id_nv, "cliente": cliente, "tipo_servicio": tipo, 
                                    "lugar": lugar, "moneda": moneda, "monto_vendido": monto, 
                                    "hh_vendidas": dias_v, "estado": "Abierta"
                                }).execute()
                                
                                if especialistas_sel and dias_v > 0 and f_ini is not None:
                                    es_continuo = incluye_finde == "Sí (Días continuos)"
                                    f_f = calcular_fecha_fin_dinamica(f_ini, dias_v, es_continuo)
                                    for esp in especialistas_sel:
                                        supabase.table("asignaciones_personal").insert({
                                            "id_nv": id_nv, 
                                            "especialista": esp, 
                                            "fecha_inicio": str(f_ini), 
                                            "fecha_fin": str(f_f), 
                                            "hh_asignadas": 0, 
                                            "actividad_ssee": "PROYECCION_GLOBAL", 
                                            "comentarios": "EXTRAS" if es_continuo else "LIBRES", 
                                            "progreso": 0
                                        }).execute()
                                        
                                st.success(f"✅ NV {id_nv} registrada exitosamente.")
                                st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ocurrió un error al guardar en la base de datos: {e}")
                    else:
                        st.warning("⚠️ Debe ingresar un ID y Cliente válidos.")
        
        with col_admin:
            st.subheader("Administración")
            st.info("Utilice esta opción para eliminar un proyecto completo del sistema. Esto borrará irreversiblemente la Nota de Venta, todas sus asignaciones, horas y gastos asociados.")
            
            nvs_para_borrar = obtener_nvs()
            if nvs_para_borrar:
                opciones_borrar = {f"{n['id_nv']} - {n['cliente']}": n['id_nv'] for n in nvs_para_borrar}
                nv_a_borrar_label = st.selectbox("Seleccione Proyecto a Eliminar", list(opciones_borrar.keys()))
                
                # Checkbox de confirmación para evitar borrados accidentales
                confirmacion_borrado = st.checkbox(f"Estoy seguro que deseo eliminar {nv_a_borrar_label}")
                
                if st.button("🗑️ Eliminar Proyecto Definitivamente", type="secondary"):
                    if confirmacion_borrado:
                        try:
                            id_a_borrar = opciones_borrar[nv_a_borrar_label]
                            # Borramos de la tabla principal (gracias a ON DELETE CASCADE, se borrarán también las asignaciones y gastos)
                            supabase.table("notas_venta").delete().eq("id_nv", id_a_borrar).execute()
                            st.success(f"✅ Proyecto {id_a_borrar} eliminado del sistema.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al intentar eliminar el proyecto: {e}")
                    else:
                        st.warning("Debe confirmar marcando la casilla antes de eliminar.")
            else:
                st.write("No hay proyectos registrados para eliminar.")

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
                                    supabase.table("asignaciones_personal").insert({
                                        "id_nv": nv_data_sel['id_nv'], 
                                        "especialista": esp, 
                                        "fecha_inicio": str(f_ini), 
                                        "fecha_fin": str(f_f), 
                                        "hh_asignadas": 0, 
                                        "actividad_ssee": "PROYECCION_GLOBAL", 
                                        "comentarios": "EXTRAS" if es_continuo else "LIBRES", 
                                        "progreso": 0
                                    }).execute()
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
                                            supabase.table("asignaciones_personal").insert({
                                                "id_nv": "AUSENCIA", 
                                                "especialista": esp, 
                                                "fecha_inicio": str(f_ini_aus), 
                                                "fecha_fin": str(f_fin_aus), 
                                                "hh_asignadas": hh_final, 
                                                "actividad_ssee": f"{tipo_ausencia}" + (f" - {comentario_aus}" if comentario_aus else ""), 
                                                "comentarios": "LIBRES", 
                                                "progreso": 100 
                                            }).execute()
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
                            # Formatear opciones para el selector
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
        
        col_days, _ = st.columns([1, 2])
        dias_a_mostrar = col_days.slider("Días a visualizar", 1, 30, 7)
        hoy = datetime.today().date()
        
        fechas_rango = [hoy + timedelta(days=i) for i in range(dias_a_mostrar)]
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
                
                # 1. Pintar Ausencias Primero
                if a['id_nv'] == 'AUSENCIA':
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        if d in fechas_rango:
                            col = d.strftime("%d-%m-%Y")
                            etiqueta = f"🌴 {a['actividad_ssee']}"
                            matriz_final.at[a['especialista'], col] = etiqueta
                
                # 2. Pintar Proyecciones Globales (No sobreescribir ausencias)
                elif a.get('actividad_ssee') == 'PROYECCION_GLOBAL':
                    trabajo_continuo = (a.get('comentarios') == 'EXTRAS')
                    cliente_nombre = mapa_clientes.get(a['id_nv'], 'Proyectado')
                    
                    for i in range((f_f - f_i).days + 1):
                        d = f_i + timedelta(days=i)
                        if not trabajo_continuo and d.weekday() >= 5:
                            continue
                        if d in fechas_rango:
                            col = d.strftime("%d-%m-%Y")
                            valor_actual = str(matriz_final.at[a['especialista'], col])
                            
                            # Solo escribimos si el técnico NO está de vacaciones/ausente ese día
                            if '🌴' not in valor_actual:
                                etiqueta = f"{a['id_nv']} [{cliente_nombre}]"
                                if valor_actual in ["🟢 Disponible", "⌛ No Hábil"]: 
                                    matriz_final.at[a['especialista'], col] = etiqueta
                                elif etiqueta not in valor_actual: 
                                    matriz_final.at[a['especialista'], col] += f" + {etiqueta}"
        
        matriz_final.columns = nombres_columnas_display
        
        # Función de estilos para pintar la matriz
        def style_matrix(x):
            texto = str(x)
            if 'No Hábil' in texto: return 'background-color: #F0F0F0; color: #A0A0A0'
            if '🌴' in texto: return 'background-color: #FADBD8; color: #C0392B; font-weight: bold' # Rojo claro para ausencias
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
                                        supabase.table("asignaciones_personal").insert({
                                            "id_nv": nv_id_sel, 
                                            "especialista": "Sin Asignar", 
                                            "fecha_inicio": str(datetime.today().date()), 
                                            "fecha_fin": str(datetime.today().date()), 
                                            "hh_asignadas": 0, 
                                            "actividad_ssee": act, 
                                            "comentarios": "SIN_PROGRAMAR", 
                                            "progreso": 0
                                        }).execute()
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
                        
                        for act in actividades_unicas:
                            df_act = df_temp[df_temp['key_grupo'] == act]
                            curr_prog = int(df_act['progreso'].max())
                            
                            esps_reales = [e for e in df_act['especialista'].unique() if e != 'Sin Asignar']
                            estado_programacion = df_act['comentarios'].iloc[0] if not df_act.empty else ""
                            
                            if estado_programacion == "SIN_PROGRAMAR":
                                curr_f_ini = datetime.today().date()
                                dias_estimados = 3
                                is_extras = False
                                estado_badge = "🔴 Sin Fecha"
                            else:
                                curr_f_ini = pd.to_datetime(df_act['fecha_inicio'].min()).date()
                                curr_f_fin = pd.to_datetime(df_act['fecha_fin'].max()).date()
                                dias_estimados = max(1, (curr_f_fin - curr_f_ini).days + 1)
                                is_extras = 'EXTRAS' in df_act['comentarios'].values
                                estado_badge = "🟢 Programado"
                            
                            with st.expander(f"{estado_badge} | 📌 Labor: {act} - Avance: {curr_prog}% | Esp: {len(esps_reales)}"):
                                with st.form(key=f"form_update_{nv_id_sel}_{act}"):
                                    col_p, col_f = st.columns([1, 1.5])
                                    nuevo_p = col_p.slider("Avance Específico %", 0, 100, curr_prog)
                                    f_ini = col_f.date_input("Fecha Inicio", value=curr_f_ini, format="DD/MM/YYYY")
                                    
                                    col_d, col_e = st.columns(2)
                                    dias_trabajo = col_d.number_input("Días de duración", min_value=1, value=dias_estimados)
                                    extras = col_d.radio("Fines de semana", ["Libres (Descanso)", "Extras (Sáb/Dom)"], index=1 if is_extras else 0)
                                    
                                    nuevos_esps = col_e.multiselect("Asignar Especialistas", ESPECIALISTAS, default=esps_reales)
                                    
                                    if st.form_submit_button("Guardar Programación / Avance", use_container_width=True):
                                        try:
                                            supabase.table("asignaciones_personal").delete().eq("id_nv", nv_id_sel).eq("actividad_ssee", act).execute()
                                            
                                            incluye_finde = True if extras == "Extras (Sáb/Dom)" else False
                                            f_f = calcular_fecha_fin_dinamica(f_ini, dias_trabajo, incluye_finde)
                                            hh_final = calcular_hh_ssee(f_ini, f_f, incluye_finde)
                                            
                                            if not nuevos_esps:
                                                supabase.table("asignaciones_personal").insert({
                                                    "id_nv": nv_id_sel, 
                                                    "especialista": "Sin Asignar", 
                                                    "fecha_inicio": str(f_ini), 
                                                    "fecha_fin": str(f_f), 
                                                    "hh_asignadas": 0, 
                                                    "actividad_ssee": act, 
                                                    "comentarios": "EXTRAS" if incluye_finde else "LIBRES", 
                                                    "progreso": nuevo_p
                                                }).execute()
                                            else:
                                                for esp in nuevos_esps:
                                                    supabase.table("asignaciones_personal").insert({
                                                        "id_nv": nv_id_sel, 
                                                        "especialista": esp, 
                                                        "fecha_inicio": str(f_ini), 
                                                        "fecha_fin": str(f_f), 
                                                        "hh_asignadas": hh_final, 
                                                        "actividad_ssee": act, 
                                                        "comentarios": "EXTRAS" if incluye_finde else "LIBRES", 
                                                        "progreso": nuevo_p
                                                    }).execute()
                                                    
                                            st.success("✅ Actividad actualizada en el cronograma.")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"❌ Error al actualizar la tarea en la base de datos: {e}")
                    else:
                        st.info("Utilice el panel de la izquierda para definir las actividades del alcance de este proyecto.")

        st.divider()
        st.subheader("3. Cronograma Operativo (Jornada 08:00 - 17:30)")
        
        vista_gantt = st.radio("Filtro de Vista del Cronograma:", ["🌍 General (Todos los proyectos activos)", "🔍 Por Proyecto Seleccionado"], horizontal=True)

        asig_gantt_raw = supabase.table("asignaciones_personal").select("*").execute().data
        if asig_gantt_raw:
            df_g = pd.DataFrame(asig_gantt_raw)
            df_g = df_g[df_g['actividad_ssee'] != 'PROYECCION_GLOBAL']
            
            if vista_gantt == "🔍 Por Proyecto Seleccionado":
                # Si estamos viendo por proyecto, excluimos las ausencias de RRHH
                df_g = df_g[df_g['id_nv'] == nv_id_sel]
            
            if not df_g.empty:
                nvs_info = {n['id_nv']: n['cliente'] for n in obtener_nvs()}
                nvs_info['AUSENCIA'] = 'Gestión Interna (RRHH)' # Mapeamos la virtualización de ausencias para el Gantt general
                
                df_g['cliente'] = df_g['id_nv'].map(nvs_info)
                df_g['Labor'] = df_g['actividad_ssee'].fillna('Servicio Terreno')
                
                # Asignar horas correctas para inicio y fin de jornada
                df_g['start_ts'] = pd.to_datetime(df_g['fecha_inicio']) + pd.Timedelta(hours=8)
                df_g['end_ts'] = pd.to_datetime(df_g['fecha_fin']) + pd.Timedelta(hours=17, minutes=30)
                
                fechas_validas = df_g[df_g['comentarios'] != 'SIN_PROGRAMAR']['start_ts']
                fecha_base_gantt = fechas_validas.min() if not fechas_validas.empty else (pd.to_datetime(datetime.today().date()) + pd.Timedelta(hours=8))
                
                df_grouped = df_g.groupby(['id_nv', 'cliente', 'Labor', 'start_ts', 'end_ts', 'progreso', 'comentarios']).agg({
                    'especialista': lambda x: ", ".join(set(x))
                }).reset_index()
                
                df_grouped = df_grouped.sort_values(by=['id_nv', 'start_ts'], ascending=[True, True])
                df_grouped['Eje_Y'] = "<b>" + df_grouped['cliente'].str.upper() + " (" + df_grouped['id_nv'] + ")</b><br>" + df_grouped['Labor']
                orden_eje_y = df_grouped['Eje_Y'].unique()
                df_grouped['Etiqueta_Barra'] = df_grouped['Labor'] + " (" + df_grouped['progreso'].astype(str) + "%)"
                
                expanded_rows = []
                for _, row in df_grouped.iterrows():
                    start = row['start_ts']
                    end = row['end_ts']
                    
                    if row['comentarios'] == 'SIN_PROGRAMAR':
                        new_row = row.copy()
                        new_row['start_ts'] = fecha_base_gantt
                        new_row['end_ts'] = fecha_base_gantt + pd.Timedelta(minutes=30)
                        new_row['Inicio'] = "Por definir"
                        new_row['Fin'] = "Por definir"
                        new_row['Etiqueta_Barra'] = "⚠️ SIN FECHA"
                        expanded_rows.append(new_row)
                    elif row['comentarios'] == 'LIBRES':
                        # Lógica para fragmentar las tareas que NO trabajan fin de semana
                        current_chunk_start = start
                        current_day = start.date()
                        end_day = end.date()
                        while current_day <= end_day:
                            if current_day.weekday() == 5: 
                                friday = current_day - pd.Timedelta(days=1)
                                chunk_end = pd.Timestamp.combine(friday, end.time())
                                if current_chunk_start < chunk_end:
                                    new_row = row.copy()
                                    new_row['start_ts'] = current_chunk_start
                                    new_row['end_ts'] = chunk_end
                                    new_row['Inicio'] = current_chunk_start.strftime('%d/%m/%Y %H:%M')
                                    new_row['Fin'] = chunk_end.strftime('%d/%m/%Y %H:%M')
                                    expanded_rows.append(new_row)
                                monday = current_day + pd.Timedelta(days=2)
                                current_chunk_start = pd.Timestamp.combine(monday, start.time())
                            elif current_day == end_day:
                                if current_day.weekday() < 5: 
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

                fig.update_traces(textposition='inside', insidetextanchor='middle', marker_line_width=0, opacity=0.95, width=0.55, textfont=dict(size=13, color='#333333'))
                
                # --- CONFIGURACIÓN DE MÁRGENES Y EJES PARA EVITAR CORTES EN EXPORTACIÓN HTML ---
                fig.update_yaxes(
                    autorange="reversed", 
                    title="", 
                    tickfont=dict(size=13, color='#333'), 
                    gridcolor='rgba(0,0,0,0.05)', 
                    categoryorder='array', 
                    categoryarray=orden_eje_y,
                    automargin=True # Clave para exportación
                )
                
                # --- PINTAR FINES DE SEMANA EN ROJO PERFECTAMENTE ALINEADOS ---
                min_date = df_plot['start_ts'].min()
                max_date = df_plot['end_ts'].max()
                if not pd.isnull(min_date):
                    curr = min_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    # Extendemos la revisión para asegurar que cubra todo el bloque visible
                    while curr <= max_date + pd.Timedelta(days=2):
                        if curr.weekday() == 5: # Detecta el Sábado
                            fig.add_vrect(
                                # Inicia a las 08:00 del Sábado y termina a las 17:30 del Domingo.
                                # Al ocultar las noches, este rectángulo encaja milimétricamente sin dejar huecos.
                                x0=curr.strftime("%Y-%m-%d 08:00:00"), 
                                x1=(curr + timedelta(days=1)).strftime("%Y-%m-%d 17:30:00"),
                                fillcolor="#FADBD8", opacity=0.4, 
                                annotation_text="SÁB / DOM (DESCANSO)", annotation_position="top left",
                                annotation_font_color="#C0392B", annotation_font_size=10,
                                layer="below", line_width=1.5, line_dash="dot", line_color="#E6B0AA"
                            )
                        curr += timedelta(days=1)
                
                # --- LÓGICA DE RESTRICCIÓN HORARIA ---
                breaks = []
                # Solo cortamos las horas fuera de jornada (17:30 a 08:00 del día siguiente)
                # No ocultamos los fines de semana, permitiendo que la caja roja sea visible.
                breaks.append(dict(bounds=[17.5, 8], pattern="hour"))
                
                fig.update_xaxes(
                    dtick=3600000 * 2, # Marcas cada 2 horas
                    tickformat="%H:%M\n%d/%m", 
                    title="Horario Operativo (08:00 - 17:30)", 
                    tickfont=dict(size=12, color='#666'), 
                    gridcolor='rgba(0,0,0,0.05)', 
                    showline=True, linewidth=1, linecolor='rgba(0,0,0,0.2)',
                    rangebreaks=breaks,
                    automargin=True # Clave para exportación
                )
                
                altura_dinamica = max(400, len(orden_eje_y) * 80)
                fig.update_layout(
                    height=altura_dinamica, 
                    margin=dict(l=250, r=30, t=60, b=80), # Márgenes predeterminados ampliados para el HTML
                    plot_bgcolor='white', 
                    paper_bgcolor='white', 
                    legend_title_text='', 
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), 
                    hoverlabel=dict(bgcolor="white", font_size=13, font_family="Arial")
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # --- BOTÓN DE EXPORTACIÓN HTML INTERACTIVO ---
                html_string = fig.to_html(include_plotlyjs='cdn')
                b64 = base64.b64encode(html_string.encode('utf-8')).decode()
                href = f'<a href="data:text/html;base64,{b64}" download="Cronograma_Gantt_FPS.html" style="display: inline-block; padding: 0.5em 1em; background-color: #003366; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; margin-top: 10px;">📥 Descargar Gantt Interactivo (HTML)</a>'
                st.markdown(href, unsafe_allow_html=True)

            else:
                st.info("Aún no hay actividades agregadas al alcance para la vista seleccionada.")

    # ==========================================
    # MÓDULO 4: GASTOS Y KPIs (BI MEJORADO)
    # ==========================================
    with tab4:
        st.header("Análisis de Datos y Control Financiero")
        
        nvs_all = obtener_nvs()
        if not nvs_all:
            st.warning("No hay notas de venta registradas para analizar.")
        else:
            # REGISTRO DE GASTOS
            nvs_activas = obtener_nvs("Abierta")
            if nvs_activas:
                with st.expander("➕ REGISTRAR GASTO OPERATIVO (Siempre en CLP)"):
                    st.info(f"💡 Los gastos se ingresan en Pesos Chilenos (CLP). Si la NV es en dólares, el sistema lo convertirá usando la tasa actual (1 USD = ${tasa_cambio} CLP).")
                    with st.form("form_gastos"):
                        c_g1, c_g2, c_g3, c_g4 = st.columns(4)
                        nv_g_label = c_g1.selectbox("Proyecto Asociado", [f"{n['id_nv']} - {n['cliente']}" for n in nvs_activas])
                        t_g = c_g2.selectbox("Ítem", ["Rendigastos", "Viático", "Hospedaje", "Pasajes", "Insumos"])
                        m_g = c_g3.number_input("Monto del Gasto (CLP)", min_value=0.0, step=1.0)
                        f_gasto = c_g4.date_input("Fecha Gasto", format="DD/MM/YYYY")
                        
                        if st.form_submit_button("Guardar Gasto"):
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

            # PREPARACIÓN DE DATOS MAESTROS PARA BI
            df_nv = pd.DataFrame(nvs_all)
            gastos_raw = supabase.table("control_gastos").select("*").execute().data
            df_gastos_full = pd.DataFrame(gastos_raw) if gastos_raw else pd.DataFrame(columns=['id_nv', 'monto_gasto', 'tipo_gasto', 'fecha_gasto'])
            
            # Agrupación de Gastos (Monto original en CLP)
            df_gas_agg = df_gastos_full.groupby('id_nv')['monto_gasto'].sum().reset_index() if not df_gastos_full.empty else pd.DataFrame(columns=['id_nv', 'monto_gasto'])
            
            # Procesamiento de Horas y Avance Real
            asig_all_raw = supabase.table("asignaciones_personal").select("*").execute().data
            
            df_ausencias = pd.DataFrame()
            df_hh_raw = pd.DataFrame()
            
            if asig_all_raw:
                df_all = pd.DataFrame(asig_all_raw)
                # Separamos el proyecto interno de Ausencias (No afecta rentabilidad ni horas consumidas de clientes)
                df_ausencias = df_all[df_all['id_nv'] == 'AUSENCIA']
                
                # Filtramos proyecciones y tareas sin programar
                df_hh_raw = df_all[(df_all['id_nv'] != 'AUSENCIA') & (df_all['actividad_ssee'] != 'PROYECCION_GLOBAL') & (df_all['comentarios'] != 'SIN_PROGRAMAR')]
                
                if not df_hh_raw.empty:
                    df_hh_agg = df_hh_raw.groupby('id_nv')['hh_asignadas'].sum().reset_index()
                    df_hh_agg['dias_ejecutados'] = df_hh_agg['hh_asignadas'] / 9.0 
                    
                    # CÁLCULO DE AVANCE FÍSICO REAL POR PROYECTO (Promedio sobre total de alcance)
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
                
            # Merge Maestro
            df_kpi = df_nv.merge(df_gas_agg, on='id_nv', how='left').merge(df_hh_agg, on='id_nv', how='left').fillna(0)
            df_kpi.rename(columns={'hh_vendidas': 'dias_proyectados'}, inplace=True)
            df_kpi['id_nv_str'] = df_kpi['id_nv'].astype(str)
            df_kpi['Proyecto_Label'] = df_kpi['id_nv_str'] + " (" + df_kpi['cliente'] + ")"
            
            # Procesamiento de Fechas para el filtro Global
            if 'created_at' in df_kpi.columns:
                df_kpi['fecha_creacion'] = pd.to_datetime(df_kpi['created_at'], errors='coerce').dt.date
                df_kpi['fecha_creacion'] = df_kpi['fecha_creacion'].fillna(datetime.today().date())
            else:
                df_kpi['fecha_creacion'] = datetime.today().date()
                
            min_date_val = df_kpi['fecha_creacion'].min()
            if pd.isnull(min_date_val): min_date_val = datetime.today().date() - timedelta(days=30)
            max_date_val = df_kpi['fecha_creacion'].max()
            if pd.isnull(max_date_val): max_date_val = datetime.today().date()
            
            # Conversión Financiera
            df_kpi['monto_gasto_ajustado'] = df_kpi.apply(lambda row: row['monto_gasto'] / tasa_cambio if row['moneda'] == 'USD' else row['monto_gasto'], axis=1)
            df_kpi['Margen'] = df_kpi['monto_vendido'] - df_kpi['monto_gasto_ajustado']

            # --- SUB PESTAÑAS DE ANÁLISIS ---
            tab_global, tab_individual = st.tabs(["🌍 Dashboard Global Mensual", "🔍 Análisis Detallado por Proyecto"])

            with tab_global:
                st.subheader("Visión Financiera Corporativa Mensual")
                
                # --- FILTROS GLOBALES (AHORA POR MES/AÑO) ---
                c_filt1, c_filt2, c_filt3 = st.columns(3)
                moneda_global = c_filt1.radio("Seleccione Moneda:", ["CLP", "USD"], horizontal=True)
                
                # Selectores de Mes y Año para control estadístico real
                año_actual = datetime.today().year
                mes_actual = datetime.today().month
                lista_anios = list(range(año_actual - 2, año_actual + 2))
                
                mes_sel = c_filt2.selectbox("Seleccione el Mes:", list(MESES_ES.values()), index=mes_actual-1)
                anio_sel = c_filt3.selectbox("Seleccione el Año:", lista_anios, index=lista_anios.index(año_actual))
                
                # Obtener el número del mes seleccionado
                mes_num = list(MESES_ES.keys())[list(MESES_ES.values()).index(mes_sel)]
                
                # Determinar primer y último día del mes seleccionado
                _, ultimo_dia = calendar.monthrange(anio_sel, mes_num)
                fecha_inicio_mes = datetime(anio_sel, mes_num, 1).date()
                fecha_fin_mes = datetime(anio_sel, mes_num, ultimo_dia).date()
                
                # Aplicar filtros (Filtrar proyectos creados en el mes seleccionado)
                df_kpi_moneda = df_kpi[(df_kpi['moneda'] == moneda_global) & (df_kpi['fecha_creacion'] >= fecha_inicio_mes) & (df_kpi['fecha_creacion'] <= fecha_fin_mes)]
                
                # Cálculo de Capacidad Total de Equipo en el Mes (Descontando Fines de semana y feriados)
                dias_habiles_mes = 0
                curr_d = fecha_inicio_mes
                while curr_d <= fecha_fin_mes:
                    if curr_d.weekday() < 5 and curr_d.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026:
                        dias_habiles_mes += 1
                    curr_d += timedelta(days=1)
                
                capacidad_total_teorica = dias_habiles_mes * len(ESPECIALISTAS)
                
                # LÓGICA DE RRHH: Calculamos los días de ausencia específicos que caen dentro de este mes
                dias_ausencia_mes = 0
                if not df_ausencias.empty:
                    for _, row_aus in df_ausencias.iterrows():
                        d_ini = pd.to_datetime(row_aus['fecha_inicio']).date()
                        d_fin = pd.to_datetime(row_aus['fecha_fin']).date()
                        
                        c_date = max(d_ini, fecha_inicio_mes)
                        e_date = min(d_fin, fecha_fin_mes)
                        while c_date <= e_date:
                            # Solo descontamos capacidad si la ausencia ocurrió en un día que originalmente era hábil
                            if c_date.weekday() < 5 and c_date.strftime("%d-%m-%Y") not in FERIADOS_CHILE_2026:
                                dias_ausencia_mes += 1
                            c_date += timedelta(days=1)
                
                capacidad_neta_mes = capacidad_total_teorica - dias_ausencia_mes
                
                if df_kpi_moneda.empty:
                    st.info(f"No hay proyectos registrados operando en {moneda_global} durante {mes_sel} de {anio_sel}.")
                else:
                    total_venta = df_kpi_moneda['monto_vendido'].sum()
                    
                    # MODIFICACIÓN: Siempre sumamos la columna 'monto_gasto' original que está en CLP
                    total_gasto_clp = df_kpi_moneda['monto_gasto'].sum()
                    
                    fmt_tot = f"{moneda_global} ${total_venta:,.0f}" if moneda_global == 'CLP' else f"{moneda_global} ${total_venta:,.3f}"
                    fmt_gas_clp = f"CLP ${total_gasto_clp:,.0f}"
                    
                    col1, col2 = st.columns(2)
                    col1.metric(f"Cartera Ofertada en {mes_sel}", fmt_tot)
                    col2.metric("Ejecución de Gasto Acumulado (CLP)", fmt_gas_clp)
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    c_graf1, c_graf2 = st.columns(2)
                    
                    with c_graf1:
                        total_dias_proyectados = df_kpi_moneda['dias_proyectados'].sum()
                        total_dias_ejecutados = df_kpi_moneda['dias_ejecutados'].sum()
                        df_tiempos = pd.DataFrame({
                            "Concepto": [f"Capacidad Neta Mes ({dias_habiles_mes} hábiles)", "Días Planificados (Vendidos)", "Días Consumidos (Reales)", "Días Ausencia RRHH (Desc.)"],
                            "Cantidad": [capacidad_neta_mes, total_dias_proyectados, total_dias_ejecutados, dias_ausencia_mes]
                        })
                        fig_tiempos = px.bar(
                            df_tiempos, x="Concepto", y="Cantidad", color="Concepto", text="Cantidad",
                            color_discrete_map={
                                f"Capacidad Neta Mes ({dias_habiles_mes} hábiles)": "#95A5A6", 
                                "Días Planificados (Vendidos)": "#3498DB", 
                                "Días Consumidos (Reales)": "#F39C12",
                                "Días Ausencia RRHH (Desc.)": "#E74C3C" # Nuevo pilar rojo para dimensionar el costo operativo del tiempo inactivo
                            },
                            title=f"Balance de Tiempos Operativos y Capacidad de {mes_sel} {anio_sel}"
                        )
                        fig_tiempos.update_traces(texttemplate='%{text:,.1f}', textposition='outside')
                        fig_tiempos.update_layout(yaxis_title="Cantidad de Días", showlegend=False, plot_bgcolor='white')
                        st.plotly_chart(fig_tiempos, use_container_width=True)
                    
                    with c_graf2:
                        df_kpi_moneda_sorted = df_kpi_moneda.sort_values('Avance_%', ascending=True)
                        
                        fig_ranking = px.bar(
                            df_kpi_moneda_sorted, 
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
                    hh_e = row_nv['hh_asignadas']
                    hh_p = d_p * 9.0  # Planificado en HH
                    estado_nv = row_nv['estado']
                    
                    fmt_v = f"{mon} ${m_v:,.0f}" if mon == 'CLP' else f"{mon} ${m_v:,.3f}"
                    fmt_g_clp = f"CLP ${m_g_clp:,.0f}"
                    fmt_m = f"{mon} ${m_m:,.0f}" if mon == 'CLP' else f"{mon} ${m_m:,.3f}"
                    
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
                    
                    holgura_hh = hh_p - hh_e
                    col_m4.metric(
                        "Ejecución de Tiempos (HH)", 
                        f"{hh_e:.1f} Reales / {hh_p:.1f} Plan", 
                        f"{holgura_hh:.1f} HH Restantes", 
                        delta_color="inverse" if holgura_hh < 0 else "normal"
                    )

                    st.markdown("---")
                    
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
                        # NUEVO GRÁFICO: Barras comparativas de Horas (HH)
                        df_hh_comp = pd.DataFrame({
                            "Concepto": ["Horas Vendidas (Plan)", "Horas Reales (Ejecutadas)"],
                            "Horas": [hh_p, hh_e]
                        })
                        
                        # Determinar color de la barra real (rojo si se pasa del plan, verde si está bien)
                        color_real = "#E74C3C" if hh_e > hh_p else "#2ECC71"
                        
                        fig_bar_hh = px.bar(
                            df_hh_comp, 
                            x="Concepto", 
                            y="Horas", 
                            color="Concepto", 
                            text="Horas",
                            color_discrete_map={"Horas Vendidas (Plan)": "#3498DB", "Horas Reales (Ejecutadas)": color_real},
                            title="Balance de Horas (Vendidas vs Reales)"
                        )
                        fig_bar_hh.update_traces(texttemplate='%{text:.1f} HH', textposition='outside')
                        fig_bar_hh.update_layout(
                            yaxis_title="Cantidad de Horas (HH)", 
                            showlegend=False, 
                            plot_bgcolor='white',
                            height=350,
                            margin=dict(l=20, r=20, t=50, b=20)
                        )
                        # Forzar el límite superior del gráfico para que los números no se corten
                        max_h = max(hh_p, hh_e)
                        fig_bar_hh.update_yaxes(range=[0, max_h * 1.2])
                        
                        st.plotly_chart(fig_bar_hh, use_container_width=True)

                        # NUEVA SECCIÓN: Comentarios de la Sala / Actividad
                        st.markdown("**📝 Comentarios y Detalles de Ejecución**")
                        if asig_all_raw:
                            df_comentarios = pd.DataFrame(asig_all_raw)
                            df_comentarios = df_comentarios[(df_comentarios['id_nv'] == row_nv['id_nv']) & (df_comentarios['actividad_ssee'] != 'PROYECCION_GLOBAL')]
                            if not df_comentarios.empty:
                                df_comentarios['actividad_ssee'] = df_comentarios['actividad_ssee'].fillna("Labor en Terreno")
                                comentarios_unicos = df_comentarios.groupby(['actividad_ssee', 'comentarios'])['progreso'].max().reset_index()
                                for _, row_c in comentarios_unicos.iterrows():
                                    act_name = row_c['actividad_ssee']
                                    com_text = row_c['comentarios'] if pd.notna(row_c['comentarios']) and str(row_c['comentarios']).strip() else "Sin comentarios registrados."
                                    prog_val = int(row_c['progreso'])
                                    
                                    # Filtrar etiquetas internas del sistema para que la lectura sea limpia
                                    if com_text in ["LIBRES", "EXTRAS", "SIN_PROGRAMAR"]:
                                        if com_text == "SIN_PROGRAMAR":
                                            com_text = "Estado operativo: SIN INICIAR"
                                        else:
                                            com_text = f"Estado operativo: {com_text.replace('_', ' ')}"
                                        
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
                                df_det_display['Equivalente (USD)'] = df_det_display['Equivalente (USD)'].apply(lambda x: f"USD ${x:,.3f}")
                            
                            df_det_display['Monto (CLP)'] = df_det_display['Monto (CLP)'].apply(lambda x: f"CLP ${x:,.0f}")
                            
                            st.dataframe(df_det_display, use_container_width=True, hide_index=True)
                        else:
                            st.info("Sin gastos registrados.")

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
                    
                    fmt_v_pdf = f"{info_nv['monto_vendido']:,.0f}" if moneda == 'CLP' else f"{info_nv['monto_vendido']:,.3f}"
                    fmt_g_pdf = f"{sum_gas_real:,.0f}" if moneda == 'CLP' else f"{sum_gas_real:,.3f}"
                    
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
