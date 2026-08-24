# ============================
# CONFIGURACAO
# ============================

# Caminho para o repositorio Git da Central Logistica
$Repositorio = "C:\Users\RAFAEL\Desktop\App_DoRafa\CentralLogistica"

# ============================
# FUNCOES AUXILIARES
# ============================

function Testar-GitInstalado {
    try {
        $gitVersion = git --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Git esta instalado: $gitVersion" -ForegroundColor Green
            return $true
        }
    } catch {
        # Ignorar erro
    }
    return $false
}

function Testar-RailwayInstalado {
    try {
        $railwayVersion = railway --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Railway CLI esta instalado: $railwayVersion" -ForegroundColor Green
            return $true
        }
    } catch {
        # Ignorar erro
    }
    return $false
}

function Testar-AutenticadoRailway {
    try {
        $status = railway status 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Usuario autenticado no Railway" -ForegroundColor Green
            return $true
        }
    } catch {
        # Ignorar erro
    }
    return $false
}

function Adicionar-PostgreSQL {
    Write-Host "O Railway detectara e criara o PostgreSQL automaticamente durante o deploy." -ForegroundColor Cyan
    Write-Host ""
    return $true
}

function Configurar-VariaveisAmbiente {
    Write-Host "Configurando variaveis de ambiente..." -ForegroundColor Cyan
    Write-Host ""

    # Caminho do arquivo de configuracao
    $envFile = Join-Path $Repositorio "railway_env.json"
    $envExample = Join-Path $Repositorio "railway_env.example.json"

    if (-not (Test-Path $envFile)) {
        Write-Host "AVISO: Arquivo railway_env.json nao encontrado." -ForegroundColor Yellow
        Write-Host "O deploy continuara, mas variaveis nao serao configuradas." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Para criar o arquivo:" -ForegroundColor Cyan
        Write-Host "  1. Copie railway_env.example.json para railway_env.json" -ForegroundColor Yellow
        Write-Host "  2. Preencha os valores reais (DATABASE_URL e auto-provisionada pelo Railway)" -ForegroundColor Yellow
        Write-Host "  3. NUNCA commite railway_env.json (ja esta no .gitignore)" -ForegroundColor Yellow
        Write-Host ""
        if (Test-Path $envExample) {
            Write-Host "Template encontrado: $envExample" -ForegroundColor Green
        }
        return $true
    }

    # Ler o arquivo JSON
    try {
        $envConfig = Get-Content $envFile | ConvertFrom-Json
    } catch {
        Write-Host "ERRO: Falha ao ler arquivo railway_env.json." -ForegroundColor Red
        return $false
    }

    # Variaveis consumidas por app/core/config.py e app/services/mapmatching.py
    # Mantenha esta lista sincronizada com config.py
    $variaveis = @(
        "DATABASE_URL",
        "SECRET_KEY",
        "CENTRAL_LOGISTICA_API_KEY",
        "CARDAPIO_WEBHOOK_URL",
        "CARDAPIO_WEBHOOK_SECRET",
        "PUBLIC_BASE_URL",
        "PIX_PROVIDER",
        "PIX_TOKEN",
        "PIX_WEBHOOK_SECRET",
        "PIX_SANDBOX",
        "REMO_PIX_ONLINE_ENABLED",
        "VAPID_PUBLIC_KEY",
        "VAPID_PRIVATE_KEY",
        "VAPID_SUBJECT",
        "OSRM_URL"
    )

    foreach ($var in $variaveis) {
        $valor = $envConfig.$var
        if (-not [string]::IsNullOrWhiteSpace($valor)) {
            Write-Host "Configurando $var..." -ForegroundColor Yellow
            railway variables set "$var=$valor"
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Aviso: Falha ao configurar $var" -ForegroundColor Yellow
            } else {
                Write-Host "$var configurado com sucesso" -ForegroundColor Green
            }
        } else {
            Write-Host "Pulando $var (valor vazio)" -ForegroundColor Gray
        }
    }

    Write-Host ""
    Write-Host "Variaveis de ambiente configuradas." -ForegroundColor Green
    Write-Host ""
    Write-Host "ALINHAMENTO Cardapio <-> CentralLogistica:" -ForegroundColor Cyan
    Write-Host "  - CENTRAL_LOGISTICA_API_KEY deve ser IGUAL nos dois lados" -ForegroundColor Yellow
    Write-Host "  - CARDAPIO_WEBHOOK_SECRET (aqui) = CENTRAL_LOGISTICA_API_KEY ou" -ForegroundColor Yellow
    Write-Host "    LOGISTICA_WEBHOOK_SECRET (no Cardapio)" -ForegroundColor Yellow
    return $true
}

