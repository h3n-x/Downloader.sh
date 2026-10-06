# Troubleshooting

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `/api/v1/ready` → `ffmpeg: false` | FFmpeg no está en el `PATH` | Instalar FFmpeg (la imagen Docker lo incluye) |
| `deno: false` | venv no está en el `PATH` del proceso | Ejecutar con `uv run` o el `PATH` de la imagen |
| `storage: false` | No cabe un trabajo de tamaño máximo en `DL_DATA_DIR` | Ampliar tmpfs/disco o bajar `DL_MAX_FILESIZE` |
| Muchos `PLATFORM_BLOCKED` en YouTube | La plataforma pide "confirmar que no eres un bot" a IPs de datacenter | No se elude por diseño; valorar otra salida de red legítima o desactivar el proveedor |
| Picos de `EXTRACTOR_FAILED` en un proveedor | La plataforma cambió | Actualizar yt-dlp (Dependabot, grupo `extraction`) y ejecutar el workflow `live` |
| `URL_NOT_ALLOWED` con un enlace legítimo | El destino (o un redirect/CDN) resolvió a IP no pública | Revisar `dl_egress_denied` y el DNS del host |
| Todos los usuarios reciben `RATE_LIMITED` a la vez | `DL_FORWARDED_ALLOW_IPS` no incluye el proxy inverso | Configurar la IP del proxy |
| El progreso no avanza pero la descarga termina | Un proxy está bufferizando SSE | `flush_interval -1` (Caddy) / `proxy_buffering off` (nginx); el cliente cae a polling |
| Página sin estilos en componentes | Build con CSS dividido (bug Astro 7.3.6 + Rolldown) | Mantener `build.cssCodeSplit: false` |
| Hidratación bloqueada por CSP | `csp-hashes.json` no corresponde al build servido | Desplegar `dist/` completo; el backend lee los hashes al arrancar |
| `INTERNAL_ERROR` sin pista | Fallo inesperado del worker | `DL_LOG_WORKER_STDERR=true` temporalmente y buscar por `request_id` |
| Worker `killed (memory limit?)` | OOM del cgroup | Subir `mem_limit` o reducir `DL_MAX_CONCURRENT_DOWNLOADS` |
