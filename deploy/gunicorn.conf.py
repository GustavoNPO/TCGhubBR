# gunicorn -c deploy/gunicorn.conf.py app:app
# Só escuta localmente: quem fala com a internet é o nginx.
bind = "127.0.0.1:8000"
# Poucos processos com threads: caches e limites em memória ficam mais consistentes.
workers = 2
threads = 4
# O scan espera o Gemini e os catálogos; acima disso o worker é reiniciado.
timeout = 60
graceful_timeout = 20
# Recicla workers aos poucos para conter vazamento de memória.
max_requests = 1000
max_requests_jitter = 100
# Confia nos cabeçalhos X-Forwarded-* só quando vêm do nginx local.
forwarded_allow_ips = "127.0.0.1"
# Logs no journald (journalctl -u tcghub).
accesslog = "-"
errorlog = "-"
loglevel = "info"