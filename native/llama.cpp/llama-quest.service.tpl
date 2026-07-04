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
    -c 32768 \
    -t 8 \
    --no-mmap
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
