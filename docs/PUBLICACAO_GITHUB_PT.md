# Separação do repositório — instruções de publicação

## Objetivo

Entregar exclusivamente o motor científico de forecasting (F0/F1, modelos,
validação e histórico dos algoritmos) e uma CLI de utilização. A cópia do
projeto original continua intacta.

## Conteúdo que fica fora

Frontend Nuxt/Vue, FastAPI, endpoints, contas de utilizadores, SQL/migrations,
optimização Pyomo/SCIP/HiGHS, pricing, otimização de membros, cenários, EV/EVSE,
ficheiros `.env`, base de dados e credenciais. As referências M3/M4 geradas pela
optimização deixam de ser necessárias para executar os benchmarks standalone.

## Preparação (PowerShell)

1. Extraia o ZIP `commfair-forecasting-code-only.zip` para uma pasta separada.
2. Entre na pasta extraída: `cd commfair-forecasting-standalone`.
3. Crie um ambiente Python:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

4. Se os ficheiros do dataset podem ser utilizados localmente, copie do backend
   do projeto original (o comando seguinte é um exemplo, adapte a localização):

```powershell
python -m scripts.import_data --backend "C:\caminho\para\projeto-original\backend"
python -m pytest tests -q
python -m scripts.demo --origin-t 7008 --model champion
```

O ZIP é **code-only**: não contém dataset e os três ficheiros continuam
ignorados pelo Git quando forem copiados. O júri precisará do dataset autorizado
para reproduzir testes em dados originais.

## Novo repositório GitHub

Crie um repositório GitHub vazio, sem README automático, licença automática ou
.gitignore automático. A partir da pasta do export:

```powershell
git init
git branch -M main
git add .
git status --short
git commit -m "Initial release: standalone forecasting engine"
git remote add origin https://github.com/ORGANIZACAO/NOVO-REPO.git
git push -u origin main
```

Antes do `git push`, confirme com `git status` e `git ls-files` que não aparecem:

- `*.xlsx` e os CSVs de inputs (sem autorização de redistribuição);
- `*.db`, `.env`, tokens, passwords ou configurações de servidor;
- diretórios `frontend/`, rotas HTTP, Docker da plataforma, otimização.

## Notas de validação

Os 5 testes unitários/integração com dataset foram executados neste export e
passaram. O comando de demonstração produziu previsões com os modelos esperados:
Ridge global `ridge_global_7b21fa54198f` (load) e `naive_24` (PV). A reprodução
exaustiva F0/F1 não está comprovada por esses testes e deve ser executada em
ambiente limpo antes de se declarar bitwise reproduction.

Esta extração mantém código científico original na maior parte dos módulos;
substitui as fronteiras de integração (F2/F3/optimizador), retira gates M3/M4
e introduz CLI autónoma. Não equivale a publicar um snapshot idêntico dos
artefactos históricos da plataforma.
