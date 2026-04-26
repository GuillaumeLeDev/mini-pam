FROM python:3.11-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bastion.py .

RUN mkdir -p /data

EXPOSE 5002

CMD ["python", "bastion.py"]
