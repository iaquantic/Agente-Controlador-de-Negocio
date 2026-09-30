# 2. Arquitectura

## 2.1 Vista general

```
                  ┌───────────────────────── VPS (fuera de Cuba) ─────────────────────────┐
 Dueño            │  Servicio Python "agente-interno"                                      │
 (Telegram) ─────▶│  ├─ Adaptador Telegram (long polling/webhook)                          │
                  │  │    └─ Autorización por ID numérico + límite 30 consultas/h          │
 Futuro           │  ├─ API interna  POST /v1/consulta  (token secreto)                    │
 Orquestador ────▶│  ├─ Núcleo del agente: modelo Claude + 12 herramientas                 │
                  │  │    └─ Validación de parámetros (esquemas) antes de cada llamada     │
                  │  ├─ Planificador: resumen 19:30 · revisión de alertas cada 30 min      │
                  │  │    └─ Anti-repetición 24 h · máx. 3 urgentes/día · silencio 21–8    │
                  │  ├─ Registro (esquema `registro`)                                       │
                  │  └─ Caché de informes (5 min)                                           │
                  │                                                                         │
                  │  Proceso "alimentador" (cron 23:50, usuario y credenciales propios)    │
                  └────────────┬───────────────────────────────────────┬──────────────────┘
                               │ rol agente_lectura (solo EXECUTE       │ rol alimentador
                               │ sobre funciones del esquema agente)    │ (escritura)
                  ┌────────────▼───────────────────────────────────────▼──────────────────┐
                  │ Supabase · PostgreSQL (MercadoMVP)                                     │
                  │  ├─ agente    : 12 funciones de lectura (SECURITY DEFINER, STABLE)     │
                  │  ├─ public    : tablas del negocio (invisibles para agente_lectura)    │
                  │  ├─ registro  : log de interacciones y alertas enviadas (servicio)     │
                  │  └─ simulador : estado del alimentador (invisible para el agente)      │
                  └────────────────────────────────────────────────────────────────────────┘
```

## 2.2 Componentes
| Componente | Responsabilidad | Tecnología |
|---|---|---|
| Adaptador Telegram | Recibir mensajes/comandos/botones, enviar respuestas | python-telegram-bot o aiogram |
| Autorización | Aceptar solo `TELEGRAM_OWNER_ID`; rechazar y registrar el resto | Middleware |
| Núcleo del agente | Bucle de uso de herramientas con Claude, system prompt (9) | SDK de Anthropic |
| Capa de herramientas | Traduce cada herramienta a `select agente.<funcion>(...)`; valida parámetros | psycopg + pydantic |
| Planificador | Resumen diario, detección periódica de alertas, anti-spam | APScheduler |
| API interna | Contrato con el orquestador (8) | FastAPI |
| Registro | Log de cada interacción, herramienta y alerta | Esquema `registro` |
| Alimentador | Genera la actividad diaria del negocio de demostración | Python + SQL |

## 2.3 Flujos

**Pregunta del dueño**
1. Telegram → autorización (ID) → límite de uso.
2. Núcleo: system prompt + historial corto + pregunta → Claude decide herramientas.
3. Cada llamada: validar parámetros → `agente.<funcion>` con rol de solo lectura → JSON.
4. Claude redacta la respuesta (formato Telegram, marcas 📊💡❔).
5. Filtro de salida (sin SQL, IDs internos, credenciales, errores técnicos) → Telegram.
6. Registro.

**Resumen diario (19:30)**: `get_business_summary` + `get_alerts` + `get_data_quality` → Claude redacta → Telegram → registro.

**Alertas urgentes (cada 30 min, 8:00–21:00)**: `get_alerts(prioridad_minima='urgent')` → descartar las enviadas en 24 h y respetar máx. 3/día → Claude redacta → Telegram. Las detectadas entre 21:00 y 8:00 se envían a las 8:00.

**Orquestador**: `POST /v1/consulta` (token) → informe predefinido, pregunta o herramienta → JSON (8) → registro. Nunca envía mensajes al dueño.

## 2.4 Decisiones clave
| Decisión | Motivo |
|---|---|
| Sin SQL libre; 12 herramientas | Métricas siempre calculadas igual, superficie de ataque mínima, testeable |
| Cálculos en funciones de PostgreSQL | Fuente única de verdad, reutilizable por el orquestador |
| Alertas por código, no por el modelo | Una alerta nunca se inventa ni se olvida |
| Rol de solo lectura sin acceso a tablas | Aunque el modelo quisiera escribir, la BD lo impide |
| Servidor fuera de Cuba | La API de Anthropic no está disponible desde Cuba |
| Alimentador separado | El negocio demo sigue vivo sin dar permisos de escritura al agente |

## 2.5 Variables de entorno
| Variable | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot de Telegram |
| `TELEGRAM_OWNER_ID` | ID numérico del dueño |
| `ANTHROPIC_API_KEY` | Modelo Claude |
| `DB_URL_AGENTE` | Conexión con rol `agente_lectura` |
| `DB_URL_SERVICIO` | Conexión para escribir en `registro` |
| `DB_URL_ALIMENTADOR` | Conexión del alimentador |
| `ELTOQUE_API_KEY` | Tasa diaria (solo el alimentador) |
| `ORQUESTADOR_TOKEN` | Autenticación de la API interna |
| `NEGOCIO_ID` | Negocio que atiende esta instancia |
