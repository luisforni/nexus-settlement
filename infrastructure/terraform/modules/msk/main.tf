locals {
  name = "${var.project}-${var.environment}"
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── Security Group ────────────────────────────────────────────────────────────
resource "aws_security_group" "msk" {
  name        = "${local.name}-msk-sg"
  description = "Allow Kafka access from within the VPC only"
  vpc_id      = var.vpc_id

  ingress {
    description = "Kafka PLAINTEXT from VPC"
    from_port   = 9092
    to_port     = 9092
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  ingress {
    description = "Kafka TLS from VPC"
    from_port   = 9094
    to_port     = 9094
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  ingress {
    description = "Zookeeper (inter-broker) from VPC"
    from_port   = 2181
    to_port     = 2181
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name}-msk-sg" })
}

# ── MSK Cluster Configuration ─────────────────────────────────────────────────
resource "aws_msk_configuration" "this" {
  name           = "${local.name}-kafka-config"
  kafka_versions = [var.kafka_version]

  server_properties = <<-PROPS
    auto.create.topics.enable=false
    default.replication.factor=1
    min.insync.replicas=1
    num.partitions=3
    log.retention.hours=168
    log.segment.bytes=1073741824
    log.retention.check.interval.ms=300000
  PROPS

  lifecycle {
    create_before_destroy = true
  }
}

# ── MSK Cluster ───────────────────────────────────────────────────────────────
resource "aws_msk_cluster" "this" {
  cluster_name           = "${local.name}-kafka"
  kafka_version          = var.kafka_version
  number_of_broker_nodes = var.num_brokers

  broker_node_group_info {
    instance_type = var.broker_instance_type
    # num_brokers must match the number of subnets provided
    client_subnets  = slice(var.subnet_ids, 0, var.num_brokers)
    security_groups = [aws_security_group.msk.id]

    storage_info {
      ebs_storage_info {
        volume_size = 100
      }
    }
  }

  # Unauthenticated access is acceptable for local simulation.
  # In production, enable SASL/SCRAM or mTLS.
  client_authentication {
    unauthenticated = true
  }

  encryption_info {
    encryption_in_transit {
      client_broker = "TLS_PLAINTEXT"
      in_cluster    = true
    }
  }

  configuration_info {
    arn      = aws_msk_configuration.this.arn
    revision = aws_msk_configuration.this.latest_revision
  }

  tags = merge(local.common_tags, { Name = "${local.name}-kafka" })
}

# ── Kafka Topics ──────────────────────────────────────────────────────────────
# Topics are created by running `kafka-topics.sh` against the local docker-compose
# Kafka broker. In a real AWS deployment, replace this null_resource with the
# `Mongey/kafka` Terraform provider pointing at the MSK bootstrap brokers.
resource "null_resource" "kafka_topics" {
  for_each = { for t in var.topics : t.name => t }

  triggers = {
    topic_name         = each.value.name
    partitions         = each.value.partitions
    replication_factor = each.value.replication_factor
    cluster_id         = aws_msk_cluster.this.id
  }

  provisioner "local-exec" {
    command = <<-EOF
      docker compose exec kafka \
        kafka-topics --bootstrap-server localhost:9092 \
        --create \
        --if-not-exists \
        --topic "${each.value.name}" \
        --partitions ${each.value.partitions} \
        --replication-factor ${each.value.replication_factor}
    EOF
    working_dir = var.compose_working_dir
  }
}
