# Agente Controlador de Negocio — Agente Interno (MVP)

Agente de **solo lectura** que analiza la base de datos de un comercio minorista cubano (tienda física + web)
y conversa con su dueño por Telegram. Es la primera pieza de la arquitectura:

```
AGENTE ORQUESTADOR
├── AGENTE INTERNO  ← este repositorio
│   └── Base de datos del negocio (Supabase · MercadoMVP)
└── AGENTE EXTERNO
    └── Información de mercado
```

## Estructura
| Ruta | Contenido |
|---|---|
| `docs/especificacion/` | Los 10 entregables de diseño (especificación, arquitectura, herramientas, reglas, seguridad, contratos, pruebas) |
| `prompts/agente_interno_system_prompt.md` | System prompt definitivo |
| `docs/decisiones.md` | Registro de decisiones de la entrevista (fases 1–8) |
| `docs/casos_de_uso.md` | 30 preguntas reales del dueño |
| `supabase/migrations/` | Esquema de la base de datos |
| `scripts/demo/` | Catálogo, tasas reales de elTOQUE y generador del historial del negocio de demostración |
| `agente_interno/` | Servicio: agente (Claude), bot de Telegram, planificador, API del orquestador, registro |
| `agente_interno/importador/` | Importador de los datos de un negocio real desde CSV o Excel ([docs/IMPORTACION.md](docs/IMPORTACION.md)) |
| `tests/` | Pruebas automáticas (ver `tests/README.md`) |

## Estado
- ✅ Diseño completo y validado (`docs/especificacion/`).
- ✅ Base de datos MercadoMVP con 12 meses de historial y el esquema `agente` (12 herramientas de solo lectura, roles y registro).
- ✅ Servicio Python: bot de Telegram, Claude con las 12 herramientas, alertas y resumen diario, API para el orquestador.
- ✅ Pruebas: 79 automáticas (herramientas, seguridad, servicio, orquestador) + 17 conversacionales con Claude.
- ✅ Importador de datos reales: catálogo, ventas, compras, devoluciones, inventario y tasas desde CSV o Excel, con
  validación por fila, stock y coste medio reconstruidos y base de datos nueva por cliente ([docs/IMPORTACION.md](docs/IMPORTACION.md)).
- ⏳ Pendiente: recibir los archivos del cliente por Telegram (hoy llegan a la carpeta del servidor) y desplegar con un negocio real.

## Arranque rápido
Ver **[docs/DESPLIEGUE.md](docs/DESPLIEGUE.md)**: crear el bot, activar los usuarios de la base de datos, rellenar `.env` y
`python -m agente_interno`.

Para un **negocio real**, antes: base de datos nueva y carga de sus datos con el importador
(**[docs/IMPORTACION.md](docs/IMPORTACION.md)**).
