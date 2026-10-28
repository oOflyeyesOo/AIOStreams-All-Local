<#
.SYNOPSIS
    AIOStreams Self-Hosted Stack Management Script & Web Bridge Server
.DESCRIPTION
    Provides automated directory creation, port conflict pre-flight checks,
    local HTTP server for 1-click web deployment, CLI setup wizard,
    and Docker stack lifecycle commands.
#>

[CmdletBinding()]
param (
    [switch]$Serve,
    [switch]$Wizard,
    [switch]$Check,
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$BuildAppliance,
    [string]$Profile = "",
    [int]$Port = 8088
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

# Colors for terminal output
function Write-Header {
    param([string]$Text)
    Write-Host "`n====================================================================" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor White
    Write-Host "====================================================================" -ForegroundColor Cyan
}

function Write-Success { param([string]$Msg) Write-Host "[+] $Msg" -ForegroundColor Green }
function Write-Info    { param([string]$Msg) Write-Host "[i] $Msg" -ForegroundColor Cyan }
function Write-Warn    { param([string]$Msg) Write-Host "[!] $Msg" -ForegroundColor Yellow }
function Write-Err     { param([string]$Msg) Write-Host "[-] $Msg" -ForegroundColor Red }

# Ensure required directory structures exist
function Ensure-Directories {
    Write-Info "Ensuring data and configuration directory structures..."
    $dirs = @(
        "data/aiostreams",
        "data/comet",
        "data/mediafusion",
        "data/prowlarr",
        "data/subsense",
        "data/sootio",
        "data/redis",
        "data/postgres",
        "data/slicksync",
        "data/aiometadata",
        "data/postersplus",
        "data/infinidysk",
        "data/stremio-web",
        "data/debrid-search",
        "init/postgres",
        "templates/setup-templates",
        "templates/formatters",
        "templates/filtering-and-expressions",
        "templates/regex-rankings",
        "templates/aiometadata-configs",
        "templates/builtin"
    )
    foreach ($d in $dirs) {
        $p = Join-Path $ScriptDir $d
        if (-not (Test-Path $p)) {
            New-Item -ItemType Directory -Path $p -Force | Out-Null
        }
    }
    Write-Success "All directories ready."
}

# Pre-flight check: Docker daemon and port availability
function Test-SystemPrerequisites {
    Write-Header "Pre-Flight Diagnostics & Port Collision Check"
    
    # 1. Docker check
    try {
        $dockerVer = docker --version 2>$null
        if ($dockerVer) {
            Write-Success "Docker CLI detected: $dockerVer"
        } else {
            Write-Err "Docker CLI not found in PATH. Please install Docker Desktop or Docker Engine."
            return $false
        }
    } catch {
        Write-Err "Docker command failed. Is Docker installed?"
        return $false
    }

    try {
        docker info 2>$null | Out-Null
        Write-Success "Docker daemon is running."
    } catch {
        Write-Warn "Docker daemon appears unreachable. Ensure Docker Desktop is started."
    }

    # 2. Port conflict test
    Write-Info "Checking target port availability..."
    $portsToCheck = @(
        @{ Port = 3001; Service = "AIOStreams" },
        @{ Port = 8000; Service = "Comet" },
        @{ Port = 8001; Service = "MediaFusion" },
        @{ Port = 8181; Service = "Zilean (DMM Cache)" },
        @{ Port = 9696; Service = "Prowlarr" },
        @{ Port = 8191; Service = "FlareSolverr" },
        @{ Port = 8080; Service = "StremThru Proxy" },
        @{ Port = 8888; Service = "MediaFlow Proxy" },
        @{ Port = 7005; Service = "Anime Kitsu" },
        @{ Port = 4005; Service = "AIOMetadata" },
        @{ Port = 3100; Service = "SubSense Subtitles" },
        @{ Port = 8085; Service = "Nuvio Web Player" },
        @{ Port = 8086; Service = "SlickSync (Nuvio & Stremio Hub)" },
        @{ Port = 3005; Service = "InfiniDysk (Usenet Stream Engine)" },
        @{ Port = 8082; Service = "Stremio Web Player & Engine" },
        @{ Port = 3011; Service = "Stremio Debrid Search (Personal Cloud)" },
        @{ Port = 55771; Service = "Sootio Multi-Scraper" }
    )

    $conflicts = @()
    foreach ($item in $portsToCheck) {
        $occupied = $false
        try {
            $tcp = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $item.Port)
            $tcp.Start()
            $tcp.Stop()
        } catch {
            $occupied = $true
        }

        if ($occupied) {
            Write-Warn "Port $($item.Port) ($($item.Service)) is currently IN USE by another process."
            $conflicts += $item
        } else {
            Write-Host "  + Port $($item.Port) available ($($item.Service))" -ForegroundColor DarkGray
        }
    }

    if ($conflicts.Count -eq 0) {
        Write-Success "All $($portsToCheck.Count) stack ports are available with no collisions!"
        return $true
    } else {
        Write-Warn "$($conflicts.Count) port conflict(s) detected. If these are existing stack containers, 'docker compose up' will recreate them."
        return $true
    }
}

