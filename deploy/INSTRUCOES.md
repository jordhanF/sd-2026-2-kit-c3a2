# Deploy em nuvem (free tier)

A plataforma está publicada em **https://168-75-70-16.sslip.io** — numa instância
**Oracle Cloud Always Free** (Ampere A1, ARM64, Ubuntu 24.04), com nginx terminando o
HTTPS e o certificado emitido pelo Let's Encrypt.

Este documento descreve exatamente o que foi feito, para ser reproduzível.

---

## Por que esta opção, e não Render/Railway

O kit sugere Render ou Railway. Ambos são free tier de verdade, mas têm duas limitações
que brigam com o enunciado deste trabalho:

| | Render / Railway free | Oracle Always Free |
|---|---|---|
| O que roda | **um container por serviço** — o `docker-compose` não sobe lá | a stack inteira, com o mesmo `docker compose up -d` do laptop |
| Inatividade | o serviço **hiberna**; a primeira requisição leva dezenas de segundos | sempre no ar |
| Custo | US$ 0 | US$ 0 |

Como o item 3 do edital pede que **o sistema inteiro suba com um comando**, publicar só o
gateway e deixar fila, worker e armazenamento vetorial de fora esvaziaria justamente o que
se está avaliando. Numa VM o artefato publicado é o mesmo que roda localmente.

### E o domínio?

`168-75-70-16.sslip.io` não é um truque: o [sslip.io](https://sslip.io) é um resolvedor
público que devolve o IP embutido no próprio nome. Serve para obter um **nome** — e, com
ele, um certificado TLS válido — sem depender de registrar domínio. Trocar por um domínio
próprio depois é mudar o `server_name` e reemitir o certificado.

---

## Passo a passo

### 1. Docker na máquina

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"      # saia e entre de novo para valer
```

### 2. Código e configuração

```bash
git clone https://github.com/jordhanF/sd-2026-2-kit-c3a2.git ~/plataforma-ia
cd ~/plataforma-ia
cp .env.example .env

# segredo de verdade e senha com hash — nada de valor de exemplo em produção
sed -i "s|^JWT_SEGREDO=.*|JWT_SEGREDO=$(openssl rand -hex 32)|" .env
sed -i "s|^AMBIENTE=.*|AMBIENTE=producao|" .env
python3 -c "import sys; sys.path.insert(0,'.'); from gateway.autenticacao import gerar_hash; print(gerar_hash('SUA-SENHA'))"
# cole o resultado em API_SENHA_HASH e esvazie API_SENHA
chmod 600 .env
```

### 3. Subir a plataforma

```bash
docker compose up -d --build
docker compose ps        # os sete de pé
curl -s localhost:8000/saude | head
```

### 4. Borda HTTPS

```bash
sudo cp deploy/nginx.conf.exemplo /etc/nginx/sites-available/plataforma-ia
sudo ln -s /etc/nginx/sites-available/plataforma-ia /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx        # reload, nunca restart

sudo certbot --nginx -d 168-75-70-16.sslip.io --non-interactive --agree-tos \
  -m seu-email@exemplo.com --redirect
```

O `certbot` reescreve o vhost acrescentando o bloco `443 ssl` e o redirecionamento de 80
para 443, e instala a renovação automática (`certbot.timer`).

---

## Decisões de operação que valem registrar

**Nada além do gateway é publicado, e só em `127.0.0.1`.** O Docker escreve direto no
`iptables` e **passa por cima do UFW**: publicar `8001:8001` num servidor com firewall
fechado abriria o serviço de ingestão para a internet inteira sem nenhum aviso. No
`docker-compose.yml` a interface vem de `BIND_LOCAL`, com `127.0.0.1` como padrão.

**`reload`, nunca `restart`, no nginx.** Esta máquina serve outros sites; `reload` é
recusado quando a configuração está inválida, enquanto `restart` derruba todos eles.
Sempre `nginx -t` antes.

**A interface de rastreamento não fica exposta.** O Jaeger publica a porta 16686 também em
`127.0.0.1`. Para abrir no navegador, um túnel SSH:

```bash
ssh -L 16686:127.0.0.1:16686 ubuntu@168.75.70.16
# depois: http://localhost:16686
```

**Atualizar o que está publicado:**

```bash
cd ~/plataforma-ia && git pull && docker compose up -d --build
```

---

## Reprodutibilidade em qualquer lugar

Nada acima é específico da Oracle: a plataforma é um `docker compose` com configuração em
variáveis de ambiente. Em qualquer VM com Docker — AWS, GCP, uma máquina na mesa — os
passos 2 e 3 bastam; o passo 4 só muda o `server_name`.
