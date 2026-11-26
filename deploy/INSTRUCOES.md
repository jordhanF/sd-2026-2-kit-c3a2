# Deploy em nuvem (free tier)

## Opcao A - Render
1. Crie conta em render.com e conecte o seu GitHub.
2. New > Web Service > selecione o repositorio.
3. Runtime: Docker. Aponte para o Dockerfile do gateway.
4. Defina as variaveis de ambiente (JWT_SEGREDO, URL_INFERENCIA).
5. Deploy. Anote a URL publica no README.

## Opcao B - Railway
1. Crie conta em railway.app e conecte o GitHub.
2. New Project > Deploy from GitHub repo.
3. Configure as variaveis de ambiente.
4. Generate Domain para obter a URL publica.

## Dica
Publique CEDO, ainda que incompleto. Deploy sempre da mais trabalho do que se imagina.
