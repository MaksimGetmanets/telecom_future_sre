# Генерация правил Prometheus из SLO-спецификаций Sloth. Подключается строкой `include observability/slo/slo.mk`.
# Результат (observability/alerts/generated/*.yaml) лежит в git, так что `make up` Sloth не требует:
# перегенерируйте и закоммитьте файлы после правки observability/slo/*.yaml.
SLOTH_IMAGE ?= ghcr.io/slok/sloth:v0.16.0

slo-gen:
> mkdir -p observability/alerts/generated
> for svc in gateway orders; do \
>   docker run --rm -u "$$(id -u):$$(id -g)" -v "$(CURDIR)/observability:/o" $(SLOTH_IMAGE) generate \
>     -i /o/slo/$$svc.yaml -o /o/alerts/generated/sloth-$$svc.yaml \
>     --slo-period-windows-path /o/slo/windows --no-log || exit 1; \
>   sed -i '/^---$$/d' observability/alerts/generated/sloth-$$svc.yaml; \
> done

.PHONY: slo-gen
