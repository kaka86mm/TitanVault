[Unit]
Description=llama.cpp QUEST-9B (deep research agent model, :8093)
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
Environment=LD_LIBRARY_PATH=/opt/llama.cpp
WorkingDirectory=/opt/llama.cpp
ExecStart=/opt/llama.cpp/llama-server \
    -m ${DATA_DIR}/models/llm/QUEST-9B-Q4-nomtp.gguf \
    --host 0.0.0.0 \
    --port 8093 \
    -ngl 99 \
    -c 131072 \
    -np 2 \
    -t 8 \
    --flash-attn on \
    --cache-type-k q4_0 \
    --cache-type-v q4_0 \
    --mmap
Restart=always
RestartSec=10
StartLimitInterval=60
StartLimitBurst=3

[Install]
WantedBy=multi-user.target
