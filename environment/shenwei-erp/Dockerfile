# 构建上下文是 环境/（compose 里 context: .），因为要一起装 shenwei-mockkit
FROM python:3.12-slim
WORKDIR /app
COPY shenwei-mockkit /app/shenwei-mockkit
COPY shenwei-erp /app/shenwei-erp
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ /app/shenwei-mockkit /app/shenwei-erp
ENV ERP_DB=/data/erp.db ERP_PORT=9100 ERP_SCENARIOS=/app/shenwei-erp/scenarios ERP_OPENAPI_OUT=/data/erp-v1.json
VOLUME /data
EXPOSE 9100
CMD ["python", "-m", "shenwei_erp"]
