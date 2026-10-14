# Деплой стека на ВМ с k3s. Запускать НА САМОЙ ВМ из корня репозитория.
# (.RECIPEPREFIX = > задан в корневом Makefile)
#
#   make vm-setup               ansible: common + k3s + terraform на ВМ (спросит пароли vault и sudo)
#   make deploy                 terraform: стек наблюдаемости на ВМ-кластер (без demo-shop, пока нет образов в ghcr)
#   make deploy DEPLOY_APPS=yes то же + demo-shop (gateway, orders, postgres)
#   make deploy DEPLOY_EXTRA="-replace=helm_release.alloy"  пересоздать релиз (нужно один раз после добавления syslog в Alloy)
#   make deploy-status          что запущено в кластере
#   make chaos-enable           разрешить Chaos Mesh эксперименты в namespace demo
#   make chaos-status           поды и CRD Chaos Mesh

VM_KUBECONFIG ?= $(abspath kubeconfig-sre.yaml)
VM_CONTEXT    ?= sre-vm
DEPLOY_APPS   ?= no
# Образы из ghcr (публикует CI). Пустой IMAGE_REGISTRY= вернёт локальные :dev
IMAGE_REGISTRY ?= ghcr.io/maksimgetmanets
IMAGE_TAG      ?= develop
IMAGE_ARGS     = $(if $(IMAGE_REGISTRY),-var image_registry=$(IMAGE_REGISTRY) -var image_tag=$(IMAGE_TAG),)
# Доп. аргументы terraform apply, например DEPLOY_EXTRA="-replace=helm_release.alloy"
DEPLOY_EXTRA  ?=
VAULT_ARGS    ?= -e @group_vars/vault.yml --ask-vault-pass --ask-become-pass

# demo-shop нужны образы gateway/orders. На ВМ их нет, пока не настроена публикация в ghcr,
# поэтому по умолчанию применяем всё, кроме helm_release.demo_shop (и лишнего podinfo).
STACK_TARGETS = -target=helm_release.kps -target=helm_release.loki -target=helm_release.tempo \
                -target=helm_release.alloy -target=helm_release.dashboards \
                -target=helm_release.chaos_mesh -target=helm_release.alerts
ifeq ($(DEPLOY_APPS),yes)
DEPLOY_TARGETS =
else
DEPLOY_TARGETS = $(STACK_TARGETS)
endif

vm-setup:
> cd ansible && ansible-playbook site.yml $(VAULT_ARGS)

deploy:
> @test -f "$(VM_KUBECONFIG)" || { echo "Нет $(VM_KUBECONFIG). Сначала: make vm-setup"; exit 1; }
> cd terraform && terraform init -input=false && terraform apply -auto-approve -input=false \
>   -var kube_config_path=$(VM_KUBECONFIG) -var kube_context=$(VM_CONTEXT) $(IMAGE_ARGS) $(DEPLOY_TARGETS) $(DEPLOY_EXTRA)

# Разрешить Chaos Mesh бить по namespace demo (без аннотации эксперименты туда не пройдут)
chaos-enable:
> KUBECONFIG=$(VM_KUBECONFIG) kubectl get ns demo >/dev/null 2>&1 || { echo "Namespace demo ещё нет: сначала make deploy DEPLOY_APPS=yes"; exit 1; }
> KUBECONFIG=$(VM_KUBECONFIG) kubectl annotate ns demo chaos-mesh.org/inject=enabled --overwrite

chaos-status:
> KUBECONFIG=$(VM_KUBECONFIG) kubectl get pods -n chaos-mesh
> KUBECONFIG=$(VM_KUBECONFIG) kubectl get crd | grep chaos-mesh.org | head -5

deploy-status:
> KUBECONFIG=$(VM_KUBECONFIG) kubectl get nodes
> KUBECONFIG=$(VM_KUBECONFIG) kubectl get pods -A

.PHONY: vm-setup deploy deploy-status chaos-enable chaos-status
