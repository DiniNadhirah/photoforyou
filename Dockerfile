# App image (used by docker-compose for the local cluster; Render can use
# the normal Python runtime instead).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=5000
EXPOSE 5000
CMD ["gunicorn", "app:app"]
