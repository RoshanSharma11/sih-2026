# Hugging Face Docker Space — Streamlit on 7860, FastAPI + streamer on localhost.
# https://huggingface.co/docs/hub/spaces-sdks-docker
FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user \
    && mkdir -p /home/user/app /home/user/.local \
    && chown -R user:user /home/user

USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SKYGUARD_API=http://127.0.0.1:8000 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHERUSAGESTATS=false

WORKDIR /home/user/app

# CPU torch only — default wheels pull CUDA and will OOM or bloat the image.
RUN pip install --user --no-cache-dir --upgrade pip \
    && pip install --user --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY --chown=user pyproject.toml ./
COPY --chown=user src ./src
RUN pip install --user --no-cache-dir -e ".[ui]"

COPY --chown=user . .
RUN chmod +x scripts/start_space.sh

EXPOSE 7860
CMD ["bash", "scripts/start_space.sh"]