# Start local bridge HTTP server to enable 1-click deployment from configurator.html
function Start-ConfigServer {
    param([int]$ListenPort = 8088)

    Ensure-Directories

    $prefix = "http://localhost:$ListenPort/"
    $listener = New-Object System.Net.HttpListener
    $listener.Prefixes.Add($prefix)

    try {
        $listener.Start()
    } catch {
        Write-Err "Could not bind to $prefix. Is another instance already running?"
        return
    }

    Write-Header "AIOStreams Web Setup Portal Bridge Running"
    Write-Success "Bridge server listening at: $prefix"
    Write-Info "Open the Setup Portal in your browser (http://localhost:8088) to connect your stack!"
    Write-Info "Press Ctrl+C in this terminal window to stop the server.`n"

    # Auto-open browser
    Start-Process $prefix

    try {
        while ($listener.IsListening) {
            $context = $listener.GetContext()
            $request = $context.Request
            $response = $context.Response

            # Enable CORS for local file:/// and localhost
            $response.Headers.Add("Access-Control-Allow-Origin", "*")
            $response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            $response.Headers.Add("Access-Control-Allow-Headers", "Content-Type")

            if ($request.HttpMethod -eq "OPTIONS") {
                $response.StatusCode = 200
                $response.Close()
                continue
            }

            $rawUrl = $request.RawUrl

            if ($request.HttpMethod -eq "GET" -and ($rawUrl -eq "/" -or $rawUrl -eq "/index.html" -or $rawUrl -eq "/dashboard")) {
                # Serve index.html or dashboard.html landing page
                $htmlPath = Join-Path $ScriptDir "index.html"
                if (-not (Test-Path $htmlPath)) {
                    $htmlPath = Join-Path $ScriptDir "dashboard.html"
                }
                if (Test-Path $htmlPath) {
                    $content = [System.IO.File]::ReadAllBytes($htmlPath)
                    $response.ContentType = "text/html; charset=utf-8"
                    $response.OutputStream.Write($content, 0, $content.Length)
                } else {
                    $response.StatusCode = 404
                }
                $response.Close()
            }
            elseif ($request.HttpMethod -eq "GET" -and ($rawUrl -eq "/configurator" -or $rawUrl -eq "/configurator.html")) {
                # Redirect legacy configurator requests to setup portal root
                $response.StatusCode = 302
                $response.Headers.Add("Location", "/")
                $response.Close()
            }
            elseif ($request.HttpMethod -eq "GET" -and $rawUrl -like "/templates/*") {
                # Serve local template JSON files directly
                $cleanPath = $rawUrl.Split('?')[0].TrimStart('/').Replace('/', '\')
                $filePath = Join-Path $ScriptDir $cleanPath
                if ((Test-Path $filePath) -and (-not (Get-Item $filePath).PSIsContainer)) {
                    $content = [System.IO.File]::ReadAllBytes($filePath)
                    $response.ContentType = "application/json; charset=utf-8"
                    $response.OutputStream.Write($content, 0, $content.Length)
                } else {
                    $response.StatusCode = 404
                }
                $response.Close()
            }
            elseif ($request.HttpMethod -eq "GET" -and $rawUrl -eq "/api/templates") {
                # List all available templates by category
                try {
                    $templateRoot = Join-Path $ScriptDir "templates"
                    $categories = @{}
                    if (Test-Path $templateRoot) {
                        Get-ChildItem -Path $templateRoot -Directory | ForEach-Object {
                            $catName = $_.Name
                            $catFiles = @()
                            Get-ChildItem -Path $_.FullName -Filter *.json | ForEach-Object {
                                $catFiles += @{
                                    name = $_.Name
                                    path = "templates/$catName/$($_.Name)"
                                    size = $_.Length
                                }
                            }
                            $categories[$catName] = $catFiles
                        }
                    }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($categories | ConvertTo-Json -Depth 4))
                    $response.ContentType = "application/json"
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                } catch {
                    $response.StatusCode = 500
                }
                $response.Close()
            }
            elseif ($request.HttpMethod -eq "GET" -and ($rawUrl -eq "/api/env" -or $rawUrl -eq "/api/status")) {
                # Return current environment variables and stack status from .env
                try {
                    $envMap = @{}
                    $targetEnv = if (Test-Path (Join-Path $ScriptDir ".env")) { Join-Path $ScriptDir ".env" } else { Join-Path $ScriptDir ".env.example" }
                    if (Test-Path $targetEnv) {
                        Get-Content $targetEnv | ForEach-Object {
                            $trimmed = $_.Trim()
                            if ($trimmed -and -not $trimmed.StartsWith("#") -and $trimmed -match '^([A-Za-z0-9_]+)=(.*)$') {
                                $envMap[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'")
                            }
                        }
                    }
                    $statusObj = [ordered]@{
                        appliance = $true
                        status = "online"
                        docker_ready = $true
                        version = "1.1.0"
                        env = $envMap
                    }
                    # Include flat keys at root as well so both flat & nested consumers resolve perfectly
                    foreach ($k in $envMap.Keys) {
                        $statusObj[$k] = $envMap[$k]
                    }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($statusObj | ConvertTo-Json -Depth 4))
                    $response.ContentType = "application/json"
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                } catch {
                    $response.StatusCode = 500
                }
                $response.Close()
            }
            elseif ($request.HttpMethod -eq "POST" -and ($rawUrl -eq "/api/env" -or $rawUrl -eq "/api/save-env" -or $rawUrl -eq "/api/quick-setup" -or $rawUrl -eq "/api/settings")) {
                # Update all configuration variables in .env
                try {
                    $reader = New-Object System.IO.StreamReader($request.InputStream, [System.Text.Encoding]::UTF8)
                    $body = $reader.ReadToEnd()
                    $json = $body | ConvertFrom-Json

                    $envFile = Join-Path $ScriptDir ".env"
                    if (-not (Test-Path $envFile)) {
                        if (Test-Path (Join-Path $ScriptDir ".env.example")) {
                            Copy-Item (Join-Path $ScriptDir ".env.example") $envFile
                        }
                    }

                    if (Test-Path $envFile) {
                        $lines = Get-Content $envFile
                        $updatedKeys = @{}
                        foreach ($prop in $json.PSObject.Properties) {
                            if ($null -ne $prop.Value) {
                                $updatedKeys[$prop.Name] = "$($prop.Value)".Trim()
                            }
                        }

                        $foundKeys = @{}
                        $newLines = @()
                        foreach ($line in $lines) {
                            $matched = $false
                            $lineTrim = $line.Trim()
                            foreach ($k in $updatedKeys.Keys) {
                                if ($lineTrim -match "^[#\s]*$k=") {
                                    $newLines += "$k=$($updatedKeys[$k])"
                                    $foundKeys[$k] = $true
                                    $matched = $true
                                    break
                                }
                            }
                            if (-not $matched) {
                                $newLines += $line
                            }
                        }

                        foreach ($k in $updatedKeys.Keys) {
                            if (-not $foundKeys.ContainsKey($k)) {
                                $newLines += "$k=$($updatedKeys[$k])"
                            }
                        }

                        [System.IO.File]::WriteAllLines($envFile, $newLines, [System.Text.Encoding]::UTF8)

                        # Set process environment variables
                        foreach ($k in $updatedKeys.Keys) {
                            [System.Environment]::SetEnvironmentVariable($k, $updatedKeys[$k])
                        }
                    }

                    # Trigger bootstrap setup script in background if python is available to re-sync templates immediately
                    $setupScript = Join-Path $ScriptDir "init/bootstrap/setup_stack.py"
                    if (Test-Path $setupScript) {
                        try {
                            $py = (Get-Command python -ErrorAction SilentlyContinue).Source
                            if (-not $py) {
                                if (Test-Path "C:\Program Files\LibreOffice\program\python.exe") {
                                    $py = "C:\Program Files\LibreOffice\program\python.exe"
                                }
                            }
                            if ($py) {
                                Start-Process -FilePath $py -ArgumentList "-u `"$setupScript`"" -WorkingDirectory $ScriptDir -WindowStyle Hidden
                            }
                        } catch {}
                    }

                    $respObj = @{ success = $true; message = "Settings updated in .env" }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($respObj | ConvertTo-Json))
                    $response.ContentType = "application/json"
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                    Write-Success "Updated settings in .env."
                } catch {
                    $errObj = @{ success = $false; error = $_.Exception.Message }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($errObj | ConvertTo-Json))
                    $response.StatusCode = 500
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                }
                $response.Close()
            }
            elseif ($request.HttpMethod -eq "POST" -and $rawUrl -eq "/api/restart") {
                try {
                    Write-Info "Restarting Docker stack..."
                    $restartOutput = docker compose restart 2>&1 | Out-String
                    $respObj = @{ success = $true; output = $restartOutput }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($respObj | ConvertTo-Json))
                    $response.ContentType = "application/json"
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                    Write-Success "Docker stack restarted."
                } catch {
                    $errObj = @{ success = $false; error = $_.Exception.Message }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($errObj | ConvertTo-Json))
                    $response.StatusCode = 500
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                }
                $response.Close()
            }
            elseif ($request.HttpMethod -eq "POST" -and $rawUrl -eq "/api/save") {
                # Save configuration files directly to workspace
                try {
                    $reader = New-Object System.IO.StreamReader($request.InputStream, [System.Text.Encoding]::UTF8)
                    $body = $reader.ReadToEnd()
                    $json = $body | ConvertFrom-Json

                    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

                    # Backup existing files if present
                    if (Test-Path (Join-Path $ScriptDir "docker-compose.yml")) {
                        Copy-Item (Join-Path $ScriptDir "docker-compose.yml") (Join-Path $ScriptDir "docker-compose.yml.$timestamp.bak")
                    }
                    if (Test-Path (Join-Path $ScriptDir ".env")) {
                        Copy-Item (Join-Path $ScriptDir ".env") (Join-Path $ScriptDir ".env.$timestamp.bak")
                    }

                    # Write new files
                    if ($json.compose) {
                        [System.IO.File]::WriteAllText((Join-Path $ScriptDir "docker-compose.yml"), $json.compose, [System.Text.Encoding]::UTF8)
                    }
                    if ($json.env) {
                        [System.IO.File]::WriteAllText((Join-Path $ScriptDir ".env"), $json.env, [System.Text.Encoding]::UTF8)
                    }
                    if ($json.sql) {
                        $sqlDir = Join-Path $ScriptDir "init/postgres"
                        if (-not (Test-Path $sqlDir)) { New-Item -ItemType Directory -Path $sqlDir -Force | Out-Null }
                        [System.IO.File]::WriteAllText((Join-Path $sqlDir "01-init-dbs.sql"), $json.sql, [System.Text.Encoding]::UTF8)
                    }

                    Ensure-Directories

                    $respObj = @{
                        success = $true
                        message = "Files written directly to workspace: docker-compose.yml, .env, init/postgres/01-init-dbs.sql"
                    }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($respObj | ConvertTo-Json))
                    $response.ContentType = "application/json"
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                    Write-Success "Received and saved new configuration directly to workspace."
                } catch {
                    $errObj = @{ success = $false; error = $_.Exception.Message }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($errObj | ConvertTo-Json))
                    $response.StatusCode = 500
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                    Write-Err "Error saving files: $($_.Exception.Message)"
                }
                $response.Close()
            }
            elseif ($request.HttpMethod -eq "POST" -and $rawUrl -eq "/api/deploy") {
                # Trigger Docker compose up -d
                try {
                    Write-Info "Executing: docker compose up -d..."
                    $deployOutput = docker compose up -d 2>&1 | Out-String
                    $respObj = @{
                        success = $true
                        output = $deployOutput
                    }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($respObj | ConvertTo-Json))
                    $response.ContentType = "application/json"
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                    Write-Success "Stack deployed successfully!"
                } catch {
                    $errObj = @{ success = $false; error = $_.Exception.Message }
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes(($errObj | ConvertTo-Json))
                    $response.StatusCode = 500
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                    Write-Err "Deployment error: $($_.Exception.Message)"
                }
                $response.Close()
            }
            elseif ($request.HttpMethod -eq "GET" -and $rawUrl -eq "/api/status") {
                try {
                    $statusOutput = docker compose ps --format json 2>&1 | Out-String
                    $respBytes = [System.Text.Encoding]::UTF8.GetBytes($statusOutput)
                    $response.ContentType = "application/json"
                    $response.OutputStream.Write($respBytes, 0, $respBytes.Length)
                } catch {
                    $response.StatusCode = 500
                }
                $response.Close()
            }
            else {
                $response.StatusCode = 404
                $response.Close()
            }
        }
    } finally {
        $listener.Stop()
        $listener.Close()
        Write-Info "Configurator server stopped."
    }
}

# Interactive CLI Wizard
function Invoke-CLIWizard {
    Write-Header "Interactive Console Configuration Wizard"
    Ensure-Directories

    $existingEnv = @{}
    $envSource = if (Test-Path (Join-Path $ScriptDir ".env")) { Join-Path $ScriptDir ".env" } else { Join-Path $ScriptDir ".env.example" }
    if (Test-Path $envSource) {
        Get-Content $envSource | ForEach-Object {
            $t = $_.Trim()
            if ($t -and -not $t.StartsWith("#") -and $t -match '^([A-Za-z0-9_]+)=(.*)$') {
                $existingEnv[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'")
            }
        }
    }

    $currentBaseUrl = if ($existingEnv.ContainsKey("BASE_URL") -and $existingEnv["BASE_URL"]) { $existingEnv["BASE_URL"] } else { "https://aio.yourdomain.com" }
    $currentTmdb = if ($existingEnv.ContainsKey("TMDB_API_KEY")) { $existingEnv["TMDB_API_KEY"] } else { "" }
    $currentRd = if ($existingEnv.ContainsKey("REALDEBRID_API_KEY")) { $existingEnv["REALDEBRID_API_KEY"] } else { "" }
    $currentTvdb = if ($existingEnv.ContainsKey("TVDB_API_KEY")) { $existingEnv["TVDB_API_KEY"] } else { "" }

    Write-Host "Enter your external credentials (press Enter to accept default):`n"
    $baseUrlInput = Read-Host "AIOStreams Public Domain / Base URL [$currentBaseUrl]"
    if (-not [string]::IsNullOrWhiteSpace($baseUrlInput)) { $currentBaseUrl = $baseUrlInput }

    $tmdbInput = Read-Host "TMDB v3 API Key [$currentTmdb]"
    if (-not [string]::IsNullOrWhiteSpace($tmdbInput)) { $currentTmdb = $tmdbInput }

    $tvdbInput = Read-Host "TheTVDB v4 API Key [$currentTvdb]"
    if (-not [string]::IsNullOrWhiteSpace($tvdbInput)) { $currentTvdb = $tvdbInput }

    $rdInput = Read-Host "Real-Debrid API Token [$currentRd]"
    if (-not [string]::IsNullOrWhiteSpace($rdInput)) { $currentRd = $rdInput }

    # Retain or generate secrets
    $secretKey = if ($existingEnv.ContainsKey("SECRET_KEY") -and $existingEnv["SECRET_KEY"]) { $existingEnv["SECRET_KEY"] } else { [System.Guid]::NewGuid().ToString("N") + [System.Guid]::NewGuid().ToString("N") }
    $pgPass = if ($existingEnv.ContainsKey("POSTGRES_PASSWORD") -and $existingEnv["POSTGRES_PASSWORD"]) { $existingEnv["POSTGRES_PASSWORD"] } else { "pg_" + [System.Guid]::NewGuid().ToString("N").Substring(0, 16) }
    $prowlarrKey = if ($existingEnv.ContainsKey("PROWLARR_API_KEY") -and $existingEnv["PROWLARR_API_KEY"]) { $existingEnv["PROWLARR_API_KEY"] } else { "prow_" + [System.Guid]::NewGuid().ToString("N").Substring(0, 16) }
    $stremthruAuth = if ($existingEnv.ContainsKey("STREMTHRU_AUTH") -and $existingEnv["STREMTHRU_AUTH"]) { $existingEnv["STREMTHRU_AUTH"] } else { "admin:" + [System.Guid]::NewGuid().ToString("N").Substring(0, 12) }
    $mediaflowPass = if ($existingEnv.ContainsKey("MEDIAFLOW_PASS") -and $existingEnv["MEDIAFLOW_PASS"]) { $existingEnv["MEDIAFLOW_PASS"] } else { "mf_" + [System.Guid]::NewGuid().ToString("N").Substring(0, 12) }
    $addonPassword = if ($existingEnv.ContainsKey("ADDON_PASSWORD") -and $existingEnv["ADDON_PASSWORD"]) { $existingEnv["ADDON_PASSWORD"] } else { "admin" }
    $postersKey = if ($existingEnv.ContainsKey("POSTERSPLUS_ACCESS_KEY") -and $existingEnv["POSTERSPLUS_ACCESS_KEY"]) { $existingEnv["POSTERSPLUS_ACCESS_KEY"] } else { $addonPassword }
    $adminEmail = if ($existingEnv.ContainsKey("ADMIN_EMAIL") -and $existingEnv["ADMIN_EMAIL"]) { $existingEnv["ADMIN_EMAIL"] } else { "admin@mediafusion.local" }

    $pmKey = if ($existingEnv.ContainsKey("PREMIUMIZE_API_KEY")) { $existingEnv["PREMIUMIZE_API_KEY"] } else { "" }
    $adKey = if ($existingEnv.ContainsKey("ALLDEBRID_API_KEY")) { $existingEnv["ALLDEBRID_API_KEY"] } else { "" }
    $tbKey = if ($existingEnv.ContainsKey("TORBOX_API_KEY")) { $existingEnv["TORBOX_API_KEY"] } else { "" }
    $dlKey = if ($existingEnv.ContainsKey("DEBRIDLINK_API_KEY")) { $existingEnv["DEBRIDLINK_API_KEY"] } else { "" }
    $faKey = if ($existingEnv.ContainsKey("FANART_API_KEY")) { $existingEnv["FANART_API_KEY"] } else { "" }
    $rpKey = if ($existingEnv.ContainsKey("RPDB_API_KEY")) { $existingEnv["RPDB_API_KEY"] } else { "" }
    $mdKey = if ($existingEnv.ContainsKey("MDBLIST_API_KEY")) { $existingEnv["MDBLIST_API_KEY"] } else { "" }
    $geKey = if ($existingEnv.ContainsKey("GEMINI_API_KEY")) { $existingEnv["GEMINI_API_KEY"] } else { "" }

    # Write .env
    $envContent = @"
# ==============================================================================
#                      ALL-IN-ONE LOCAL STREMIO BACKEND (.env)
# ==============================================================================
BASE_URL=$currentBaseUrl
TMDB_API_KEY=$currentTmdb
REALDEBRID_API_KEY=$currentRd
PREMIUMIZE_API_KEY=$pmKey
ALLDEBRID_API_KEY=$adKey
TORBOX_API_KEY=$tbKey
DEBRIDLINK_API_KEY=$dlKey
TVDB_API_KEY=$currentTvdb
FANART_API_KEY=$faKey
RPDB_API_KEY=$rpKey
MDBLIST_API_KEY=$mdKey
GEMINI_API_KEY=$geKey
ADDON_PASSWORD=$addonPassword

SECRET_KEY=$secretKey
POSTGRES_PASSWORD=$pgPass
PROWLARR_API_KEY=$prowlarrKey
POSTERSPLUS_ACCESS_KEY=$postersKey
ADMIN_EMAIL=$adminEmail
STREMTHRU_AUTH=$stremthruAuth
MEDIAFLOW_PASS=$mediaflowPass

# ==============================================================================
# COMMUNITY TEMPLATES & STREAM EXPRESSION LANGUAGE (SEL) AUTO-SYNC
# ==============================================================================
TEMPLATE_URLS=["https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/Tamtaro-All-Templates-for-AIOStreams.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/refs/heads/main/all-templates.json"]
TEMPLATE_REFRESH_INTERVAL=3600
WHITELISTED_SYNC_REFRESH_INTERVAL=3600
FEATURED_TEMPLATE_IDS=tamtaro.complete,Vidhin05.regex-template,Vidhin05.english-template
SEL_SYNC_ACCESS=all
WHITELISTED_REGEX_PATTERNS_URLS=["https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/English/regexes.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/German/regexes.json"]
WHITELISTED_SEL_URLS=["https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-ESEs-extended.json","https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-ESEs-standard.json","https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-ISEs.json","https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-PSEs.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/English/expressions.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/German/expressions.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/English/legacy-expressions.json"]
"@
    Set-Content -Path (Join-Path $ScriptDir ".env") -Value $envContent -Encoding utf8
    Write-Success ".env generated and saved."

    # Write 01-init-dbs.sql
    $sqlContent = @"
SELECT 'CREATE DATABASE zilean' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zilean')\gexec
SELECT 'CREATE DATABASE mediafusion' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mediafusion')\gexec
SELECT 'CREATE DATABASE aiometadata' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'aiometadata')\gexec
"@
    Set-Content -Path (Join-Path $ScriptDir "init/postgres/01-init-dbs.sql") -Value $sqlContent -Encoding utf8
    Write-Success "init/postgres/01-init-dbs.sql verified."

    $startNow = Read-Host "`nStart Docker stack now? (y/n) [y]"
    if ($startNow -ne 'n') {
        Start-Stack
    }
}

# Start the stack
function Start-Stack {
    param([string]$ComposeProfile = "")
    Write-Header "Starting Docker Compose Stack"
    Ensure-Directories
    $envPath = Join-Path $ScriptDir ".env"
    $examplePath = Join-Path $ScriptDir ".env.example"
    if (-not (Test-Path $envPath)) {
        if (Test-Path $examplePath) {
            Write-Warn ".env not found. Copying .env.example with unique security keys..."
            Copy-Item $examplePath $envPath
            $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
            $b = New-Object byte[] 32; $rng.GetBytes($b); $randSecret = -join ($b | ForEach-Object { "{0:x2}" -f $_ })
            $b16 = New-Object byte[] 16; $rng.GetBytes($b16); $randPg = -join ($b16 | ForEach-Object { "{0:x2}" -f $_ })
            $b16_2 = New-Object byte[] 16; $rng.GetBytes($b16_2); $randProwl = -join ($b16_2 | ForEach-Object { "{0:x2}" -f $_ })
            (Get-Content $envPath) `
                -replace 'e2c019d4536f9a039b56f8f1dfba8919634e2c8846bb1999252c79213bc01b09', $randSecret `
                -replace 'postgres_supersecret_db_pass_2026', $randPg `
                -replace 'prowlarr_internal_secret_key_99', $randProwl |
                Set-Content $envPath
            Write-Success "Generated unique cryptographic keys for SECRET_KEY, POSTGRES_PASSWORD, and PROWLARR_API_KEY."
        }
    }
    if ($ComposeProfile) {
        Write-Info "Launching with profile: $ComposeProfile..."
        docker compose --profile $ComposeProfile up -d
    } else {
        docker compose up -d
    }
    Write-Success "Docker stack start command completed."
    Show-StremioLinks
}

# Stop the stack
function Stop-Stack {
    Write-Header "Stopping Docker Compose Stack"
    docker compose down
    Write-Success "Docker stack stopped."
}

# Display Status & Health
function Show-StackStatus {
    Write-Header "Stack Service Status"
    docker compose ps
}

# Show Stremio links & endpoints
function Show-StremioLinks {
    Write-Header "Stremio Addon Installation & Service Links"
    $baseUrl = "https://aio.yourdomain.com"
    if (Test-Path (Join-Path $ScriptDir ".env")) {
        Get-Content (Join-Path $ScriptDir ".env") | ForEach-Object {
            if ($_ -match '^BASE_URL=(.*)$') { $baseUrl = $matches[1] }
        }
    }

    Write-Host "Central AIOStreams Addon Manifest:" -ForegroundColor Green
    Write-Host "  $baseUrl/manifest.json" -ForegroundColor White

    Write-Host "`nWeb Management Portals:" -ForegroundColor Cyan
    Write-Host "  • Appliance Hub (Landing Page): http://localhost:8088"
    Write-Host "  • AIOStreams Portal:     http://localhost:3001"
    Write-Host "  • Stremio Web Player:    http://localhost:8082"
    Write-Host "  • Nuvio Web Player:      http://localhost:8085"
    Write-Host "  • SlickSync Hub:         http://localhost:8086"
    Write-Host "  • Debrid Cloud Search:   http://localhost:3011"
    Write-Host "  • AIOMetadata:           http://localhost:4005"
    Write-Host "  • SubSense Subtitles:    http://localhost:3100"
    Write-Host "  • InfiniDysk Usenet:     http://localhost:3005"
    Write-Host "  • Comet Scraper:         http://localhost:8000"
    Write-Host "  • MediaFusion:           http://localhost:8001"
    Write-Host "  • Sootio Multi-Scraper:  http://localhost:55771"
    Write-Host "  • Anime Kitsu:           http://localhost:7005"
    Write-Host "  • Prowlarr Indexers:     http://localhost:9696"
    Write-Host "  • Zilean Hash Cache:     http://localhost:8181"
    Write-Host "  • StremThru Proxy UI:    http://localhost:8080"
    Write-Host "  • MediaFlow Proxy:       http://localhost:8888"

    Write-Host "`nOptional external Cinemeta tool:" -ForegroundColor Yellow
    Write-Host "  1. Visit Hidden Cinemeta (external): https://hidden-cinemeta.vercel.app/"
    Write-Host "  2. Input your Stremio AuthKey to hide Cinemeta's cloud catalogs."
    Write-Host "  3. AIOMetadata (:4005) serves as your primary local rich metadata & catalog provider."
    Write-Host ""
}

# Build All-In-One Appliance Image (Single Container Package)
function Build-AllInOneImage {
    Write-Header "Building All-In-One Appliance Image (GHCR/Local Package)"
    Write-Info "Executing: docker build -t aiostreams-aio:latest -t ghcr.io/ooflyeyesoo/aiostreams-aio:latest -f ./docker/all-in-one/Dockerfile ."
    docker build -t aiostreams-aio:latest -t ghcr.io/ooflyeyesoo/aiostreams-aio:latest -f ./docker/all-in-one/Dockerfile .
    if ($LASTEXITCODE -eq 0) {
        Write-Success "All-In-One appliance image successfully built!"
        Write-Info "Local tags available for running or testing:"
        Write-Host "  • aiostreams-aio:latest" -ForegroundColor White
        Write-Host "  • ghcr.io/ooflyeyesoo/aiostreams-aio:latest" -ForegroundColor White
        Write-Host "`nTo push to GHCR (requires GitHub PAT with write:packages):" -ForegroundColor Cyan
        Write-Host "  docker push ghcr.io/ooflyeyesoo/aiostreams-aio:latest" -ForegroundColor DarkGray
    } else {
        Write-Err "Build failed. Check docker logs above."
    }
}

# Main Menu
function Show-Menu {
    Clear-Host
    Write-Header "AIOStreams Self-Hosted All-In-One Control Center"
    Write-Host " 1) Start Web Setup Portal & Direct-Deploy Server (http://localhost:8088)" -ForegroundColor Green
    Write-Host " 2) Interactive CLI Setup Wizard (Configure in terminal)"
    Write-Host " 3) Run Pre-Flight Diagnostics & Port Collision Check"
    Write-Host " 4) Start Stack (docker compose up -d)"
    Write-Host " 5) View Stack Status & Health (docker compose ps)"
    Write-Host " 6) Stop Stack (docker compose down)"
    Write-Host " 7) View Stremio Manifest & Service URLs"
    Write-Host " 8) Build All-In-One Appliance Docker Package (ghcr.io/ooflyeyesoo/aiostreams-aio)"
    Write-Host " 0) Exit"
    Write-Host ""
    $choice = Read-Host "Select an option [1-8, 0]"

    switch ($choice) {
        "1" { Start-ConfigServer -ListenPort $Port }
        "2" { Invoke-CLIWizard }
        "3" { Test-SystemPrerequisites; pause }
        "4" { Start-Stack; pause }
        "5" { Show-StackStatus; pause }
        "6" { Stop-Stack; pause }
        "7" { Show-StremioLinks; pause }
        "8" { Build-AllInOneImage; pause }
        "0" { exit }
        default { Write-Warn "Invalid choice." }
    }
}

# CLI Argument routing
if ($Serve) {
    Start-ConfigServer -ListenPort $Port
} elseif ($Wizard) {
    Invoke-CLIWizard
} elseif ($Check) {
    Test-SystemPrerequisites
} elseif ($Start) {
    Start-Stack -ComposeProfile $Profile
} elseif ($Stop) {
    Stop-Stack
} elseif ($Status) {
    Show-StackStatus
} elseif ($BuildAppliance) {
    Build-AllInOneImage
} else {
    Show-Menu
}
