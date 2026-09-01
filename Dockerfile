# Containerizes the current Streamlit review app + entity_screening pipeline.
#
# docs/requirements.md Section 9a calls for "a Dockerfile for the API layer" —
# that FastAPI layer doesn't exist yet (it's a separate architecture change
# pending review), so this wraps what's actually built today instead of
# presuming that shape. Expect this to be revisited once the API layer lands
# — likely a second, thinner image for the API service, with this one
# adjusted to run Streamlit as a client of it rather than calling the
# pipeline directly.
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
