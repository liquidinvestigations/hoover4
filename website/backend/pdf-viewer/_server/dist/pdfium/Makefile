all: dev

clean:
	rm -rf ./src/vendor/pdfium.js ./src/vendor/pdfium.wasm ./src/vendor/pdfium.cjs

.PHONY: build
build:
	make clean
	docker buildx build -o docker .
