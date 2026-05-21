FROM python:3.12-slim
WORKDIR /app

# Install SDK first so it's cached when only app code changes
COPY sdk/ /sdk/
RUN pip install --no-cache-dir /sdk

COPY chatbot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY chatbot/ .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