function Executar-Migracoes {
    Write-Host "O aplicativo executara as migracoes automaticamente ao iniciar." -ForegroundColor Cyan
    Write-Host ""
    return $true
}

function Instalar-RailwayCLI {
    Write-Host "Instalando Railway CLI..." -ForegroundColor Yellow
    try {
        npm install -g @railway/cli
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Railway CLI instalado com sucesso" -ForegroundColor Green

            # Obter o caminho do npm global
            $npmPath = npm config get prefix
            $npmBinPath = Join-Path $npmPath ""

            # Adicionar ao PATH da sessao atual
            $env:Path = $npmBinPath + ";" + $env:Path

            return $true
        } else {
            Write-Host "Falha ao instalar Railway CLI" -ForegroundColor Red
            return $false
        }
    } catch {
        Write-Host "Erro ao instalar Railway CLI: $_" -ForegroundColor Red
        return $false
    }
}

function Testar-RepositorioGit {
    $gitDir = Join-Path $Repositorio ".git"
    if (Test-Path $gitDir) {
        Write-Host "Pasta e um repositorio Git" -ForegroundColor Green
        return $true
    } else {
        Write-Host "Pasta nao e um repositorio Git" -ForegroundColor Red
        return $false
    }
}

# ============================
# EXECUCAO PRINCIPAL
# ============================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Deploy - Central Logistica (REMO)" -ForegroundColor Cyan
Write-Host "  GitHub / Railway" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verificar se a pasta configurada existe
if (-not (Test-Path $Repositorio)) {
    Write-Host "ERRO: A pasta configurada nao existe:" -ForegroundColor Red
    Write-Host "  $Repositorio" -ForegroundColor Red
    Write-Host ""
    Write-Host "Por favor, altere a variavel `$Repositorio` no inicio do script." -ForegroundColor Yellow
    exit 1
}

Write-Host "Pasta encontrada: $Repositorio" -ForegroundColor Green
Write-Host ""

# Acessar o diretorio do repositorio
Set-Location $Repositorio
Write-Host "Diretorio alterado para: $(Get-Location)" -ForegroundColor Green
Write-Host ""

# 2. Verificar se e um repositorio Git
if (-not (Testar-RepositorioGit)) {
    Write-Host "ERRO: A pasta nao e um repositorio Git valido." -ForegroundColor Red
    exit 1
}
Write-Host ""

# 3. Verificar se o Git esta instalado
if (-not (Testar-GitInstalado)) {
    Write-Host "ERRO: Git nao esta instalado." -ForegroundColor Red
    Write-Host "Por favor, instale o Git em: https://git-scm.com/downloads" -ForegroundColor Yellow
    exit 1
}
Write-Host ""

# 4. Verificar se o Railway CLI esta instalado
if (-not (Testar-RailwayInstalado)) {
    Write-Host "Railway CLI nao esta instalado. Iniciando instalacao..." -ForegroundColor Yellow
    Write-Host ""

    try {
        $npmVersion = npm --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERRO: npm nao esta instalado. E necessario para instalar o Railway CLI." -ForegroundColor Red
            Write-Host "Por favor, instale o Node.js em: https://nodejs.org/" -ForegroundColor Yellow
            exit 1
        }
        Write-Host "npm esta instalado: $npmVersion" -ForegroundColor Green
    } catch {
        Write-Host "ERRO: npm nao esta instalado. E necessario para instalar o Railway CLI." -ForegroundColor Red
        Write-Host "Por favor, instale o Node.js em: https://nodejs.org/" -ForegroundColor Yellow
        exit 1
    }

    if (-not (Instalar-RailwayCLI)) {
        exit 1
    }
    Write-Host ""
}

# 5. Verificar se o usuario esta autenticado no Railway
if (-not (Testar-AutenticadoRailway)) {
    Write-Host "Usuario nao autenticado no Railway. Executando login..." -ForegroundColor Yellow
    Write-Host ""
    railway login
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: Falha ao autenticar no Railway." -ForegroundColor Red
        exit 1
    }
    Write-Host ""
}

