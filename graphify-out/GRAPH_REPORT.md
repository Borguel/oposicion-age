# Graph Report - oposicion-age  (2026-08-01)

## Corpus Check
- 260 files · ~844,570 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3501 nodes · 7699 edges · 184 communities (163 shown, 21 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 196 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cf6946fa`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Rama de trabajo
- test_admin.py
- posthog-array.js
- ya
- email_utils.py
- test_publicacion_estatica_boe.py
- g
- route
- _con_sesion
- .register
- auth.js
- fakes.py
- test_generador_preguntas_verificado.py
- admin.py
- test_tu_tutor.py
- Ga
- generar_preguntas_ia_en_lotes
- coleccion_examenes_oficiales
- admin/script.js
- N
- subida-pdf-tarjetas/script.js
- test_ia.py
- chat_controller.py
- registrar_uso
- documentos_pdf.py
- info
- login/script.js
- test_auth_utils.py
- regenerar_temario_ofimatica.py
- subida-pdf-esquemas/script.js
- tarjetas_generator.py
- coste_ia.py
- test_generar_test_oficial.py
- auth_utils.py
- pdf_ia.py
- Oo
- db
- test_prueba_gratuita.py
- subida-pdf-resumen/script.js
- test_pagos_checkout.py
- test-personalizado/script.js
- tu-tutor/script.js
- call_deepseek_api
- .identify
- test_validador_preguntas.py
- warn
- mis-documentos/script.js
- subida-pdf-generar-test/script.js
- zona-opositor/script.js
- test_tareas_programadas.py
- cargar_temario_gace_bloque2_ue.py
- test-oficial/script.js
- utils.py
- mi-cuenta/script.js
- requiere_plan
- rutas_progreso.py
- preguntas-falladas/script.js
- preguntas-favoritas/script.js
- repetir-test/script.js
- test_resultado_test_oficial.py
- test_reparto_realista.py
- test_utils.py
- registro_progreso_usuario.py
- escapeHtml
- test-progreso.js
- repasar-preguntas/script.js
- cargar_temario_auxiliar.py
- Dn
- subida-pdf-chat-pdf/script.js
- vigilancia_boe.py
- generar_tarjetas_verificadas
- al
- test_vigilancia_boe.py
- test_carpetas_documentos.py
- deepseek_utils.py
- demo/script.js
- test_gestion_cuenta.py
- test_push_notificaciones.py
- extraer_paginas
- estadisticas/script.js
- generar_propuesta_cambio
- test_auth_publico.py
- test_temario.py
- firebase_setup.py
- onboarding-tour.js
- ei
- mis-tests/script.js
- test_generator.py
- detectar_cambios_leyes_vigiladas
- toast
- es
- resultados-test.js
- test_repaso_espaciado.py
- oposicionActual
- De
- ui
- podar_temario_age_bloque4_tema9.py
- _fecha_hace
- jr
- podar_temario_gace_bloque2_temas1_5.py
- test_webhook_stripe.py
- coleccion_banco_preguntas
- _temas_mencionados
- responder_tutor_stream
- sembrar_usuario_activo
- wireFichaVista
- manifest.json
- podar_temario_age_bloque5_tema6.py
- TestCallDeepseekApiStream
- test_marcadas_duda.py
- cargar_temario_boe.py
- planes/script.js
- obtener_estadisticas_completas_usuario
- test_autosave_resume.py
- TestGenerarConContinuacion
- obtener_contexto_por_temas_exactos
- test_soporte.py
- Esquema de datos en Firestore
- generar_sitemap.py
- _sembrar_tema
- TestRelevanciaTemarioConIA
- temario.py
- plan.js
- limpiar_titulos_vacio_temario.py
- package.json
- Arrancar en local
- test_ranking.py
- obtener_catalogo_temas
- push.js
- test_fecha_examen.py
- test_health.py
- test_mi_perfil.py
- TestExistePropuestaPendienteReciente
- _guardar_turno
- conftest.py
- favoritas.js
- OPOSICIONES
- displaySurvey
- getSurveys
- tutor-widget.js
- datos-personales/script.js
- resultado/script.js
- ranking/script.js
- limpiar_subdivisiones_vacias.py
- test_borrar_test.py
- TestGenerarDocumentoLargoPorPartes
- test_error_handler.py
- test_rate_limiter.py
- diagnosticar_usuario.py
- popover.js
- migrar_usuarios_a_suscripciones.py
- nav.spec.js
- TestTrocearEnParrafos
- _respuesta_http_error
- avisos_oficiales_editar
- preguntas_export
- analytics.js
- firebase-config.js
- limite-paginas.js
- temas-numeracion.js
- listar_temas_vacios.py
- smoke.spec.js
- cuenta-atras.js
- icons.js
- navegador-preguntas.js
- otras-herramientas-pdf.js
- stream-utils.js
- generar_claves_vapid.py
- completar_explicaciones.py
- _eventos_sse
- buscar_pregunta_oficial
- playwright.config.js

## God Nodes (most connected - your core abstractions)
1. `_como()` - 109 edges
2. `ya` - 107 edges
3. `requiere_plan()` - 56 edges
4. `call_deepseek_api()` - 51 edges
5. `responder_tutor()` - 48 edges
6. `sembrar_usuario_activo()` - 48 edges
7. `N()` - 48 edges
8. `db()` - 47 edges
9. `g()` - 47 edges
10. `requiere_permiso()` - 46 edges

## Surprising Connections (you probably didn't know these)
- `_volcar_coste_ia()` --indirect_call--> `db()`  [INFERRED]
  app.py → conftest.py
- `_uso_herramientas()` --indirect_call--> `db()`  [INFERRED]
  blueprints/admin.py → conftest.py
- `usuarios_listar()` --indirect_call--> `db()`  [INFERRED]
  blueprints/admin.py → conftest.py
- `usuarios_crear()` --indirect_call--> `db()`  [INFERRED]
  blueprints/admin.py → conftest.py
- `usuarios_eliminar()` --indirect_call--> `db()`  [INFERRED]
  blueprints/admin.py → conftest.py

## Import Cycles
- None detected.

## Communities (184 total, 21 thin omitted)

### Community 1 - "test_admin.py"
Cohesion: 0.04
Nodes (102): _como(), Pruebas del panel de administración (blueprints/admin.py + requiere_admin). Lo…, test_admin_accede(), test_admin_asigna_roles(), test_asignar_roles_requiere_admin_total(), test_auditoria_ordena_reciente_primero(), test_auditoria_paginada(), test_avisos_oficiales_crear_manual_con_tipo_personalizado_y_url_inap() (+94 more)

### Community 2 - "posthog-array.js"
Cohesion: 0.03
Nodes (60): addFeatureFlagsHandler(), as(), Br, Ca(), captureLog(), Ce(), count(), cs() (+52 more)

### Community 3 - "ya"
Cohesion: 0.04
Nodes (19): clearCache(), cn(), critical(), _e(), error(), flushLogs(), ge(), getEarlyAccessFeatures() (+11 more)

### Community 4 - "email_utils.py"
Cohesion: 0.06
Nodes (67): enviar_verificacion_email(), route, Rutas de autenticación relacionadas con correos que Firebase mandaría por su…, Genera el enlace de restablecimiento de contraseña con Firebase Admin y lo…, Genera el enlace de verificación de correo con Firebase Admin y lo envía por…, recuperar_contrasena(), _clave_cron_valida(), enviar_recordatorios_prueba() (+59 more)

### Community 5 - "test_publicacion_estatica_boe.py"
Cohesion: 0.07
Nodes (60): avisos_oficiales_actualizar(), avisos_oficiales_listar(), actualizar_pagina_avisos_general(), actualizar_pagina_estatica_avisos(), _cabeceras(), _consultar_avisos_publicados(), _consultar_avisos_publicados_todos(), _escribir_archivo_github() (+52 more)

### Community 6 - "g"
Cohesion: 0.07
Nodes (41): A(), addExceptionStep(), b(), constructor(), d(), eo(), f(), Fo (+33 more)

### Community 7 - "route"
Cohesion: 0.10
Nodes (58): Exige que quien llama tenga AL MENOS UNO de los permisos indicados (o sea…, requiere_permiso(), analitica_contenido(), avisos_oficiales_crear(), cambios_temario_actualizar(), cambios_temario_listar(), _id_valido(), preguntas_crear() (+50 more)

### Community 8 - "_con_sesion"
Cohesion: 0.06
Nodes (23): _extraer_json_array(), Extrae y parsea el array JSON que debería devolver la IA, tolerando que venga…, _con_sesion(), documento_sembrado(), _eventos_sse(), _FakeRespuestaDeepSeek, fixture, Pruebas de blueprints/pdf_ia.py: _extraer_json_array (la reparación de JSON de… (+15 more)

### Community 9 - ".register"
Cohesion: 0.05
Nodes (32): aa(), ba, bn(), Bs(), Bt(), destroy(), fa(), fn() (+24 more)

### Community 10 - "auth.js"
Cohesion: 0.06
Nodes (42): _permisos, actualizarEnlacesNav(), actualizarIconoTema(), alternarTema(), aplicarEstiloAviso(), app, auth, calcularNotificaciones() (+34 more)

### Community 11 - "fakes.py"
Cohesion: 0.05
Nodes (17): _cumple_filtro(), FakeAggregationQuery, FakeAggregationResult, FakeCollectionGroupRef, FakeCollectionRef, FakeDocumentRef, FakeDocumentSnapshot, FakeFirestore (+9 more)

### Community 12 - "test_generador_preguntas_verificado.py"
Cohesion: 0.08
Nodes (49): _bloques_contenido(), _bloques_texto_legal(), _elegir_ancla_legal(), _elegir_tipo_pregunta(), _es_normativo(), _extraer_articulos(), _generar_pregunta_verificada(), generar_test_verificado() (+41 more)

### Community 13 - "admin.py"
Cohesion: 0.06
Nodes (50): Exige que quien llama sea administrador (custom claim admin:true en su token de…, requiere_admin(), auditoria_listar(), _bajas_agregadas(), bajas_listar(), banco_preguntas_resumen(), banner_guardar(), banner_obtener() (+42 more)

### Community 14 - "test_tu_tutor.py"
Cohesion: 0.09
Nodes (42): responder_tutor(), Pruebas de Tu Tutor (chat_controller.responder_tutor + blueprints/tu_tutor.py):…, _sembrar_tema(), test_contexto_de_pagina_pasa_la_pregunta_en_pantalla(), test_contexto_personal_del_usuario_se_incluye_en_el_prompt(), test_contexto_personal_incluye_la_nota_del_ultimo_test(), test_conversacion_normal_si_conserva_el_historial(), test_dato_verificado_con_pregunta_en_pantalla_no_invierte_opcion_con_doble_negacion() (+34 more)

### Community 15 - "Ga"
Cohesion: 0.07
Nodes (5): cancelPendingSurvey(), Ga, On, Va, Wa

### Community 16 - "generar_preguntas_ia_en_lotes"
Cohesion: 0.09
Nodes (23): _fragmentos_por_lote(), generar_preguntas_ia_en_lotes(), Devuelve una lista de n_lotes fragmentos del documento, uno por lote, para que…, Genera 'num_preguntas' preguntas pidiéndolas a DeepSeek en varios lotes en…, _con_sesion(), _pregunta_json(), Pruebas de los generadores de test/análisis basados en el TEMARIO oficial vía…, test_dedupe_por_texto_normalizado_entre_lotes() (+15 more)

### Community 17 - "coleccion_examenes_oficiales"
Cohesion: 0.08
Nodes (35): main(), Sube a Firestore los datos oficiales de la convocatoria vigente de una…, aplicar(), doc_ids(), _firestore_client(), main(), preview(), Desactiva en Firestore las preguntas del banco de GACE que preguntan… (+27 more)

### Community 18 - "admin/script.js"
Cohesion: 0.07
Nodes (39): activarPestana(), actualizarBadgeBoe(), actualizarBadgeReportes(), alternarSubmenuSidebar(), atraparTabEnModal(), bloquesAbiertos, bloquesAbiertosPreguntas, cargarAuditoria() (+31 more)

### Community 19 - "N"
Cohesion: 0.11
Nodes (7): allowedMetrics(), flushIntervalMilliseconds(), flushToCaptureTimeoutMs(), N(), q(), transformToEventProperties(), useAttribution()

### Community 20 - "subida-pdf-tarjetas/script.js"
Cohesion: 0.06
Nodes (41): alertaPreguntas, archivoPdfInput, autoSaveIndicator, btnAnterior, btnCerrar, btnEscuchar, btnListaTarjetas, btnSiguiente (+33 more)

### Community 21 - "test_ia.py"
Cohesion: 0.09
Nodes (34): estado_salud(), fichero_demasiado_grande(), manejar_error_no_controlado(), limit, route, raiz(), Sin autenticación a propósito: la usa el monitor externo (GitHub Actions, o el…, verificar_api_key() (+26 more)

### Community 22 - "chat_controller.py"
Cohesion: 0.10
Nodes (37): _actualizar_resumen_si_hace_falta(), _bloque_explicar_fallo(), _bloque_respuesta_verificada(), _contexto_personal_usuario(), _es_modo_examen(), _es_pregunta_de_test(), _hace_cuanto(), _historial_previo() (+29 more)

### Community 23 - "registrar_uso"
Cohesion: 0.10
Nodes (36): cargar_limites_config(), _config_tool(), devolver_uso(), _estructura_defecto(), _fusionar_overrides(), guardar_limites_config(), invalidar_cache_limites(), limites_efectivos() (+28 more)

### Community 24 - "documentos_pdf.py"
Cohesion: 0.09
Nodes (25): documento_titulo(), eliminar_documento_route(), actualizar_titulo(), eliminar_documento(), extraer_titulo(), _hash_texto(), obtener_documento(), obtener_o_crear_documento() (+17 more)

### Community 25 - "info"
Cohesion: 0.09
Nodes (14): Ao, Bo(), captureException(), debug(), fe(), Ho(), info(), jo (+6 more)

### Community 26 - "login/script.js"
Cohesion: 0.06
Nodes (27): avisoPrueba, bloqueNombreApellidos, bloqueRepetirPassword, bloqueTerminos, btnGoogle, btnOlvidePassword, btnRecuperarCancelar, btnRecuperarSubmit (+19 more)

### Community 27 - "test_auth_utils.py"
Cohesion: 0.10
Nodes (23): _decodificar_token_admin(), _decodificar_token_peticion(), obtener_identidad_desde_token(), obtener_uid_desde_token(), Verifica el token Bearer y devuelve (decoded, None) o (None, respuesta de…, verify_id_token() con un reintento ante fallos de red al obtener los…, Header Authorization: Bearer <token> ya verificado -- el dict crudo que…, Verifica el Firebase ID token del header Authorization: Bearer <token>.… (+15 more)

### Community 28 - "regenerar_temario_ofimatica.py"
Cohesion: 0.11
Nodes (32): dividir_en_subbloques_por_epigrafe(), _estimar_tokens(), extraer_texto_tema(), guardar_preview(), _limpiar_pagina(), _localizar_pdfs(), main(), procesar_tema() (+24 more)

### Community 29 - "subida-pdf-esquemas/script.js"
Cohesion: 0.09
Nodes (29): alertaPreguntas, archivoPdfInput, autoSaveIndicator, bloquesAHtml(), btnCerrar, btnDescargarPdf, calcularCorteSeguro(), construirArbolLista() (+21 more)

### Community 30 - "tarjetas_generator.py"
Cohesion: 0.10
Nodes (18): _asegurar_tarjeta_valida(), _contiene_frase_prohibida(), _generar_candidatas_fragmento(), _normalizar(), _parsear_tarjetas(), _prompt_generacion(), _prompt_verificacion(), Generador de tarjetas de memoria (flashcards) a partir de un PDF subido por el… (+10 more)

### Community 31 - "coste_ia.py"
Cohesion: 0.10
Nodes (25): AcumuladorTokens, acumular_usage(), coste_estimado(), flush_coste(), guardar_coste_directo(), _incrementar_mes(), Contabilidad del gasto en IA (tokens de DeepSeek) por usuario. Cómo funciona: -…, Vuelca lo acumulado directamente al documento del usuario, sin pasar por… (+17 more)

### Community 32 - "test_generar_test_oficial.py"
Cohesion: 0.14
Nodes (30): _con_sesion(), _pregunta(), Pruebas del generador de Test Oficial (banco de preguntas de exámenes reales ya…, test_demo_test_oficial_devuelve_menos_de_5_si_no_hay_tantas(), test_demo_test_oficial_excluye_psicotecnicas(), test_demo_test_oficial_no_exige_login(), test_demo_test_oficial_oposicion_no_valida_cae_a_age(), test_repartir_cupos_reparte_el_resto_sin_perder_unidades() (+22 more)

### Community 33 - "auth_utils.py"
Cohesion: 0.09
Nodes (28): _permisos_de(), Conjunto de permisos efectivos del token. El super-admin los tiene todos., _contar_subcoleccion(), _ficha_actividad(), _notas_lista(), _oposiciones_activas(), _plan_usuario(), Nº de documentos de una subcolección del usuario. Usa la agregación count()… (+20 more)

### Community 34 - "pdf_ia.py"
Cohesion: 0.14
Nodes (30): chat_deepseek(), chat_pdf_mensaje(), documento_carpeta(), documento_esquema(), documento_resumen(), documento_tarjetas(), documento_test(), generar_esquema_desde_pdf() (+22 more)

### Community 35 - "Oo"
Cohesion: 0.08
Nodes (13): buildProperties(), getAndClearBuffer(), ii, is(), nt(), Oo, Se(), si (+5 more)

### Community 36 - "db"
Cohesion: 0.16
Nodes (28): requiere_login(), promocion_publica(), Lectura pública: el frontend decide si mostrarla según el plan del usuario (o…, cancelar_suscripcion(), contactar_soporte(), crear_sesion_checkout(), crear_sesion_portal(), _current_period_end() (+20 more)

### Community 37 - "test_prueba_gratuita.py"
Cohesion: 0.10
Nodes (25): es_dominio_email_desechable(), Dominios de correo desechable/temporal conocidos: una cuenta creada con uno de…, True si el dominio del email está en la lista conocida de correo…, ¿Es ya cliente de pago en ALGUNA oposición (suscripción real, no la prueba…, tiene_plan_de_pago_activo(), inicializar_estadisticas_usuario(), obtener_perfil_usuario(), Datos mínimos de plan/suscripción para pintar la UI del frontend. Si se pasa… (+17 more)

### Community 38 - "subida-pdf-resumen/script.js"
Cohesion: 0.09
Nodes (26): alertaPreguntas, archivoPdfInput, autoSaveIndicator, bloquesAHtml(), btnCerrar, btnDescargarPdf, contenedorCarga, contenidoResumen (+18 more)

### Community 39 - "test_pagos_checkout.py"
Cohesion: 0.14
Nodes (25): _con_sesion(), _mock_precio(), Pruebas de las rutas que crean sesiones de pago en Stripe (/crear-sesion-…, test_cancelar_suscripcion_con_subscription_id_huerfano_se_marca_gratis_localmente(), test_cancelar_suscripcion_programa_la_baja_y_guarda_el_motivo(), test_cancelar_suscripcion_propaga_error_de_stripe_como_500(), test_cancelar_suscripcion_rechaza_motivo_no_valido(), test_cancelar_suscripcion_sin_suscripcion_activa_da_error() (+17 more)

### Community 40 - "test-personalizado/script.js"
Cohesion: 0.13
Nodes (25): activarBotonFavorita(), actualizarNavegadorPreguntas(), agregarPreguntaEnCurso(), asignarTemaFallback(), botonFavoritaHTML(), cargarTemas(), entrarEnModoTest(), formatearTiempo() (+17 more)

### Community 41 - "tu-tutor/script.js"
Cohesion: 0.20
Nodes (28): acortarTitulo(), actualizarBotonScroll(), actualizarBurbujaBot(), agregarCtaPlanes(), agregarMensaje(), aplicarEnfasis(), aplicarSugerenciaBienvenida(), cargarConversacion() (+20 more)

### Community 42 - "call_deepseek_api"
Cohesion: 0.14
Nodes (24): cargar_examen(), generar_explicacion(), Carga el Ejercicio Único de una convocatoria AGE (Cuerpo General Administrativo…, cargar_examen(), generar_explicacion(), Carga el Ejercicio Único de una convocatoria del Cuerpo General Auxiliar de la…, El PDF fuente usa una fuente con un tracking que pypdf extrae como espacios…, reparar_espaciado() (+16 more)

### Community 43 - ".identify"
Cohesion: 0.13
Nodes (3): qo(), setAnonymousDistinctId(), zo

### Community 44 - "test_validador_preguntas.py"
Cohesion: 0.18
Nodes (26): _pregunta_valida(), Pruebas de validador_preguntas.py: filtra preguntas mal formadas o de baja…, test_acepta_explicacion_justo_en_el_limite(), test_detectar_repeticiones_cuenta_frases_normativas_repetidas(), test_falta_una_clave_obligatoria(), test_falta_una_opcion_de_la_a_a_la_d(), test_filtrar_preguntas_repetidas_quita_las_que_mencionan_el_concepto(), test_no_es_un_diccionario() (+18 more)

### Community 45 - "warn"
Cohesion: 0.11
Nodes (17): dt(), flush(), getMessages(), getTickets(), ht, ke(), M(), markAsRead() (+9 more)

### Community 46 - "mis-documentos/script.js"
Cohesion: 0.19
Nodes (26): abrirCarpeta(), abrirModalAnadir(), asignarCarpeta(), cargarDocumentos(), carpetas, cerrarModalAnadir(), confirmarAnadirDocumentos(), crearCarpetaEnBackend() (+18 more)

### Community 47 - "subida-pdf-generar-test/script.js"
Cohesion: 0.14
Nodes (25): activarBotonFavorita(), actualizarNavegadorPreguntas(), agregarPreguntaEnCurso(), avisarSiPreguntasIncompletas(), botonFavoritaHTML(), formatearTiempo(), generarTestDesdePdfConProgreso(), guardarContenidoEnSegundoPlano() (+17 more)

### Community 48 - "zona-opositor/script.js"
Cohesion: 0.14
Nodes (25): AVISOS, cargarAvisosOficiales(), cargarProgresoInsignias(), cargarRacha(), cargarRepasoPendiente(), cargarTestEnProgreso(), comprobarPasosOnboarding(), escapeHtml() (+17 more)

### Community 49 - "test_tareas_programadas.py"
Cohesion: 0.11
Nodes (16): _fecha_hace(), _mes_actual(), _prueba_fin_en(), Pruebas del cron de recordatorios de racha (blueprints/tareas_programadas.py):…, test_avisa_a_quien_cruza_un_umbral_de_inactividad(), test_avisa_a_quien_esta_en_riesgo_de_perder_la_racha(), test_avisa_a_quien_la_prueba_termino_ayer(), test_avisa_a_quien_le_quedan_2_dias_de_prueba() (+8 more)

### Community 50 - "cargar_temario_gace_bloque2_ue.py"
Cohesion: 0.16
Nodes (23): clasificar_subbloques_tratado(), dividir_tratado_en_subbloques(), _estimar_tokens(), extraer_texto_ftu(), guardar_preview(), _localizar_articulado(), _localizar_fichas_ftu(), main() (+15 more)

### Community 51 - "test-oficial/script.js"
Cohesion: 0.14
Nodes (24): activarBotonFavorita(), actualizarNavegadorPreguntas(), botonFavoritaHTML(), cargarTemas(), formatearTiempo(), guardarTestAutomaticamente(), iniciarBotonSimulacroOficial(), iniciarSelectorPsicotecnicas() (+16 more)

### Community 52 - "utils.py"
Cohesion: 0.12
Nodes (24): test_pregunta_recien_generada_se_encuentra_de_inmediato_en_tu_tutor(), test_buscar_pregunta_banco_ia_por_contencion_del_enunciado(), test_obtener_preguntas_banco_ia_usa_cache_hasta_que_se_invalida(), agrupar_subbloques_por_tema(), buscar_pregunta_banco_ia(), contar_tokens(), _desde_cache_o_calcular(), invalidar_cache() (+16 more)

### Community 53 - "mi-cuenta/script.js"
Cohesion: 0.10
Nodes (21): a11yModalCancelar, a11yModalEliminar, btnConfirmarCancelar, btnConfirmarEliminar, btnContacto, campoComentario, campoConfirmar, campoContacto (+13 more)

### Community 54 - "requiere_plan"
Cohesion: 0.17
Nodes (21): Exige que el usuario tenga, como mínimo, el plan `minimo`. Por defecto…, requiere_plan(), _alias_valido(), mi_estado_ranking(), obtener_ranking(), route, Clasificación de racha de estudio: anónima y estrictamente opcional. Solo…, salir_ranking() (+13 more)

### Community 55 - "rutas_progreso.py"
Cohesion: 0.17
Nodes (20): listar_fallos(), desmarcar_favorita(), listar_favoritas(), marcar_favorita(), ordenar_por_prioridad_repaso(), Banco persistente de "preguntas favoritas" marcadas por el usuario para repasar…, Repaso espaciado para favoritas: al no haber un contador de fallos (el usuario…, _b64url_decode() (+12 more)

### Community 56 - "preguntas-falladas/script.js"
Cohesion: 0.17
Nodes (20): activarBotonFavorita(), actualizarNavegadorPreguntas(), botonFavoritaHTML(), cargarTemas(), formatearTiempo(), guardarTestFalladasAutomaticamente(), iniciarTemporizador(), listaTemasGlobal (+12 more)

### Community 57 - "preguntas-favoritas/script.js"
Cohesion: 0.17
Nodes (20): activarBotonFavorita(), actualizarNavegadorPreguntas(), botonFavoritaHTML(), cargarTemas(), formatearTiempo(), guardarTestFavoritasAutomaticamente(), iniciarTemporizador(), listaTemasGlobal (+12 more)

### Community 58 - "repetir-test/script.js"
Cohesion: 0.16
Nodes (19): activarBotonFavorita(), actualizarNavegadorPreguntas(), botonFavoritaHTML(), cargarListaTemas(), confirmarFinalizar(), formatearMinSeg(), generarComparacionIntentosHTML(), iniciarTemporizador() (+11 more)

### Community 59 - "test_resultado_test_oficial.py"
Cohesion: 0.16
Nodes (19): actualizar_estadisticas_test(), conectar_firestore(), corregir(), main(), Corrección única: el campo "resultado" (aprobado/suspendido) de un test se…, _con_sesion(), _contenido_con_aciertos_y_fallos(), Pruebas de que "aprobado/suspendido" se calcula con la misma fórmula oficial… (+11 more)

### Community 60 - "test_reparto_realista.py"
Cohesion: 0.14
Nodes (20): Pruebas del reparto "realista" de preguntas entre temas (opción del usuario en…, test_calcular_pesos_reales_por_bloque_cuenta_por_bloque(), test_calcular_pesos_reales_por_bloque_usa_cache(), test_calcular_pesos_reales_por_bloque_vacio_sin_examenes(), test_obtener_preguntas_examenes_oficiales_filtra_por_tipo(), test_obtener_preguntas_examenes_oficiales_usa_cache(), test_repartir_cupos_por_tema_realista_bloque_sin_datos_recibe_peso_medio(), test_repartir_cupos_por_tema_realista_reparte_igual_dentro_del_bloque() (+12 more)

### Community 61 - "test_utils.py"
Cohesion: 0.17
Nodes (20): _pregunta_base(), Pruebas de utils.barajar_opciones_pregunta: los LLM tienden a poner la…, test_conserva_las_4_opciones_sin_perder_ni_duplicar_contenido(), test_explicacion_remapeada_a_la_nueva_letra_correcta(), test_no_siempre_deja_la_correcta_en_a(), test_no_toca_explicacion_que_no_sigue_el_formato_por_letra(), test_no_toca_la_pregunta_si_las_opciones_no_tienen_forma_esperada(), test_obtener_titulos_temas_reales_traduce_codigos_via_get_all() (+12 more)

### Community 62 - "registro_progreso_usuario.py"
Cohesion: 0.18
Nodes (16): actualizar_banco_fallos(), _id_pregunta(), ordenar_por_prioridad_repaso(), Banco persistente de "preguntas falladas" por usuario/oposición. Antes, el test…, Repaso espaciado simple: en vez de elegir al azar entre las preguntas falladas…, marcar_generado(), Actualiza los indicadores del documento tras guardar contenido nuevo generado a…, guardar_resultado_en_firestore() (+8 more)

### Community 63 - "escapeHtml"
Cohesion: 0.18
Nodes (20): _actualizarStatBoe(), _avisoTemasFaltantesHtml(), _avisoTokenGithubHtml(), cargarAvisosOficiales(), cargarCambiosTemario(), _cargarSaludVigilancia(), cargarSoporte(), _diffHtml() (+12 more)

### Community 64 - "test-progreso.js"
Cohesion: 0.18
Nodes (15): activarGuardadoAlSalir(), actualizarContenidoEnCurso(), armarDeteccionOffline(), autoguardarProgreso(), borrarCopiaLocal(), cargarTestEnProgreso(), claveOffline(), enviarAutosave() (+7 more)

### Community 65 - "repasar-preguntas/script.js"
Cohesion: 0.15
Nodes (19): cache, cargarTemas(), elAviso, elCargando, elFiltroBloque, elFiltroTema, elLista, escaparHtml() (+11 more)

### Community 66 - "cargar_temario_auxiliar.py"
Cohesion: 0.20
Nodes (17): clasificar_subbloque_auxiliar(), construir_subbloques_clasificados(), guardar_preview(), main(), Carga el Bloque I ("Organización Pública", 16 temas) de "Temario Auxiliar"…, Igual que clasificar_subbloque_age de completar_temario_age.py, pero con los 16…, subir_a_firestore(), detectar_offset() (+9 more)

### Community 67 - "Dn"
Cohesion: 0.15
Nodes (3): Dn, ensureFlagsLoaded(), Lo

### Community 68 - "subida-pdf-chat-pdf/script.js"
Cohesion: 0.15
Nodes (18): addMessageToPdfChat(), enviarMensajePdf(), escaparHtml(), handlePdfUpload(), hideTypingIndicator(), historialChat, pageCount, pdfChatBox (+10 more)

### Community 69 - "vigilancia_boe.py"
Cohesion: 0.18
Nodes (18): _buscar_clave(), _buscar_lista(), _clasificar_relevancia_temario_con_ia(), _fechas_a_revisar(), _get_json(), _guardar_aviso_oficial(), obtener_bloque_texto_ley(), obtener_indice_texto_ley() (+10 more)

### Community 70 - "generar_tarjetas_verificadas"
Cohesion: 0.18
Nodes (7): generar_documento_largo_por_partes(), Trocea el texto en fragmentos de como mucho 'tamano' caracteres, cortando…, Para documentos largos, en vez de meter todo el texto de golpe en un único…, _trocear_en_parrafos(), generar_tarjetas_verificadas(), Genera hasta num_tarjetas tarjetas de memoria verificadas a partir de texto (ya…, TestGenerarTarjetasVerificadas

### Community 71 - "al"
Cohesion: 0.23
Nodes (3): al, getFeatureFlag(), isFeatureEnabled()

### Community 72 - "test_vigilancia_boe.py"
Cohesion: 0.22
Nodes (14): _fake_response(), _metadatos(), Pruebas de vigilancia_boe.py: nunca publica/aplica nada sola -- solo crea…, _sumario_con_item(), test_clasificar_aviso_llamamiento_extraordinario_no_es_fecha_examen(), test_detectar_avisos_oficiales_crea_aviso_pendiente(), test_detectar_avisos_oficiales_ignora_lo_irrelevante_para_las_3_oposiciones(), test_detectar_avisos_oficiales_ignora_mencion_sin_tipo_de_aviso_reconocible() (+6 more)

### Community 73 - "test_carpetas_documentos.py"
Cohesion: 0.19
Nodes (16): crear_carpeta_documentos(), eliminar_carpeta_documentos(), crear_carpeta(), eliminar_carpeta(), listar_carpetas(), Catálogo de carpetas del usuario: las creadas explícitamente con…, Borra la carpeta del catálogo y deja "sin carpeta" a los documentos que…, _con_sesion() (+8 more)

### Community 74 - "deepseek_utils.py"
Cohesion: 0.15
Nodes (15): cargar_examen(), generar_explicacion(), Carga el Primer Ejercicio de una convocatoria GACE (Cuerpo de Gestión de la…, call_deepseek_api_stream(), _es_error_transitorio(), generar_contenido_desde_texto(), _post_deepseek_con_reintentos(), POST a DeepSeek con el mismo criterio de reintento transitorio que… (+7 more)

### Community 75 - "demo/script.js"
Cohesion: 0.18
Nodes (16): actualizarNavegador(), btnDescargarPdf, cargarPreguntas(), confirmarFinalizar(), contCargando, contError, contNavegador, contResultados (+8 more)

### Community 76 - "test_gestion_cuenta.py"
Cohesion: 0.19
Nodes (15): eliminar_cuenta_usuario(), exportar_datos_usuario(), Exportación y borrado de cuenta (derecho de acceso y de supresión del RGPD):…, Todo lo que Firestore tiene guardado de este usuario, en un único JSON…, Cancela cualquier suscripción de Stripe activa, borra todas las subcolecciones…, _con_sesion(), Pruebas de exportación y borrado de cuenta (gestion_cuenta.py + rutas de…, test_eliminar_cuenta_borra_conversaciones_de_tu_tutor() (+7 more)

### Community 77 - "test_push_notificaciones.py"
Cohesion: 0.18
Nodes (14): _cifrar_aes128gcm(), _hkdf_expand(), _hkdf_extract(), Cifra el payload según RFC 8291 (aes128gcm) para el navegador receptor,…, _con_sesion(), _descifrar_como_navegador(), _fecha_hace(), Pruebas de las rutas de suscripción a notificaciones push (guardar, deduplicar… (+6 more)

### Community 78 - "extraer_paginas"
Cohesion: 0.22
Nodes (14): dividir_en_subbloques(), extraer_paginas(), Trocea el texto de una norma en subbloques cortando siempre en límites de…, _trocear_por_parrafos_o_lineas(), guardar_preview(), main(), procesar_objetivo(), Rellena los 2 temas de "Temario AGE" que estaban vacíos en Firestore (ver… (+6 more)

### Community 79 - "estadisticas/script.js"
Cohesion: 0.25
Nodes (14): cargarDatos(), fechaLocalYMD(), mostrarTemasFlojos(), notaSobre10(), obtenerAuthHeaders(), parsearFechaUTC(), pintarCalendarioMes(), pintarMapaTemario() (+6 more)

### Community 80 - "generar_propuesta_cambio"
Cohesion: 0.25
Nodes (14): _bloque_candidatos(), generar_propuesta_cambio(), _prompt_generacion(), _prompt_verificacion(), Redacta una propuesta de cambio al temario ("elimina este texto exacto, añade…, Devuelve {"chunk_id_afectado", "resumen", "texto_eliminar", "texto_anadir"} si…, Pruebas de generador_diff_temario.py: el mismo espíritu que…, _respuesta_generacion() (+6 more)

### Community 81 - "test_auth_publico.py"
Cohesion: 0.21
Nodes (12): _con_sesion(), _mensaje_generico(), Pruebas de /recuperar-contrasena: la única ruta del backend pensada para…, test_email_con_formato_invalido_responde_generico_sin_llamar_a_firebase(), test_email_existente_genera_enlace_y_envia_por_brevo(), test_email_no_registrado_responde_igual_y_no_envia_nada(), test_email_vacio_responde_generico_sin_llamar_a_firebase(), test_fallo_inesperado_de_firebase_no_rompe_la_ruta() (+4 more)

### Community 82 - "test_temario.py"
Cohesion: 0.18
Nodes (9): _con_sesion(), Pruebas de blueprints/temario.py: catálogo de oposiciones y su temario -- sin…, test_avisos_oficiales_devuelve_los_de_esa_oposicion(), test_avisos_oficiales_ignora_los_de_otra_oposicion(), test_avisos_oficiales_incluye_uno_que_afecta_a_varias_oposiciones(), test_progreso_usuario_404_si_no_existe(), test_progreso_usuario_devuelve_los_campos_esperados(), test_temas_disponibles_devuelve_bloque_y_tema() (+1 more)

### Community 83 - "firebase_setup.py"
Cohesion: 0.20
Nodes (12): asignar_admin(), main(), Script PUNTUAL (no forma parte de la app) para dar permisos de administrador a…, propagar_proxy_saliente(), Arranque de Firebase Admin, en su propio módulo para que tanto app.py como cada…, Si hay un proxy de salida con IP estática configurado (QuotaGuard o Fixie, para…, Pruebas de propagar_proxy_saliente() (firebase_setup.py): sin FIXIE_URL ni…, test_con_fixie_url_rellena_las_variables_de_proxy() (+4 more)

### Community 84 - "onboarding-tour.js"
Cohesion: 0.30
Nodes (14): claveParaUsuario(), detenerListenerScrollTour(), detenerObservadorTour(), iniciarPaso(), iniciarTourGenerico(), marcarVisto(), mostrarBocadillo(), mostrarTourTest() (+6 more)

### Community 86 - "mis-tests/script.js"
Cohesion: 0.22
Nodes (14): acortarTitulo(), borrarTest(), cargarTemas(), cargarTests(), formatearFecha(), inicializar(), PAGINA_POR_TIPO, pillsTemas() (+6 more)

### Community 87 - "test_generator.py"
Cohesion: 0.18
Nodes (14): _asegurar_pregunta_valida(), _claves_dedup(), _normalizar(), _pedir_una_pregunta_de_recambio(), _prompt_con_exclusion(), _prompt_verificacion(), _prompt_verificacion_lote(), Verifica TODAS las preguntas candidatas de un lote en UNA sola llamada, en vez… (+6 more)

### Community 88 - "detectar_cambios_leyes_vigiladas"
Cohesion: 0.14
Nodes (15): test_bloque_con_texto_solo_espacios_se_descarta(), test_detectar_cambios_leyes_vigiladas_crea_propuesta_pendiente(), test_detectar_cambios_leyes_vigiladas_no_duplica_si_ya_hay_propuesta_pendiente_reciente(), test_verificar_bloque_temas_referenciados_detecta_tema_inexistente(), test_verificar_bloque_temas_referenciados_no_duplica_entre_leyes(), test_verificar_bloque_temas_referenciados_sin_faltantes_si_todo_existe(), detectar_cambios_leyes_vigiladas(), _doc_estado() (+7 more)

### Community 89 - "toast"
Cohesion: 0.24
Nodes (14): api(), cambiarEstadoAvisoOficial(), cambiarEstadoCambioTemario(), cambiarEstadoReporte(), cambiarEstadoSoporte(), _crearAvisoManual(), _guardarEdicionAviso(), inputLocalAIso() (+6 more)

### Community 91 - "resultados-test.js"
Cohesion: 0.31
Nodes (13): acortarTitulo(), agruparPorTema(), calcularEstadisticas(), calcularEstadisticasSinDudas(), calcularMejorRacha(), descargarResultadosPDF(), escaparHtml(), formatearExplicacionHTML() (+5 more)

### Community 92 - "test_repaso_espaciado.py"
Cohesion: 0.36
Nodes (11): _id_pregunta(), _con_sesion(), _pregunta_base(), Pruebas del repaso espaciado aplicado a los tests generados desde el banco de…, test_generar_test_fallos_a_igualdad_prioriza_la_mas_antigua(), test_generar_test_fallos_prioriza_la_mas_fallada(), test_generar_test_favoritas_marca_fecha_ultimo_repaso(), test_generar_test_favoritas_prioriza_la_nunca_repasada() (+3 more)

### Community 93 - "oposicionActual"
Cohesion: 0.29
Nodes (13): apiGet(), buscarYEditarPregunta(), cargarChunks(), cargarPreguntas(), _idValido(), modalImportar(), modalPregunta(), oposicionActual() (+5 more)

### Community 95 - "ui"
Cohesion: 0.19
Nodes (5): di(), hi, onConfigChange(), setElementSelectors(), ui()

### Community 96 - "podar_temario_age_bloque4_tema9.py"
Cohesion: 0.26
Nodes (12): _estimar_tokens(), _extraer_rango(), guardar_preview(), _localizar_articulos(), main(), procesar(), Poda el TRLGSS (RDL 8/2015) ya cargado en Temario AGE/bloque_04/tema_09 ("El…, Comprime una lista de números de artículo en rangos legibles, p.ej. [1,2,3,5,6]… (+4 more)

### Community 97 - "_fecha_hace"
Cohesion: 0.23
Nodes (3): _fecha_hace(), TestDetectarAvisosOficialesBackfillYEstado, TestFechasARevisar

### Community 99 - "podar_temario_gace_bloque2_temas1_5.py"
Cohesion: 0.27
Nodes (11): _extraer_rango(), guardar_preview(), _localizar_articulado_principal(), _localizar_protocolo(), main(), procesar(), Poda el TUE y el TFUE ya cargados en Temario GACE/bloque_02 (temas 1-5) a solo…, (offsets, fin) del articulado real del Tratado -- ver… (+3 more)

### Community 100 - "test_webhook_stripe.py"
Cohesion: 0.32
Nodes (11): _evento(), _firmar(), _post_evento(), Pruebas del webhook de Stripe: la ruta que decide si alguien pasa a tener una…, test_webhook_acepta_firma_valida_y_no_reprocesa_el_mismo_evento(), test_webhook_checkout_completado_activa_suscripcion(), test_webhook_con_firma_de_otro_timestamp_muy_antiguo_se_rechaza(), test_webhook_payment_failed_marca_past_due_y_avisa_por_email() (+3 more)

### Community 101 - "coleccion_banco_preguntas"
Cohesion: 0.31
Nodes (9): coleccion_banco_preguntas(), guardar_pregunta_generada(), Repositorio interno de preguntas de Test Personalizado ya generadas y…, Guarda una pregunta de Test Personalizado ya verificada en el banco de esa…, Pruebas del repositorio interno de preguntas ya generadas y verificadas…, test_coleccion_banco_preguntas_oposicion_no_valida_cae_a_la_de_defecto(), test_coleccion_banco_preguntas_separa_por_oposicion(), test_guardar_pregunta_generada_escribe_los_campos_esperados() (+1 more)

### Community 102 - "_temas_mencionados"
Cohesion: 0.27
Nodes (11): _indice_palabras_por_tema(), _palabras_significativas(), Palabra significativa del TÍTULO COMPLETO -> conjunto de ids de tema que la…, Compara el mensaje (normalizado, sin acentos) contra el título de cada tema del…, _temas_mencionados(), _catalogo(), test_palabra_generica_compartida_por_dos_temas_no_dispara_por_si_sola(), test_titulo_compuesto_separado_por_punto_y_dos_puntos_permite_coincidir_con_una_sola_parte() (+3 more)

### Community 103 - "responder_tutor_stream"
Cohesion: 0.18
Nodes (8): _modelo_tutor(), responder_tutor_stream(), El modelo de DeepSeek que usa Tu Tutor es configurable sin redeploy vía…, test_responder_tutor_stream_emite_deltas_y_guarda_al_final(), test_responder_tutor_stream_emite_error_si_deepseek_no_devuelve_nada(), test_stream_incluye_temas_relacionados_para_generar_test(), test_stream_sin_tema_concreto_no_incluye_acciones_de_tema(), TestModeloConfigurable

### Community 104 - "sembrar_usuario_activo"
Cohesion: 0.40
Nodes (10): Siembra usuarios/{uid} con una suscripción de pago ya activa (evita tener que…, sembrar_usuario_activo(), _con_sesion(), Pruebas de marcar/desmarcar preguntas como favoritas y de generar un test a…, test_desmarcar_favorita(), test_favoritas_no_se_mezclan_entre_oposiciones(), test_generar_test_favoritas_filtra_por_tema(), test_generar_test_favoritas_sin_favoritas_avisa() (+2 more)

### Community 105 - "wireFichaVista"
Cohesion: 0.31
Nodes (11): abrirModal(), abrirUsuario(), cargarUsuarios(), cerrarModal(), descargarCSV(), fichaPlanBadge(), modalCrearUsuario(), pintarFicha() (+3 more)

### Community 106 - "manifest.json"
Cohesion: 0.18
Nodes (10): background_color, description, display, icons, lang, name, scope, short_name (+2 more)

### Community 107 - "podar_temario_age_bloque5_tema6.py"
Cohesion: 0.33
Nodes (10): _estimar_tokens(), _extraer_rango(), guardar_preview(), _localizar_articulos(), main(), procesar(), Poda la Ley 47/2003, General Presupuestaria (LGP), ya cargada entera en Temario…, _resumen_rangos() (+2 more)

### Community 108 - "TestCallDeepseekApiStream"
Cohesion: 0.31
Nodes (3): call_deepseek_api_stream: solo se reintenta la CONEXIÓN inicial (antes de ceder…, _respuesta_stream(), TestCallDeepseekApiStream

### Community 109 - "test_marcadas_duda.py"
Cohesion: 0.33
Nodes (10): _con_sesion(), Pruebas de "marcar pregunta como duda": el usuario puede marcar una pregunta…, test_autosave_guarda_marcadas_duda(), test_autosave_sin_marcadas_duda_por_defecto_vacio(), test_guardar_test_excluye_dudas_de_la_nota_final(), test_guardar_test_persiste_marcada_duda_por_pregunta(), test_guardar_test_si_se_marcan_todas_como_duda_se_cuentan_igual(), test_guardar_test_sin_marcadas_duda_por_defecto_false() (+2 more)

### Community 110 - "cargar_temario_boe.py"
Cohesion: 0.31
Nodes (9): clasificar_subbloque(), construir_subbloques_clasificados(), guardar_preview(), main(), Carga automática de un "Código electrónico" del BOE (una recopilación de leyes…, La sección romana N del SUMARIO (que incluye 'I. INTRODUCCIÓN') es el bloque…, _ruta_cache_paginas(), seccion_a_bloque() (+1 more)

### Community 111 - "planes/script.js"
Cohesion: 0.24
Nodes (7): CONFIANZA, ctaPrueba, inicializarSelectorOposicion(), marcarPlanActual(), mensajeCheckout, restaurarBotones(), selectorOposicion

### Community 112 - "obtener_estadisticas_completas_usuario"
Cohesion: 0.29
Nodes (9): obtener_estadisticas_completas_usuario(), Suma las preguntas dejadas en blanco en todos los tests finalizados de esta…, Obtener estadísticas completas del usuario para UNA OPOSICIÓN (test,…, _total_blancos_usuario(), Prueba de que /estadisticas-completas suma las preguntas en blanco de todos los…, test_incluye_historial_tests_para_la_grafica_de_evolucion(), test_incluye_paginas_analizadas_para_otra_actividad(), test_total_blancos_cero_sin_tests() (+1 more)

### Community 113 - "test_autosave_resume.py"
Cohesion: 0.36
Nodes (9): _con_sesion(), Pruebas del autoguardado y reanudación de tests (rutas_progreso.py): que el…, test_autosave_corrige_documento_id_en_un_guardado_posterior(), test_autosave_posterior_no_borra_el_contenido_ya_guardado(), test_autosave_sin_documento_id_no_borra_el_ya_guardado(), test_autosave_sin_test_id_devuelve_error(), test_primer_autosave_crea_el_borrador_completo(), test_ultimo_test_devuelve_404_si_solo_hay_borradores() (+1 more)

### Community 114 - "TestGenerarConContinuacion"
Cohesion: 0.31
Nodes (3): generar_con_continuacion: usada por /resumir-documento y /generar-esquema-…, _respuesta_con_status(), TestGenerarConContinuacion

### Community 115 - "obtener_contexto_por_temas_exactos"
Cohesion: 0.47
Nodes (9): _contar_tokens_por_palabras(), Pruebas de utils.obtener_contexto_por_temas_exactos: el RAG de Tu Tutor. Antes…, _sembrar_subbloque(), test_incluye_por_relevancia_no_por_orden_de_almacenamiento(), test_no_truncado_cuando_todo_cabe(), test_sin_mensaje_conserva_el_orden_original_por_id(), test_tras_fragmento_grande_poco_relevante_que_no_cabe_sigue_probando_otros(), obtener_contexto_por_temas_exactos() (+1 more)

### Community 116 - "test_soporte.py"
Cohesion: 0.31
Nodes (7): _como(), Pruebas del mensaje de soporte/contacto desde Mi Cuenta: POST /mi-…, test_contactar_guarda_mensaje_pendiente(), test_reportes_pendientes_suma_soporte_y_preguntas(), test_soporte_con_permiso_reportes_accede(), test_soporte_sin_permiso_reportes_403(), test_usuario_contacta_y_admin_lo_revisa()

### Community 117 - "Esquema de datos en Firestore"
Cohesion: 0.22
Nodes (8): `datos_convocatoria/{oposicion}`, Esquema de datos en Firestore, Exámenes oficiales, Notas, `stripe_events/{event_id}`, Subcolecciones de `usuarios/{uid}`, Temario oficial, `usuarios/{uid}`

### Community 118 - "generar_sitemap.py"
Cohesion: 0.36
Nodes (8): _canonical(), _es_publica(), generar(), _lastmod(), _prefijos_disallow(), _prioridad(), Regenera frontend/sitemap.xml a partir de las páginas públicas reales. No se…, P. ej. 'Disallow: /subida-pdf-*/' -> prefijo '/subida-pdf-' (todo lo anterior…

### Community 119 - "_sembrar_tema"
Cohesion: 0.22
Nodes (9): _sembrar_tema(), test_analitica_agrega_rendimiento_y_sin_actividad(), test_cambios_temario_aprobar_aplica_el_cambio_al_chunk(), test_cambios_temario_aprobar_falla_si_el_chunk_ya_no_coincide(), test_cambios_temario_descartar_no_toca_el_chunk(), test_permiso_temario_puede_editar_pero_no_usuarios(), test_temario_arbol_y_chunks(), test_temario_editar_y_borrar_chunk() (+1 more)

### Community 121 - "temario.py"
Cohesion: 0.36
Nodes (7): avisos_oficiales(), obtener_oposiciones_disponibles(), obtener_temas_disponibles(), progreso_usuario(), route, Rutas de consulta del catálogo de oposiciones y su temario., Avisos oficiales ya publicados (convocatorias, listas de admitidos, fechas de…

### Community 122 - "plan.js"
Cohesion: 0.39
Nodes (7): claveCache(), mostrarPantallaBloqueo(), NOMBRE_PLAN, obtenerPlan(), ORDEN_PLANES, planCubre(), protegerPagina()

### Community 123 - "limpiar_titulos_vacio_temario.py"
Cohesion: 0.39
Nodes (7): conectar_firestore(), corregir_en_firestore(), encontrar_titulos_a_corregir(), guardar_preview(), main(), Limpia el marcador literal "VACIO" / "(VACIO)" que quedó pegado al final del…, Recorre las 3 colecciones y devuelve una lista de (coleccion, bloque_id,…

### Community 124 - "package.json"
Cohesion: 0.25
Nodes (7): devDependencies, @playwright/test, name, private, scripts, test:e2e, @playwright/test

### Community 125 - "Arrancar en local"
Cohesion: 0.25
Nodes (7): Arrancar en local, Backend, Desplegar, Domina tu Opo, Estructura del repo, Frontend, Tests

### Community 126 - "test_ranking.py"
Cohesion: 0.43
Nodes (7): _con_sesion(), Pruebas de la clasificación anónima y opcional (blueprints/ranking.py): que…, test_ranking_ordenado_por_racha_actual_descendente(), test_ranking_vacio_si_nadie_se_ha_apuntado(), test_salir_del_ranking_lo_oculta_sin_borrar_la_racha(), test_unirse_aparece_en_el_ranking_con_alias_no_con_email(), test_unirse_con_alias_invalido_devuelve_error()

### Community 127 - "obtener_catalogo_temas"
Cohesion: 0.38
Nodes (7): Devuelve un dict con el saludo inicial personalizado, un mensaje de…, sugerencia_inicial_usuario(), test_saludo_de_vuelta_y_sugerencias_de_examen_para_usuario_con_historia(), test_sugerencia_inicial_recomienda_practicar_el_tema_mas_flojo(), test_sugerencia_inicial_usuario_nuevo_sin_tests_no_tiene_accion(), test_obtener_catalogo_temas_usa_cache_hasta_que_se_limpia(), obtener_catalogo_temas()

### Community 128 - "push.js"
Cohesion: 0.43
Nodes (4): activarNotificaciones(), base64UrlAClaveBytes(), notificacionesActivas(), pushDisponibleEnNavegador()

### Community 129 - "test_fecha_examen.py"
Cohesion: 0.48
Nodes (6): _con_sesion(), Pruebas de /fecha-examen: guardar, leer y borrar la fecha de examen que el…, test_fecha_examen_formato_invalido_devuelve_error(), test_fecha_examen_no_se_mezcla_entre_oposiciones(), test_fecha_examen_vacia_la_borra(), test_guardar_y_leer_fecha_examen()

### Community 131 - "test_mi_perfil.py"
Cohesion: 0.48
Nodes (6): _con_sesion(), Pruebas de /mi-perfil: en particular, que un administrador (custom claim de…, test_mi_perfil_admin_con_plan_de_pago_sigue_dando_premium(), test_mi_perfil_admin_sin_documento_de_usuario_da_premium(), test_mi_perfil_admin_sin_plan_ni_prueba_da_premium(), test_mi_perfil_usuario_normal_sin_plan_ni_prueba_da_gratis()

### Community 133 - "_guardar_turno"
Cohesion: 0.33
Nodes (6): _actualizar_memoria_cruzada(), agregar_mensaje_a_conversacion(), crear_conversacion(), _guardar_turno(), _resumir_memoria_cruzada(), test_anadir_mensaje_a_conversacion_inexistente_la_crea()

### Community 134 - "conftest.py"
Cohesion: 0.47
Nodes (5): client(), flask_app(), _limpiar_fake_db(), fixture, Configuración compartida de pytest: prepara variables de entorno dummy y…

### Community 135 - "favoritas.js"
Cohesion: 0.47
Nodes (3): activarBotonFavorita(), desmarcarFavorita(), marcarFavorita()

### Community 136 - "OPOSICIONES"
Cohesion: 0.73
Nodes (5): cambiarOposicionYRecargar(), establecerOposicionActual(), inyectarSelectorOposicion(), obtenerOposicionActual(), OPOSICIONES

### Community 137 - "displaySurvey"
Cohesion: 0.33
Nodes (3): canRenderSurvey(), displaySurvey(), renderSurvey()

### Community 138 - "getSurveys"
Cohesion: 0.33
Nodes (3): canRenderSurveyAsync(), getSurveys(), ma

### Community 139 - "tutor-widget.js"
Cohesion: 0.47
Nodes (3): aplicarEnfasis(), escapeHtml(), formatearMensajeBot()

### Community 140 - "datos-personales/script.js"
Cohesion: 0.60
Nodes (5): guardarDatosBasicos(), iniciar(), intentarCambiarEmail(), mostrarMensaje(), pedirPassword()

### Community 141 - "resultado/script.js"
Cohesion: 0.53
Nodes (5): cargarTemas(), formatearFecha(), inicializar(), TIPO_INFO, tipoInfo()

### Community 142 - "ranking/script.js"
Cohesion: 0.80
Nodes (5): escaparHtml(), iniciar(), renderizarFormularioUnirse(), renderizarLista(), renderizarParticipando()

### Community 143 - "limpiar_subdivisiones_vacias.py"
Cohesion: 0.53
Nodes (5): conectar_firestore(), limpiar(), main(), parsear_bloque_tema(), Borra las subdivisiones ("subbloques") con el campo "texto" vacío dentro de…

### Community 144 - "test_borrar_test.py"
Cohesion: 0.53
Nodes (5): _con_sesion(), Borrado de tests propios (finalizados y en progreso) desde Mis Tests., test_borrar_test_de_otro_usuario_no_lo_afecta(), test_borrar_test_en_progreso(), test_borrar_test_finalizado()

### Community 146 - "test_error_handler.py"
Cohesion: 0.53
Nodes (5): _app_con_manejador(), Prueba del manejador de errores global (@app.errorhandler(Exception) en…, test_error_http_normal_sigue_devolviendo_su_propia_respuesta(), test_excepcion_no_controlada_devuelve_500_json_consistente(), test_excepcion_no_controlada_no_filtra_el_traceback()

### Community 147 - "test_rate_limiter.py"
Cohesion: 0.53
Nodes (5): _app_con_limite(), Pruebas del freno de ráfaga en los endpoints de IA (rate_limiter.py). Igual que…, test_limite_10_por_minuto_corta_pasado_el_limite(), test_limite_20_por_minuto_corta_pasado_el_limite(), test_limite_5_por_minuto_corta_pasado_el_limite()

### Community 148 - "diagnosticar_usuario.py"
Cohesion: 0.60
Nodes (4): conectar_firestore(), diagnosticar(), main(), Herramienta de solo lectura para investigar el estado real de una cuenta…

### Community 149 - "popover.js"
Cohesion: 0.80
Nodes (4): activarPopover(), cerrarAbiertos(), instalarCierreGlobal(), primerElementoFocable()

### Community 150 - "migrar_usuarios_a_suscripciones.py"
Cohesion: 0.60
Nodes (4): conectar_firestore(), main(), migrar(), Migración única: antes de que la web soportara varias oposiciones, cada usuario…

### Community 151 - "nav.spec.js"
Cohesion: 0.50
Nodes (3): mockNav(), moduloFirebaseAuth(), { test, expect }

### Community 154 - "avisos_oficiales_editar"
Cohesion: 0.50
Nodes (4): avisos_oficiales_editar(), _leer_oposiciones_de_datos(), Lista de oposiciones de un payload de alta/edición de aviso -- "oposiciones":…, Corrige el CONTENIDO de un aviso ya creado -- título, tipo, enlaces,…

### Community 155 - "preguntas_export"
Cohesion: 0.50
Nodes (4): preguntas_export(), Genera un CSV descargable (UTF-8 con BOM para que Excel respete los acentos)., Descarga todas las preguntas de una oposición en CSV., _respuesta_csv()

### Community 156 - "analytics.js"
Cohesion: 0.67
Nodes (3): cargarPostHog(), CLAVE_COOKIES_ACEPTADAS, iniciarAnalitica()

### Community 158 - "firebase-config.js"
Cohesion: 0.50
Nodes (3): BACKEND_URL, firebaseConfig, RECAPTCHA_SITE_KEY

### Community 160 - "temas-numeracion.js"
Cohesion: 0.67
Nodes (3): agruparTemasPorBloque(), numeroRomano(), ROMANOS

### Community 161 - "listar_temas_vacios.py"
Cohesion: 0.67
Nodes (3): conectar_firestore(), main(), Diagnóstico de solo lectura: recorre las 3 colecciones de Temario (AGE, GACE,…

### Community 171 - "_eventos_sse"
Cohesion: 0.67
Nodes (3): _eventos_sse(), test_ruta_tu_tutor_stream_emite_eventos_y_registra_uso(), test_ruta_tu_tutor_stream_no_registra_uso_si_deepseek_falla()

### Community 172 - "buscar_pregunta_oficial"
Cohesion: 0.67
Nodes (3): test_buscar_pregunta_oficial_por_contencion_del_enunciado(), buscar_pregunta_oficial(), Busca en el banco de exámenes oficiales de la oposición una pregunta cuyo…

## Knowledge Gaps
- **266 isolated node(s):** `PERMISO_POR_PESTANA`, `modal`, `modalContenido`, `GRUPOS`, `RENDERS` (+261 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `oposicionActual()` connect `oposicionActual` to `repasar-preguntas/script.js`, `test-personalizado/script.js`, `wireFichaVista`, `subida-pdf-generar-test/script.js`, `admin/script.js`, `test-oficial/script.js`, `preguntas-falladas/script.js`, `preguntas-favoritas/script.js`, `repetir-test/script.js`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `p()` connect `warn` to `posthog-array.js`, `ya`, `g`, `test-personalizado/script.js`, `info`, `De`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Why does `entrarEnModoTest()` connect `test-personalizado/script.js` to `warn`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **What connects `PERMISO_POR_PESTANA`, `modal`, `modalContenido` to the rest of the system?**
  _266 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_admin.py` be split into smaller, more focused modules?**
  _Cohesion score 0.03582554517133956 - nodes in this community are weakly interconnected._
- **Should `posthog-array.js` be split into smaller, more focused modules?**
  _Cohesion score 0.03416728902165796 - nodes in this community are weakly interconnected._
- **Should `ya` be split into smaller, more focused modules?**
  _Cohesion score 0.043467643467643466 - nodes in this community are weakly interconnected._