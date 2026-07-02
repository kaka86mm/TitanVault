# config/homepage/docker.yaml.tpl
# homepage 的 docker 连接配置。
# 让 homepage 经 docker.sock 发现本机容器, 在服务卡片上显示运行状态/CPU/内存。
#
# install.sh Phase5 用 envsubst 渲染 (无变量, 直接拷贝即可)。
my-docker:
  socket: /var/run/docker.sock
