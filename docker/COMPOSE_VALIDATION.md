# Compose 校验结果（docker compose config 输出）

验证日期: 2026-08-16
Docker: Docker version 29.3.1, build c2be9cc
Compose: Docker Compose version v5.1.1

## 1. compose.yaml（生产）
```yaml
name: trutheguipment
services:
  homeassistant:
    cap_add:
      - NET_RAW
      - SYS_TIME
    cap_drop:
      - ALL
    container_name: homeassistant
    environment:
      TZ: Asia/Shanghai
    healthcheck:
      test:
        - CMD-SHELL
        - python3 -c 'import urllib.request; urllib.request.urlopen("http://localhost:8123/", timeout=3)'
      timeout: 5s
      interval: 30s
      retries: 3
      start_period: 1m30s
    image: ghcr.io/home-assistant/home-assistant:2026.8.2
    network_mode: host
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    volumes:
      - type: bind
        source: C:\Users\33940\Desktop\truth eguipment\docker\volumes\ha_config
        target: /config
        bind: {}
      - type: bind
        source: /etc/localtime
        target: /etc/localtime
        read_only: true
        bind: {}
  ollama:
    container_name: ollama
    environment:
      OLLAMA_KEEP_ALIVE: "-1"
    healthcheck:
      test:
        - CMD
        - ollama
        - list
      timeout: 10s
      interval: 30s
      retries: 3
      start_period: 30s
    image: ollama/ollama:0.32.13
    networks:
      default: null
    ports:
      - mode: ingress
        host_ip: 127.0.0.1
        target: 11434
        published: "11434"
        protocol: tcp
    restart: unless-stopped
    volumes:
      - type: bind
        source: C:\Users\33940\Desktop\truth eguipment\docker\volumes\ollama_data
        target: /root/.ollama
        bind: {}
networks:
  default:
    name: agent-platform-internal
```

## 2. compose.yaml + compose.dev.yaml（开发）
退出码: 0
```yaml
name: trutheguipment
services:
  homeassistant:
    cap_add:
      - NET_RAW
      - SYS_TIME
    cap_drop:
      - ALL
    container_name: homeassistant
    environment:
      TZ: Asia/Shanghai
    healthcheck:
      test:
        - CMD-SHELL
        - python3 -c 'import urllib.request; urllib.request.urlopen("http://localhost:8123/", timeout=3)'
      timeout: 5s
      interval: 30s
      retries: 3
      start_period: 1m30s
    image: ghcr.io/home-assistant/home-assistant:2026.8.2
    ports:
      - mode: ingress
        target: 8123
        published: "8123"
        protocol: tcp
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    volumes:
      - type: bind
        source: C:\Users\33940\Desktop\truth eguipment\docker\volumes\ha_config
        target: /config
        bind: {}
      - type: bind
        source: /etc/localtime
        target: /etc/localtime
        read_only: true
        bind: {}
  ollama:
    container_name: ollama
    environment:
      OLLAMA_KEEP_ALIVE: "-1"
    healthcheck:
      test:
        - CMD
        - ollama
        - list
      timeout: 10s
      interval: 30s
      retries: 3
      start_period: 30s
    image: ollama/ollama:0.32.13
    networks:
      default: null
    ports:
      - mode: ingress
        host_ip: 127.0.0.1
        target: 11434
        published: "11434"
        protocol: tcp
    restart: unless-stopped
    volumes:
      - type: bind
        source: C:\Users\33940\Desktop\truth eguipment\docker\volumes\ollama_data
        target: /root/.ollama
        bind: {}
networks:
  default:
    name: agent-platform-internal
```
