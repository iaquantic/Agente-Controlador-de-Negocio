FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Havana
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agente_interno ./agente_interno
COPY prompts ./prompts
COPY docs/especificacion/schemas ./docs/especificacion/schemas
RUN useradd --create-home agente && mkdir -p registro && chown agente registro
USER agente
CMD ["python", "-m", "agente_interno"]