# 6. Executar git status e exibir arquivos alterados
Write-Host "Verificando status do Git..." -ForegroundColor Cyan
Write-Host ""
$statusOutput = git status
$statusOutput
Write-Host ""

# Verificar se ha alteracoes para commitar
$hasChanges = $false
if ($statusOutput -match "modified:|new file:|deleted:") {
    $hasChanges = $true
}

if (-not $hasChanges) {
    Write-Host "Nao ha alteracoes para commitar." -ForegroundColor Yellow
    Write-Host "Deseja continuar apenas com o deploy no Railway? (S/N)" -ForegroundColor Cyan
    $resposta = Read-Host

    if ($resposta -ne "S" -and $resposta -ne "s") {
        Write-Host "Operacao cancelada pelo usuario." -ForegroundColor Yellow
        exit 0
    }
    Write-Host ""
} else {
    # 7. Executar git add .
    Write-Host "Adicionando arquivos ao staging..." -ForegroundColor Cyan
    git add .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: Falha ao executar git add." -ForegroundColor Red
        exit 1
    }
    Write-Host "Arquivos adicionados ao staging" -ForegroundColor Green
    Write-Host ""

    # 8. Solicitar mensagem do commit
    Write-Host "Digite a mensagem do commit (pressione ENTER para gerar automaticamente):" -ForegroundColor Cyan
    $mensagemCommit = Read-Host

    if ([string]::IsNullOrWhiteSpace($mensagemCommit)) {
        $dataHora = Get-Date -Format "yyyy-MM-dd HH:mm"
        $mensagemCommit = "Atualizacao Central Logistica $dataHora"
        Write-Host "Mensagem gerada automaticamente: $mensagemCommit" -ForegroundColor Green
    }
    Write-Host ""

    # 9. Executar git commit
    Write-Host "Executando commit..." -ForegroundColor Cyan
    git commit -m $mensagemCommit
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: Falha ao executar git commit." -ForegroundColor Red
        exit 1
    }
    Write-Host "Commit realizado com sucesso" -ForegroundColor Green
    Write-Host ""

    # 10. Executar git push
    Write-Host "Enviando alteracoes para o GitHub..." -ForegroundColor Cyan
    git push
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: Falha ao executar git push." -ForegroundColor Red
        exit 1
    }
    Write-Host "Push realizado com sucesso" -ForegroundColor Green
    Write-Host ""
}

# 11. Verificar se ha projeto vinculado
Write-Host "Verificando se ha projeto vinculado ao Railway..." -ForegroundColor Cyan
Write-Host ""
$projectLinked = $false
try {
    $projectInfo = railway project 2>&1
    if ($LASTEXITCODE -eq 0) {
        $projectLinked = $true
        Write-Host "Projeto vinculado encontrado:" -ForegroundColor Green
        Write-Host $projectInfo
    }
} catch {
    # Ignorar erro
}

if (-not $projectLinked) {
    Write-Host "Nenhum projeto vinculado encontrado." -ForegroundColor Yellow
    Write-Host "O Railway tentara criar um novo projeto automaticamente." -ForegroundColor Yellow
    Write-Host ""
}

# 12. Adicionar servico PostgreSQL
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Configuracao do Banco de Dados" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Adicionar-PostgreSQL)) {
    Write-Host "ERRO: Falha ao configurar PostgreSQL." -ForegroundColor Red
    exit 1
}
Write-Host ""

# 13. Configurar variaveis de ambiente
if (-not (Configurar-VariaveisAmbiente)) {
    Write-Host "ERRO: Falha ao configurar variaveis de ambiente." -ForegroundColor Red
    exit 1
}
Write-Host ""

# 14. Executar migracoes e dados iniciais
if (-not (Executar-Migracoes)) {
    Write-Host "ERRO: Falha ao executar migracoes." -ForegroundColor Red
    exit 1
}
Write-Host ""

# 15. Executar deploy
Write-Host "Iniciando deploy da Central Logistica no Railway..." -ForegroundColor Cyan
Write-Host ""
railway up
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: Falha ao executar railway up." -ForegroundColor Red
    exit 1
}
Write-Host ""

# 16. Exibir resultado final
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Deploy concluido com sucesso!" -ForegroundColor Green
Write-Host "  Central Logistica (REMO)" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
