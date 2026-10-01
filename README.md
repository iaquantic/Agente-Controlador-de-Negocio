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
| `tests/` | Pruebas automáticas (ver `tests/README.md`) |

## Estado
- ✅ Diseño completo y validado (`docs/especificacion/`).
- ✅ Base de datos MercadoMVP con 12 meses de historial y el esquema `agente` (12 herramientas de solo lectura, roles y registro).
- ✅ Servicio Python: bot de Telegram, Claude con las 12 herramientas, alertas y resumen diario, API para el orquestador.
- ✅ Pruebas: 79 automáticas (herramientas, seguridad, servicio, orquestador) + 17 conversacionales con Claude.
- ⏳ Pendiente: desplegar en un VPS (ver `docs/DESPLIEGUE.md`) y el alimentador diario de datos de demostración.

## Arranque rápido
Ver **[docs/DESPLIEGUE.md](docs/DESPLIEGUE.md)**: crear el bot, activar los usuarios de la base de datos, rellenar `.env` y
`python -m agente_interno`.
