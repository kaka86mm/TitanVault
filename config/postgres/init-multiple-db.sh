#!/usr/bin/env bash
# config/postgres/init-multiple-db.sh
# postgres 官方入口钩子: 仅在数据目录首次初始化时执行一次。
#
# POSTGRES_MULTIPLE_DATABASES=gitea,litellm 时, 为每个库 CREATE DATABASE
# 并授予 POSTGRES_USER 全部权限。这样上层服务 (Gitea/LiteLLM/...) 共享同一
# postgres 实例而互不干扰, 避免各自跑独立 db。
set -euo pipefail

databases="${POSTGRES_MULTIPLE_DATABASES:-}"
if [ -z "$databases" ]; then
  echo "[init] POSTGRES_MULTIPLE_DATABASES 未设置, 跳过多库初始化"
  exit 0
fi

user="${POSTGRES_USER:-postgres}"
echo "[init] 为用户 '$user' 创建数据库: $databases"

# 需要预装 pgvector 扩展的库 (hindsight 的相似度检索依赖它)
VECTOR_DBS="${POSTGRES_VECTOR_DBS:-hindsight}"

for db in $(echo "$databases" | tr ',' ' '); do
  db=$(echo "$db" | xargs)  # 去空白
  echo "[init] -> $db"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE "$db";
    GRANT ALL PRIVILEGES ON DATABASE "$db" TO "$user";
EOSQL
  # 该库需要 pgvector?
  if echo " $VECTOR_DBS " | grep -q " $db "; then
    echo "[init]   在 $db 启用 pgvector 扩展"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d "$db" <<-EOSQL
      CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
  fi
done

echo "[init] 多库初始化完成 (pgvector 已为 $VECTOR_DBS 启用)"
