FROM python:3.11-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rotation_agent.py .

EXPOSE 5003

CMD ["python", "rotation_agent.py"]
