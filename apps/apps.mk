# Цели для demo-сервисов. Подключается строкой `include apps/apps.mk` в конце корневого Makefile.
# (.RECIPEPREFIX = > задан в корневом Makefile)

IMAGE_TAG ?= dev

# Собрать образы и загрузить их в локальный кластер k3d
apps-images: cluster
> docker build -f apps/Dockerfile --build-arg MODULE=gateway -t gateway:$(IMAGE_TAG) apps
> docker build -f apps/Dockerfile --build-arg MODULE=orders -t orders:$(IMAGE_TAG) apps
> k3d image import gateway:$(IMAGE_TAG) orders:$(IMAGE_TAG) -c $(CLUSTER)

# Пересобрать образы и перезапустить поды (после правок кода)
apps-reload: apps-images
> kubectl -n demo rollout restart deploy/gateway deploy/orders
> kubectl -n demo rollout status deploy/gateway deploy/orders --timeout=180s

# Тесты в контейнере Maven (на хосте Java и Maven не нужны). Исходники копируются, в репозитории ничего не создаётся.
apps-test:
> docker run --rm -v "$(CURDIR)/apps:/src:ro" -v sre-m2:/root/.m2 maven:3.9-eclipse-temurin-21 \
>   sh -c 'cp -r /src /work && cd /work && mvn -B test'

# make up теперь собирает образы перед Terraform
up: apps-images

.PHONY: apps-images apps-reload apps-test
