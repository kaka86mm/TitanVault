# images/offline/ — 预打包离线镜像

国内 docker hub 被 DNS 污染 (registry-1.docker.io 解析到错误 IP),
镜像源 (1ms.run/daocloud 等) 对冷门镜像无缓存 → 回源卡死。
本目录预打包常用镜像, install.sh Phase3 自动 `docker load`, 之后 compose up
发现镜像已存在就不再 pull。

## 文件清单

| 文件 | 镜像 | 打包时间 |
|---|---|---|
| standard-offline-images.tar.gz (1.5G) | lpdswing/mineru-web-{backend,frontend}, metacubex/mihomo, filebrowser/filebrowser, searxng/searxng, nginx:stable-alpine, louislam/uptime-kuma, nicolargo/glances (运行时冷门镜像) | 见 git log |
| build-base-images.tar.gz (56M) | python:3.10-slim, python:3.12-slim (本地 build 的 FROM base) | 见 git log |

## 更新离线包

镜像有新版本时, 在能直连 docker hub 的机器上 (如配了代理的生产机) 重新打包:

```bash
# 在有网络的机器上
docker pull <新镜像>
docker save <镜像1> <镜像2> ... | gzip > standard-offline-images.tar.gz
```

## 不在此打包的 (体积过大或需本地 build)

- 本地 build 镜像: mineru-rocm, aham-voice-web, mozin/sensevoice, mozin/token-usage-api (源码在 images/*/)
- 热门镜像 (镜像源可靠): postgres/redis/qdrant/caddy/homepage/litellm/kokoro/frpc/minio
- full 档大镜像: dify 全家桶/hindsight/open_notebook/hermes 等 (>15GB, 建议有代理环境部署)

`scripts/load-offline-images.sh --check` 可检查缺失项。
