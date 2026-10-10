FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi httpx numpy faiss-cpu sqlalchemy pymysql python-dotenv requests lxml pandas
WORKDIR /work
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NO_MARKET_REFRESH=1 UI_PREWARM=0
CMD ["python", "tests/offline_xml_server.py", "--fixture", "/fixture", "--report", "/results/linux.json"]
