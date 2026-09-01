FROM python:3.12-slim

WORKDIR /app
COPY app ./app
COPY data ./data
COPY examples ./examples

ENTRYPOINT ["python", "-m", "app.cli"]
CMD ["examples/smoke_notes.jsonl"]

