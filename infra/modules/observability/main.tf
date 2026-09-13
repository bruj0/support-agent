data "aws_region" "current" {}

provider "helm" {
  kubernetes = {
    config_path = "~/.kube/config"
  }
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

# --- T002 AdotCollectorHelm (DaemonSet, hostNetwork, Pod Identity) ----------------

resource "helm_release" "adot_collector" {
  count = var.test_mode ? 0 : 1

  name             = "adot-collector"
  namespace        = "opentelemetry"
  repository       = "https://aws-otel-collector.github.io/releases"
  chart            = "aws-otel-collector"
  version          = "0.13.0"
  create_namespace = true

  set = [
    { name = "mode", value = "daemonset" },
    { name = "hostNetwork", value = "true" },
    { name = "serviceAccount.annotations.eks\\.amazonaws\\.com/pod-identity-association-arn", value = var.adot_role_arn },
    { name = "config.exporters.awsxray.region", value = var.region },
    { name = "config.exporters.awsemf.region", value = var.region },
    { name = "config.exporters.awsemf.namespace", value = "support-bot" },
    { name = "config.exporters.logging.loglevel", value = "info" },
    { name = "config.service.pipelines.traces.exporters[0]", value = "{awsxray}" },
    { name = "config.service.pipelines.metrics.exporters[0]", value = "{awsemf}" },
  ]

  values = [
    <<-YAML
      config:
        receivers:
          otlp:
            protocols:
              grpc:
                endpoint: 0.0.0.0:4317
              http:
                endpoint: 0.0.0.0:4318
        processors:
          memory_limiter:
            check_interval: 5s
            limit_mib: 512
            spike_limit_mib: 128
          batch:
            timeout: 10s
            send_batch_size: 1024
        service:
          pipelines:
            traces:
              receivers: [otlp]
              processors: [memory_limiter, batch]
              exporters: [awsxray]
            metrics:
              receivers: [otlp]
              processors: [memory_limiter, batch]
              exporters: [awsemf]
    YAML
  ]
}

# --- T003 ApplicationLogGroup + OtelLogGroup (30d + 7d, KMS-encrypted) ------------

resource "aws_cloudwatch_log_group" "application" {
  name              = "/aws/eks/support-bot-${var.env}/application"
  retention_in_days = 30
  kms_key_id        = var.cmk_arn

  tags = {
    Cluster = "support-bot-${var.env}"
    Env     = var.env
  }
}

resource "aws_cloudwatch_log_group" "otel" {
  name              = "/aws/eks/support-bot-${var.env}/otel"
  retention_in_days = 7
  kms_key_id        = var.cmk_arn

  tags = {
    Cluster = "support-bot-${var.env}"
    Env     = var.env
  }
}

# --- T005 PodSecurityStandards (Namespace labels = restricted) --------------------

resource "kubernetes_manifest" "support_bot_namespace_labels" {
  manifest = {
    apiVersion = "v1"
    kind       = "Namespace"
    metadata = {
      name = "support-bot"
      labels = {
        "pod-security.kubernetes.io/enforce" = "restricted"
        "pod-security.kubernetes.io/warn"    = "restricted"
        "pod-security.kubernetes.io/audit"   = "restricted"
      }
    }
  }
}

# --- T006 NetworkPolicy: default-deny ---------------------------------------------

resource "kubernetes_manifest" "support_bot_default_deny" {
  manifest = {
    apiVersion = "networking.k8s.io/v1"
    kind       = "NetworkPolicy"
    metadata = {
      name      = "default-deny"
      namespace = "support-bot"
    }
    spec = {
      podSelector = {}
      policyTypes = ["Ingress", "Egress"]
    }
  }
}

# --- T007 NetworkPolicy: api-allow (5 egress ports) -------------------------------

resource "kubernetes_manifest" "support_bot_api_allow" {
  manifest = {
    apiVersion = "networking.k8s.io/v1"
    kind       = "NetworkPolicy"
    metadata = {
      name      = "api-allow"
      namespace = "support-bot"
    }
    spec = {
      podSelector = {
        matchLabels = {
          app = "support-bot-api"
        }
      }
      policyTypes = ["Ingress", "Egress"]
      ingress = [{
        from = [{ podSelector = {} }]
        ports = [{
          port     = 8000
          protocol = "TCP"
        }]
      }]
      egress = [
        # Chroma :8000
        {
          to = [{
            podSelector = {
              matchLabels = {
                app = "support-bot-chroma"
              }
            }
          }]
          ports = [{
            port     = 8000
            protocol = "TCP"
          }]
        },
        # OpenAI :443 (HTTPS, RFC1918 excluded)
        {
          to = [{
            ipBlock = {
              cidr   = "0.0.0.0/0"
              except = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
            }
          }]
          ports = [{
            port     = 443
            protocol = "TCP"
          }]
        },
        # ADOT :4318 (OTLP HTTP)
        {
          to = [{
            ipBlock = {
              cidr = "0.0.0.0/0"
            }
          }]
          ports = [{
            port     = 4318
            protocol = "TCP"
          }]
        },
        # kube-dns :53 (UDP + TCP) in kube-system namespace
        {
          to = [{
            namespaceSelector = {
              matchLabels = {
                "kubernetes.io/metadata.name" = "kube-system"
              }
            }
          }]
          ports = [
            { port = 53, protocol = "UDP" },
            { port = 53, protocol = "TCP" },
          ]
        },
        # EKS API endpoint :443
        {
          to = [{
            ipBlock = {
              cidr = "0.0.0.0/0"
            }
          }]
          ports = [{
            port     = 443
            protocol = "TCP"
          }]
        },
      ]
    }
  }
}

# --- T008 NetworkPolicy: chroma-allow (3 egress ports) ----------------------------

resource "kubernetes_manifest" "support_bot_chroma_allow" {
  manifest = {
    apiVersion = "networking.k8s.io/v1"
    kind       = "NetworkPolicy"
    metadata = {
      name      = "chroma-allow"
      namespace = "support-bot"
    }
    spec = {
      podSelector = {
        matchLabels = {
          app = "support-bot-chroma"
        }
      }
      policyTypes = ["Ingress", "Egress"]
      ingress = [{
        from = [{
          podSelector = {
            matchLabels = {
              app = "support-bot-api"
            }
          }
        }]
        ports = [{
          port     = 8000
          protocol = "TCP"
        }]
      }]
      egress = [
        # ADOT :4318
        {
          to = [{
            ipBlock = {
              cidr = "0.0.0.0/0"
            }
          }]
          ports = [{
            port     = 4318
            protocol = "TCP"
          }]
        },
        # kube-dns :53
        {
          to = [{
            namespaceSelector = {
              matchLabels = {
                "kubernetes.io/metadata.name" = "kube-system"
              }
            }
          }]
          ports = [
            { port = 53, protocol = "UDP" },
            { port = 53, protocol = "TCP" },
          ]
        },
        # EKS API :443
        {
          to = [{
            ipBlock = {
              cidr = "0.0.0.0/0"
            }
          }]
          ports = [{
            port     = 443
            protocol = "TCP"
          }]
        },
      ]
    }
  }
}
