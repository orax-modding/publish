# Validates the Hexium token from .env against the real tcli upload endpoint.
# tcli sends: POST {repo}/api/experimental/usermedia/initiate-upload/
#   Authorization: Bearer <token>
#   body: {"filename":"...","file_size_bytes":<long>}   (FileData model)
#   expects: 201 Created
$ErrorActionPreference = 'Stop'
$line = Get-Content .env | Where-Object { $_ -match '^HEXIUM_API_TOKEN\s*=' } | Select-Object -First 1
$token = ($line -replace '^HEXIUM_API_TOKEN\s*=\s*', '').Trim()
if (-not $token) { Write-Host 'Token missing in .env'; exit 1 }

$uri = 'https://hexium.gg/api/experimental/usermedia/initiate-upload/'
$body = '{"filename":"publish.zip","file_size_bytes":1024}'
$tests = @(
    @{ Label = '.env token (Bearer)'; Header = "Bearer $token" },
    @{ Label = 'garbage token (Bearer)'; Header = 'Bearer definitely-not-a-real-token' },
    @{ Label = 'no auth'; Header = $null }
)

foreach ($t in $tests) {
    $h = @{}
    if ($t.Header) { $h['Authorization'] = $t.Header }
    try {
        $r = Invoke-WebRequest -Uri $uri -Method Post -Headers $h -ContentType 'application/json' -Body $body -UseBasicParsing -TimeoutSec 15
        Write-Host "[$($t.Label)] -> $([int]$r.StatusCode) $($r.Content)"
    }
    catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $code = [int]$resp.StatusCode
            $content = ''
            try {
                $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
                $content = $reader.ReadToEnd()
            }
            catch { }
            Write-Host "[$($t.Label)] -> $code $content"
        }
        else {
            Write-Host "[$($t.Label)] -> EXC $($_.Exception.Message)"
        }
    }
}