up:
	docker compose up -d
etl:
	python -m etl.run --all
etl-extract:
	python -m etl.run --extract
etl-transform:
	python -m etl.run --transform
etl-load:
	python -m etl.run --load
test:
	pytest -q
api:
	uvicorn api.main:app --reload
reset:
	docker compose down -v
