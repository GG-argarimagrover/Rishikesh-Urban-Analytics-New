.PHONY: install test demo serve docker
install:
	pip install -e ".[dev]"
test:
	pytest -q
demo:            ## offline demo → output/demo/Rishikesh_Dashboard.html
	rishikesh-urban run --config data/sample/config.sample.yaml
serve:           ## web app on http://127.0.0.1:8000
	rishikesh-urban serve
docker:
	docker build -t rishikesh-urban . && docker run --rm -p 8000:8000 -v rui-data:/data rishikesh-urban
