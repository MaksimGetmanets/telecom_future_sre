# ansible

Роли: `common` (ssh-ключи, ufw, fail2ban), `k3s` (server/agent), `deploy_tools` (terraform, make, git на ВМ), `rsyslog` и `auditd` (логи и аудит хоста в Loki).

## Запуск

```bash
cd ansible
ansible-galaxy collection install -r requirements.yml
cp inventory/hosts.ini.example inventory/hosts.ini     # вписать свои ВМ
# публичные ключи и токен кластера положить в vault:
ansible-vault create group_vars/vault.yml
#   common_ssh_public_keys: ["ssh-ed25519 AAAA..."]
#   k3s_token: "<случайная строка >=16 символов>"
ansible-playbook site.yml -e @group_vars/vault.yml --ask-vault-pass --ask-become-pass
```

Только common: `--tags common`. Только k3s: `--tags k3s`.

После запуска kubeconfig лежит в корне репозитория (`kubeconfig-sre.yaml`, в .gitignore):
`KUBECONFIG=kubeconfig-sre.yaml kubectl get nodes`.

## Важно

- Пока `common_ssh_public_keys` пуст, вход по паролю НЕ отключается (чтобы не потерять доступ).
- ufw сначала разрешает SSH и только потом включается.
- Версия k3s (`v1.28.15+k3s1`) совпадает с `K3S_IMAGE` в Makefile.
- Terraform (`terraform/`) дальше применяется к ВМ-кластеру: `kube_config_path=../kubeconfig-sre.yaml`, `kube_context=sre-vm`.

## Деплой стека на ВМ одной командой

Запускается на самой ВМ, из корня репозитория (нужен `terraform`, его ставит роль `deploy_tools`):

```bash
make vm-setup      # ansible: common + k3s + terraform (спросит пароли vault и sudo)
make deploy        # terraform: kube-prometheus-stack, Loki, Tempo, Alloy, дашборды
make deploy-status # что запущено в кластере
```

`make deploy` по умолчанию не ставит demo-shop: образам `gateway:dev` и `orders:dev` на ВМ взяться неоткуда,
пока они не публикуются в ghcr. Когда образы появятся: `make deploy DEPLOY_APPS=yes`.

## Логи и аудит хоста в Loki (rsyslog + auditd)

Цепочка: хост (`rsyslog`, `auditd`) -> syslog по TCP -> Alloy в кластере -> Loki.
Адрес приёмника это фиксированный ClusterIP Alloy `10.43.100.100:1514`: он виден только с самой ноды, наружу порт не открыт.
Настройка приёмника: `terraform/values/alloy.yaml`. Пересылаются все логи хоста (`sshd`, `sudo`, `kern`...) и события аудита
(правила в `roles/auditd/templates/50-sre.rules.j2`, у событий ключи `sre_identity`, `sre_sudo`, `sre_sshd` и так далее).

Порядок включения (один раз, т.к. clusterIP у существующего сервиса менять нельзя):

```bash
make vm-setup                                          # роли rsyslog и auditd
make deploy DEPLOY_EXTRA="-replace=helm_release.alloy" # Alloy пересоздаётся с приёмником syslog
```

Проверка (Grafana -> Explore -> Loki):

```bash
logger -p authpriv.warning "test-sre-hostlog"          # на ВМ
sudo touch /etc/ssh/sshd_config                        # генерирует событие аудита
```
```logql
{job="host-syslog"} |= "test-sre-hostlog"
{job="host-syslog"} |= "sre_sshd"
{job="host-syslog", program="sshd"}
```
