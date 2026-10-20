# Discovers the current user / teams (namespace) on Hexium using the .env token.
$ErrorActionPreference = 'Stop'
$line = Get-Content .env | Where-Object { $_ -match '^HEXIUM_TCLI_AUTH_TOKEN\s*=' } | Select-Object -First 1
$token = ($line -replace '^HEXIUM_TCLI_AUTH_TOKEN\s*=\s*', '').Trim()
if (-not $token) { Write-Host 'Token missing'; exit 1 }

$urls = 'https://hexium.gg/api/current-user/',
        'https://hexium.gg/api/experimental/current-user/',
        'https://hexium.gg/api/v1/team/',
        'https://hexium.gg/api/experimental/team/',
        'https://hexium.gg/api/current-user/service-accounts/',
        'https://hexium.gg/api/experimental/current-user/service-accounts/',
        'https://hexium.gg/api/v1/user/'

foreach ($u in $urls) {
    try {
        $r = Invoke-WebRequest -Uri $u -Headers @{ Authorization = "Bearer $token" } -UseBasicParsing -TimeoutSec 10
        $c = [string]$r.Content
        $prev = if ($c.Length -gt 300) { $c.Substring(0, 300) } else { $c }
        Write-Host "$u -> $([int]$r.StatusCode) $prev"
    }
    catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $code = [int]$resp.StatusCode
            $c = ''
            try {
                $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
                $c = $sr.ReadToEnd()
            }
            catch { }
            $prev = if ($c.Length -gt 200) { $c.Substring(0, 200) } else { $c }
            Write-Host "$u -> $code $prev"
        }
        else {
            Write-Host "$u -> EXC $($_.Exception.Message)"
        }
    }
}