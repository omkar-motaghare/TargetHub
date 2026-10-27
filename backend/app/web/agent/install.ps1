<#
.SYNOPSIS
  Installs the TargetHub Agent on Windows and registers it to start at boot.

.DESCRIPTION
  Downloads targethub_agent.py from the TargetHub server, verifies its SHA-256,
  installs pyserial (needed for COM ports), writes a protected configuration
  with the single-use enrollment token, and registers a Scheduled Task that
  runs the Agent as SYSTEM at startup and restarts it if it stops.

  Run from an elevated PowerShell (Run as administrator). The TargetHub
  "Enroll Agent" page generates the complete command for you.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1 `
    -TargetHubUrl https://hub.example.com -EnrollmentToken enroll_xxx -AgentSha256 <sha256>
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$TargetHubUrl,
  [Parameter(Mandatory = $true)][string]$EnrollmentToken,
  [Parameter(Mandatory = $true)][string]$AgentSha256,
  [switch]$AllowInsecureHttp,
  [switch]$SkipPyserial,
  [string]$InstallDir = '',
  [string]$ConfigDir = '',
  [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Fail([string]$Message) {
  Write-Host "ERROR: $Message" -ForegroundColor Red
  exit 1
}

# --- validation -------------------------------------------------------------
if ($AgentSha256 -notmatch '^[0-9a-fA-F]{64}$') { Fail '-AgentSha256 must be a 64-character hex digest.' }
if ($TargetHubUrl -match '^http://') {
  if (-not $AllowInsecureHttp) { Fail 'Refusing plain http:// TargetHub URL; use https:// or pass -AllowInsecureHttp.' }
} elseif ($TargetHubUrl -notmatch '^https://') {
  Fail '-TargetHubUrl must start with https:// (or http:// with -AllowInsecureHttp).'
}
$TargetHubUrl = $TargetHubUrl.TrimEnd('/')
if (-not $InstallDir) { $InstallDir = Join-Path $env:ProgramFiles 'TargetHub\Agent' }
if (-not $ConfigDir) { $ConfigDir = Join-Path $env:ProgramData 'TargetHub\agent' }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Fail 'Run this installer from an elevated PowerShell (Run as administrator).'
}

# --- python -----------------------------------------------------------------
function Find-Python {
  if ($Python) { return $Python }
  foreach ($candidate in @('py', 'python', 'python3')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
      $exe = $cmd.Source
      $arguments = @()
      if ($candidate -eq 'py') { $arguments = @('-3') }
      try {
        $version = & $exe @arguments -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$version -ge [version]'3.10') {
          # Resolve the real interpreter so the scheduled task does not depend on PATH.
          return (& $exe @arguments -c 'import sys; print(sys.executable)').Trim()
        }
      } catch { continue }
    }
  }
  return $null
}
$PythonExe = Find-Python
if (-not $PythonExe) { Fail 'Python 3.10+ is required. Install it from https://www.python.org/downloads/ (enable "Add to PATH").' }
Write-Host "Using Python: $PythonExe"

# --- download + verify --------------------------------------------------------
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.ServicePointManager]::SecurityProtocol
New-Item -ItemType Directory -Force -Path $InstallDir, $ConfigDir | Out-Null
$AgentPath = Join-Path $InstallDir 'targethub_agent.py'
$TempPath = "$AgentPath.tmp"
Invoke-WebRequest -UseBasicParsing -Uri "$TargetHubUrl/web/agent/targethub_agent.py" -OutFile $TempPath
$actual = (Get-FileHash -Path $TempPath -Algorithm SHA256).Hash
if ($actual -ne $AgentSha256) {
  Remove-Item -Force $TempPath
  Fail "Agent checksum mismatch (expected $AgentSha256, got $actual); aborting."
}
& $PythonExe -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" $TempPath
if ($LASTEXITCODE -ne 0) { Remove-Item -Force $TempPath; Fail 'Downloaded agent is not valid Python.' }
Move-Item -Force $TempPath $AgentPath

if (-not $SkipPyserial) {
  Write-Host 'Installing pyserial (serial/COM port support)...'
  & $PythonExe -m pip install --disable-pip-version-check --quiet --upgrade pyserial
  if ($LASTEXITCODE -ne 0) {
    Write-Warning 'pyserial could not be installed; COM ports will be unavailable until you run: python -m pip install pyserial'
  }
}

# --- configuration --------------------------------------------------------------
$sha = [Security.Cryptography.SHA256]::Create()
$tokenHash = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($EnrollmentToken)) | ForEach-Object { $_.ToString('x2') })
$Instance = $tokenHash.Substring(0, 16)
$ConfigPath = Join-Path $ConfigDir "$Instance.json"
$LogPath = Join-Path $ConfigDir "$Instance.log"

if (-not (Test-Path $ConfigPath) -or -not (Select-String -Path $ConfigPath -Pattern '"agent_id"' -Quiet)) {
  $config = [ordered]@{
    targethub_url               = $TargetHubUrl
    enrollment_token            = $EnrollmentToken
    heartbeat_interval          = 15
    operation_poll_wait_seconds = 10
    request_timeout             = 15
    allow_insecure_http         = [bool]$AllowInsecureHttp
    resources                   = @()
  }
  $config | ConvertTo-Json -Depth 5 | Set-Content -Path $ConfigPath -Encoding UTF8
}
# Only SYSTEM and Administrators may read the credential.
& icacls $ConfigDir /inheritance:r /grant:r 'SYSTEM:(OI)(CI)F' 'Administrators:(OI)(CI)F' | Out-Null

# --- scheduled task ---------------------------------------------------------------
$TaskName = "TargetHub Agent $Instance"
$cmdLine = "/c `"`"$PythonExe`" `"$AgentPath`" --config `"$ConfigPath`" >> `"$LogPath`" 2>&1`""
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $cmdLine -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -StartWhenAvailable -MultipleInstances IgnoreNew
$taskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
  -Principal $taskPrincipal -Description 'TargetHub Agent' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host ''
Write-Host "TargetHub Agent installed and started: scheduled task '$TaskName'" -ForegroundColor Green
Write-Host "Config: $ConfigPath"
Write-Host "Logs:   $LogPath"
Write-Host "Status: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "Remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
