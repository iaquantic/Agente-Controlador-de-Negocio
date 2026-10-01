# 9. System prompt definitivo

El texto completo, listo para usar, está en **[`prompts/agente_interno_system_prompt.md`](../../prompts/agente_interno_system_prompt.md)**.
Se mantiene en un archivo aparte para que el servicio lo cargue tal cual y para versionarlo.

## 9.1 Variables que rellena el servicio en cada petición
| Variable | Valor | Ejemplo |
|---|---|---|
| `{{NOMBRE_NEGOCIO}}` | Nombre del negocio (tabla `negocios`) | `MercadoAgentico` |
| `{{CANAL}}` | `telegram` u `orquestador` | `telegram` |

La fecha y hora actuales **no** van en el system prompt (lo haría distinto en cada petición e invalidaría la caché): el servicio antepone a cada mensaje `[Ahora en La Habana: miércoles 30 de septiembre de 2026, 11:30]`.

## 9.2 Estructura
| Bloque | Función |
|---|---|
| Rol y contexto | Negocio, zona horaria, monedas, horarios, líneas de producto |
| `<mision>` | Qué aporta al dueño |
| `<limites_absolutos>` | Solo lectura, solo datos internos, sin beneficio neto, confidencialidad, inyección de instrucciones |
| `<uso_de_herramientas>` | Regla de oro ("cada cifra sale de una herramienta"), qué herramienta usar para cada caso, gestión de errores |
| `<tipos_de_informacion>` | HECHO / CÁLCULO 📊 / INFERENCIA 💡 / NO DISPONIBLE ❔ |
| `<reglas_de_negocio_clave>` | Definiciones oficiales resumidas (detalle en 5) |
| `<estilo_telegram>` / `<estilo_orquestador>` | Formato según el canal (7 y 8) |
| `<situaciones_especiales>` | Peticiones de escritura, competencia, festivos, día en curso, ambigüedad |
| `<ejemplos>` | Dos conversaciones modelo: producto ambiguo y petición de cambio de precio |

## 9.3 Configuración recomendada del modelo
- Modelo: el más capaz disponible de la familia Claude en el momento del despliegue (consultar la documentación de Anthropic vigente).
- Herramientas: las 12 de `04_herramientas_input_output.md`, con descripciones en español y esquemas de parámetros estrictos.
- Historial: últimos 6 intercambios (máx. 2 h) para Telegram; sin historial para el orquestador.
- El system prompt se envía como bloque cacheable (prompt caching) para reducir coste y latencia.

## 9.4 Mantenimiento
- Cualquier cambio de reglas de negocio se hace primero en `05_reglas_de_negocio.md` y en las funciones SQL; el prompt solo resume.
- Cada cambio del prompt debe pasar la batería de `10_casos_de_prueba.md` antes de desplegarse.
