.PHONY: test test-quick test-snapshots docker-build

DOCKER_IMAGE := gimera-test

docker-build:
	docker build -f Dockerfile.test -t $(DOCKER_IMAGE) .

test: docker-build
	docker run --rm $(DOCKER_IMAGE) pytest gimera/tests/ -v --tb=short

test-quick: docker-build
	docker run --rm $(DOCKER_IMAGE) pytest gimera/tests/test_gimera.py -v --tb=short

test-snapshots: docker-build
	docker run --rm $(DOCKER_IMAGE) pytest gimera/tests/test_snapshots_complex.py -v --tb=short
