# TitanVault Homepage — React 前端门户
# 替代 gethomepage/homepage, 整合服务展示 + 资源监控 + AI 助手 + API 指南入口。
# 多阶段 build: node 编译 → caddy:alpine 托管静态文件 (轻量 ~50MB)。
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install --production=false
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv/titanvault
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 3000
