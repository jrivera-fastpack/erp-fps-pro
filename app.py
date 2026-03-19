<<<<
                else:
                    st.info("No hay datos de facturación proyectada para mostrar.")

    # ==========================================
    # MÓDULO 5: CIERRE Y PDF ANALÍTICO
====
                else:
                    st.info("No hay datos de facturación proyectada para mostrar.")

            # --- NUEVA PESTAÑA: HISTORIAL FACTURADO ---
            with tab_facturados:
                st.subheader("✅ Historial de Servicios Facturados")
                st.info("Aquí se listan todas las parcialidades o hitos que ya han sido marcados como 'Facturada' en el sistema, organizados por mes.")
                
                df_hitos_fact = df_hitos[df_hitos['estado'] == 'Facturada'].copy()
                
                if not df_hitos_fact.empty:
                    df_hitos_fact = df_hitos_fact.merge(df_kpi[['id_nv', 'cliente', 'tipo_servicio', 'moneda']], on='id_nv', how='left')
                    df_hitos_fact['monto_usd_est'] = df_hitos_fact.apply(lambda r: r['monto'] if r['moneda'] == 'USD' else r['monto'] / tasa_cambio, axis=1)
                    
                    # Ordenar por año y mes descendente
                    df_hitos_fact = df_hitos_fact.sort_values(by=['anio', 'mes'], ascending=[False, False])
                    
                    # Formatear el mes
                    df_hitos_fact['Mes_Txt'] = df_hitos_fact['mes'].apply(lambda x: MESES_ES.get(int(x), str(x)))
                    df_hitos_fact['Periodo'] = df_hitos_fact['Mes_Txt'] + " " + df_hitos_fact['anio'].astype(str)
                    
                    periodos = df_hitos_fact['Periodo'].unique()
                    
                    for periodo in periodos:
                        st.markdown(f"#### 📅 {periodo}")
                        df_per = df_hitos_fact[df_hitos_fact['Periodo'] == periodo].copy()
                        
                        tot_usd = df_per['monto_usd_est'].sum()
                        tot_clp = tot_usd * tasa_cambio
                        
                        c1, c2 = st.columns(2)
                        c1.metric(f"Total Facturado en {periodo} (USD)", f"USD ${tot_usd:,.2f}")
                        c2.metric(f"Total Facturado en {periodo} (CLP)", f"CLP ${tot_clp:,.0f}".replace(",", "."))
                        
                        df_show = df_per[['id_nv', 'cliente', 'tipo_servicio', 'moneda', 'porcentaje', 'monto']].copy()
                        df_show.rename(columns={
                            'id_nv': 'NV', 'cliente': 'Cliente', 'tipo_servicio': 'Tipo', 
                            'moneda': 'Moneda', 'porcentaje': '% Cobrado', 'monto': 'Monto Facturado'
                        }, inplace=True)
                        
                        def format_facturado(val, mon):
                            if mon == 'USD': return f"USD ${val:,.2f}"
                            return f"CLP ${val:,.0f}".replace(",", ".")
                            
                        df_show['Monto Facturado'] = df_show.apply(lambda x: format_facturado(x['Monto Facturado'], x['Moneda']), axis=1)
                        df_show['% Cobrado'] = df_show['% Cobrado'].apply(lambda x: f"{x:.1f}%")
                        
                        st.dataframe(df_show, use_container_width=True, hide_index=True)
                        st.markdown("<hr style='margin: 10px 0; opacity: 0.3;'>", unsafe_allow_html=True)
                else:
                    st.success("Aún no hay servicios marcados como facturados en el sistema.")

    # ==========================================
    # MÓDULO 5: CIERRE Y PDF ANALÍTICO
>>>>
