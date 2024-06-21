FROM python:3.12-slim

WORKDIR /code

EXPOSE 80

ENV PYTHONPATH=/code/app

COPY ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY ./app /code/app

CMD ["python", "/code/app/goe-e-solar-charger.py"]
