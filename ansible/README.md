# ansible

Роли: `common` (ssh-ключи, ufw, fail2ban) и `k3s` (server/agent). `rsyslog` и `auditd` пока пустые.

## Запуск

```bash
cd ansible
ansible-galaxy collection install -r requirements.yml
cp inventory/hosts.ini.example inventory/hosts.ini     # вписать свои ВМ
# публичные ключи и токен кластера положить в vault:
ansible-vault create group_vars/vault.yml
#   common_ssh_public_keys: ["ssh-ed25519 AAAA..."]
#   k3s_token: "<случайная строка >=16 символов>"
ansible-playbook site.yml --ask-vault-pass
```

Только common: `--tags common`. Только k3s: `--tags k3s`.

После запуска kubeconfig лежит в корне репозитория (`kubeconfig-sre.yaml`, в .gitignore):
`KUBECONFIG=kubeconfig-sre.yaml kubectl get nodes`.

## Важно

- Пока `common_ssh_public_keys` пуст, вход по паролю НЕ отключается (чтобы не потерять доступ).
- ufw сначала разрешает SSH и только потом включается.
- Версия k3s (`v1.28.15+k3s1`) совпадает с `K3S_IMAGE` в Makefile.
- Terraform (`terraform/`) дальше применяется к ВМ-кластеру: `kube_config_path=../kubeconfig-sre.yaml`, `kube_context=sre-vm`.
