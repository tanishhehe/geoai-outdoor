# Works as a Hugging Face Space (SDK: docker, port 7860) or on any container host.
FROM python:3.11-slim
ARG SLM_MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct
ENV SLM_MODEL_ID=${SLM_MODEL_ID} SLM_BACKEND=transformers PYTHONUNBUFFERED=1 HF_HOME=/models
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt
# bake weights into the image so cold starts do not depend on the Hub
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('${SLM_MODEL_ID}')"
COPY app ./app
COPY static ./static
ENV CONTACT_EMAIL=change-me@example.com
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
