# Chaos Mesh: инъекции сбоев (pod-kill, network delay, CPU stress). Сценарии лежат в chaos/.
# Настройки под containerd из k3s: values/chaos-mesh.yaml.

resource "helm_release" "chaos_mesh" {
  name             = "chaos-mesh"
  namespace        = "chaos-mesh"
  create_namespace = true
  repository       = "https://charts.chaos-mesh.org"
  chart            = "chaos-mesh"
  version          = "2.8.4"
  timeout          = 600
  values           = [file("${path.module}/values/chaos-mesh.yaml")]

  depends_on = [helm_release.kps]
}
