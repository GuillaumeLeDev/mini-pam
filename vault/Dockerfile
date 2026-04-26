FROM python:3.11-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY vault_api.py .

RUN mkdir -p /data

EXPOSE 5001

CMD ["python", "vault_api.py"]
