# Деплой стека на ВМ с k3s. Запускать НА САМОЙ ВМ из корня репозитория.
# (.RECIPEPREFIX = > задан в корневом Makefile)
#
#   make vm-setup               ansible: common + k3s + terraform на ВМ (спросит пароли vault и sudo)
#   make deploy                 terraform: стек наблюдаемости на ВМ-кластер (без demo-shop, пока нет образов в ghcr)
#   make deploy DEPLOY_APPS=yes то же + demo-shop (gateway, orders, postgres)
#   make deploy-status          что запущено в кластере

VM_KUBECONFIG ?= $(abspath kubeconfig-sre.yaml)
VM_CONTEXT    ?= sre-vm
DEPLOY_APPS   ?= no
VAULT_ARGS    ?= -e @group_vars/vault.yml --ask-vault-pass --ask-become-pass

# demo-shop нужны образы gateway/orders. На ВМ их нет, пока не настроена публикация в ghcr,
# поэтому по умолчанию применяем всё, кроме helm_release.demo_shop (и лишнего podinfo).
STACK_TARGETS = -target=helm_release.kps -target=helm_release.loki -target=helm_release.tempo \
                -target=helm_release.alloy -target=helm_release.dashboards
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
>   -var kube_config_path=$(VM_KUBECONFIG) -var kube_context=$(VM_CONTEXT) $(DEPLOY_TARGETS)

deploy-status:
> KUBECONFIG=$(VM_KUBECONFIG) kubectl get nodes
> KUBECONFIG=$(VM_KUBECONFIG) kubectl get pods -A

.PHONY: vm-setup deploy deploy-status
