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

## Estado
- ✅ Diseño completo y validado.
- ✅ Base de datos creada con 12 meses de historial (MercadoAgentico).
- ⏳ Por construir: funciones del esquema `agente` + rol de solo lectura, servicio Python (bot, modelo, planificador, API interna, registro), alimentador diario, ejecución de las pruebas.
