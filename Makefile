.RECIPEPREFIX = >
CLUSTER ?= sre
K3S_IMAGE ?= rancher/k3s:v1.28.15-k3s1

up: cluster
> cd terraform && terraform init -input=false && terraform apply -auto-approve -input=false

cluster:
> k3d cluster get $(CLUSTER) >/dev/null 2>&1 || k3d cluster create $(CLUSTER) --image $(K3S_IMAGE)

down:
> k3d cluster delete $(CLUSTER)
