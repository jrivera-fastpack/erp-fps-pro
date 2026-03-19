<<<<
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
                            title=f"Balance de Tiempos Operativos y Capacidad de {mes_sel_global} {anio_sel_global}"
                        )
                        fig_tiempos.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                        fig_tiempos.update_layout(yaxis_title="Cantidad de Días-Hombre", showlegend=False, plot_bgcolor='white')
                        
                        max_y = max([capacidad_neta_mes, total_dias_proyectados, total_dias_ejecutados, int(dias_ausencia_mes)] + [1])
                        fig_tiempos.update_yaxes(range=[0, max_y * 1.2])
                        st.plotly_chart(fig_tiempos, use_container_width=True)
====
                    with c_graf1:
                        df_tiempos = pd.DataFrame({
                            "Concepto": ["Días Totales del Equipo", "Días Planificados (Matriz Semanal)", "Días Reales Ejecutados (Gantt)"],
                            "Cantidad": [capacidad_neta_mes, total_dias_proyectados, total_dias_ejecutados]
                        })
                        fig_tiempos = px.bar(
                            df_tiempos, x="Concepto", y="Cantidad", color="Concepto", text="Cantidad",
                            color_discrete_map={
                                "Días Totales del Equipo": "#95A5A6", 
                                "Días Planificados (Matriz Semanal)": "#3498DB", 
                                "Días Reales Ejecutados (Gantt)": "#2ECC71"
                            },
                            title=f"Balance de Tiempos Operativos y Capacidad de {mes_sel_global} {anio_sel_global}"
                        )
                        fig_tiempos.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                        fig_tiempos.update_layout(yaxis_title="Cantidad de Días-Hombre", showlegend=False, plot_bgcolor='white')
                        
                        max_y = max([capacidad_neta_mes, total_dias_proyectados, total_dias_ejecutados] + [1])
                        fig_tiempos.update_yaxes(range=[0, max_y * 1.2])
                        st.plotly_chart(fig_tiempos, use_container_width=True)
>>>>
